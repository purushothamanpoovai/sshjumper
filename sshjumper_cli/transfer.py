"""-U / -D file transfer: rsync when both ends have it, scp otherwise.

rsync only sends what changed, so re-sending a file or folder that is already
(mostly) there is quick. Files are written to a temporary name and renamed
when complete, so an interrupted transfer never leaves a half-written file in
place; the partial data is kept in ``.rsync-partial`` and resumed next time.
Nothing on the destination is ever deleted.

Every step (the remote check, rsync, an scp fallback) shares one SSH
connection (ControlMaster in a private 0700 directory), so the jump chain and
TOTP are authenticated only once.

Copy semantics match ``scp -r``:

    -U dir  /tmp/        -> /tmp/dir          (existing directory: copy into it)
    -U dir  /tmp/new     -> /tmp/new          (missing target: becomes the copy)
    -U file /tmp/name    -> /tmp/name
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from sshjumper_cli import ui
from sshjumper_cli.ssh_config import GeneratedSSHConfig

# rsync exit codes that mean rsync itself is the problem, so scp may work:
# 1 syntax/usage (older rsync), 2 protocol incompatibility, 4 unsupported
# action, 5 protocol start-up, 12 data stream (e.g. broken remote rsync),
# 14 IPC, 127 not found. Missing files (23), Ctrl-C (20), connection loss
# (255) and the like are reported as they are: scp would fail the same way.
_FALLBACK = {1, 2, 4, 5, 12, 14, 127}
PARTIAL_DIR = ".rsync-partial"


def local_path(path: str) -> str:
    """Keep scp/rsync from reading ``a:b`` as host ``a`` or ``-x`` as an option."""
    first = path.split("/", 1)[0]
    return f"./{path}" if ":" in first or path.startswith("-") else path


MIN_RSYNC = (3, 4, 0)  # 3.4.0 fixes CVE-2024-12084..12088 (malicious-server attacks)


def _rsync_ok() -> bool:
    """Local rsync present and new enough to be safe against a hostile server."""
    if shutil.which("rsync") is None:
        return False
    try:
        out = subprocess.run(["rsync", "--version"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    match = re.search(r"version\s+(\d+)\.(\d+)\.(\d+)", out)
    return bool(match) and tuple(int(x) for x in match.groups()) >= MIN_RSYNC


def _remote_path(path: str) -> str:
    """Remote path relative to the login directory (rsync / test don't expand ``~``)."""
    if path in ("", "~", "~/"):
        return "."
    if path.startswith("~/"):
        return path[2:]
    return path


def _strip_slash(path: str) -> str:
    """``dir/`` copies ``dir`` itself (as scp does), not just its contents."""
    stripped = path.rstrip("/")
    return stripped or path  # keep "/" as is


def _run(cmd: list[str], env: dict[str, str] | None, **kwargs) -> int:
    try:
        return subprocess.run(cmd, env=env, **kwargs).returncode
    except KeyboardInterrupt:
        print("\nTransfer interrupted.", file=sys.stderr)
        return 130


class _Connection:
    """One shared SSH connection for every command of a transfer."""

    def __init__(self, generated: GeneratedSSHConfig, env: dict[str, str] | None):
        self.alias = generated.final_alias
        self.env = env
        base = tempfile.gettempdir() if len(tempfile.gettempdir()) < 40 else "/tmp"
        self.dir = Path(tempfile.mkdtemp(prefix="sshj-cm-", dir=base))  # mode 0700
        self.options = [
            "-F", str(generated.path),
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath={self.dir}/%C",
            "-o", "ControlPersist=120",
        ]

    def ssh_command(self) -> str:
        """The ``-e`` value for rsync: reuse the master, never become one.

        A new master would stay in the background holding rsync's output
        pipe open, so if the master is gone rsync just connects directly.
        """
        options = [o.replace("ControlMaster=auto", "ControlMaster=no") for o in self.options]
        return shlex.join(["ssh", *options])

    def probe(self, script: str) -> tuple[int, set[str]]:
        """Run a small remote check; returns (exit code, output words).

        Output goes to a file, not a pipe: the backgrounded master keeps the
        stdout it inherited open, so reading a pipe would never finish.
        """
        out = self.dir / "probe.out"
        with open(out, "wb") as handle:
            rc = _run(
                ["ssh", *self.options, self.alias, script],
                self.env,
                stdin=subprocess.DEVNULL,
                stdout=handle,
            )
        return rc, set(out.read_text(errors="replace").split())

    def close(self) -> None:
        subprocess.run(
            ["ssh", *self.options, "-O", "exit", self.alias],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=self.env,
            check=False,
        )
        shutil.rmtree(self.dir, ignore_errors=True)


def _scp(conn_options: list[str], alias: str, direction: str, source: str,
         destination: str, quiet: bool, verbose: bool, env: dict[str, str] | None) -> int:
    cmd = ["scp", *conn_options, "-r", "-C"]
    if quiet:
        cmd.append("-q")
    if verbose:
        cmd.append("-v")
    remote = f"{alias}:"
    if direction == "upload":
        cmd.extend([local_path(source), remote + destination])
    else:
        cmd.extend([remote + source, local_path(destination)])
    return _run(cmd, env)


_PROGRESS_RE = re.compile(r"^\s*([\d,.]+)\s+(\d+)%\s+(\S+/s)\s+(\d+:\d\d:\d\d)")
_STAT_RE = re.compile(r"^(Number of regular files transferred|Total transferred file size):\s*([\d,.]+)")


def _size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def _number(text: str) -> int:
    return int(re.sub(r"\D", "", text) or 0)


def _run_rsync_with_summary(cmd: list[str], direction: str, env: dict[str, str] | None) -> int:
    """Run rsync, turn its raw progress/stats into one live line and a summary."""
    started = time.monotonic()
    stats: dict[str, int] = {}
    try:
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE)
    except OSError:
        return 127
    buffer = b""
    try:
        if proc.stdout is None:
            return proc.wait()
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk
            parts = re.split(rb"[\r\n]", buffer)
            buffer = parts.pop()
            for raw in parts:
                line = raw.decode(errors="replace")
                progress = _PROGRESS_RE.match(line)
                stat = _STAT_RE.match(line)
                if progress:
                    done, pct, speed, eta = progress.groups()
                    left = f"  {eta} left" if pct != "100" else ""
                    ui.progress(direction, f"{pct}%  {_size(_number(done))}  {speed}{left}")
                elif stat:
                    stats[stat.group(1)] = _number(stat.group(2))
                elif line.strip() and not re.match(r"^(Number of|Total |Literal data|Matched data|File list|sent |total size)", line):
                    ui.clear_progress()
                    print(line)  # e.g. file names with -v
        rc = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        ui.clear_progress()
        print("\nTransfer interrupted.", file=sys.stderr)
        return 130

    ui.clear_progress()
    if rc == 0:
        files = stats.get("Number of regular files transferred", 0)
        elapsed = time.monotonic() - started
        if files == 0:
            ui.mark(direction, "ok", "✓ up to date")
        else:
            size = _size(stats.get("Total transferred file size", 0))
            ui.mark(direction, "ok", f"✓ {files} file{'s' if files != 1 else ''} · {size} · {elapsed:.0f}s")
        ui.end_line()
    return rc


def scp_command(generated: GeneratedSSHConfig, direction: str, source: str,
                destination: str, quiet: bool = False, verbose: bool = False) -> list[str]:
    """Plain scp command (shown by ``-ii`` and used when rsync is not installed)."""
    cmd = ["scp", "-F", str(generated.path), "-r", "-C"]
    if quiet:
        cmd.append("-q")
    if verbose:
        cmd.append("-v")
    remote = f"{generated.final_alias}:"
    if direction == "upload":
        return [*cmd, local_path(source), remote + destination]
    return [*cmd, remote + source, local_path(destination)]


def run_transfer(
    generated: GeneratedSSHConfig,
    direction: str,
    source: str,
    destination: str,
    quiet: bool = False,
    verbose: bool = False,
    env: dict[str, str] | None = None,
) -> int:
    if not _rsync_ok():
        return _run(scp_command(generated, direction, source, destination, quiet, verbose), env)

    conn = _Connection(generated, env)
    try:
        source = _strip_slash(source)
        if direction == "upload":
            src_is_dir = os.path.isdir(source)
            remote_dst = _remote_path(destination)
            checks = [f"[ -d {shlex.quote(remote_dst)} ] && echo dst_dir"]
        else:
            remote_src = _remote_path(source)
            dst_is_dir = os.path.isdir(destination)
            checks = [f"[ -d {shlex.quote(remote_src)} ] && echo src_dir"]
        script = "; ".join(["command -v rsync >/dev/null 2>&1 && echo has_rsync", *checks, "true"])

        rc, found = conn.probe(script)
        if rc == 255 or rc == 130:
            return rc  # could not connect / interrupted: scp would fail the same way
        if rc != 0 or "has_rsync" not in found:
            return _scp(conn.options, conn.alias, direction, source, destination, quiet, verbose, env)

        if direction == "upload":
            dst_is_dir = "dst_dir" in found
            src_arg, dst_arg = local_path(source), f"{conn.alias}:{remote_dst}"
        else:
            src_is_dir = "src_dir" in found
            src_arg, dst_arg = f"{conn.alias}:{remote_src}", local_path(destination)
        if src_is_dir and not dst_is_dir:
            src_arg += "/"  # missing target becomes the copy (scp -r behaviour)
        elif dst_is_dir and not dst_arg.endswith("/"):
            dst_arg += "/"  # copy into the existing directory

        cmd = [
            "rsync", "-rlptz", "--safe-links", "--protect-args", f"--partial-dir={PARTIAL_DIR}",
            "-e", conn.ssh_command(),
        ]
        if quiet:
            cmd.append("-q")
        else:
            cmd.extend(["--info=progress2", "--stats"])
        if verbose:
            cmd.append("-v")
        if quiet:
            rc = _run([*cmd, src_arg, dst_arg], env)
        else:
            rc = _run_rsync_with_summary([*cmd, src_arg, dst_arg], direction, env)
        if rc not in _FALLBACK:
            return rc

        ui.end_line()
        ui.mark(direction, "warn", f"rsync failed ({rc}), retrying with scp")
        ui.end_line()
        return _scp(conn.options, conn.alias, direction, source, destination, quiet, verbose, env)
    finally:
        conn.close()
