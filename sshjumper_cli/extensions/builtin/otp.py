"""Builtin extension: answer per-hop TOTP prompts automatically.

Hops opt in with ``totp:`` (on the hop or its ``_hosts`` template)::

    totp: keepass:jump_server_gw     # TOTP stored on that KeePass entry
    totp: env:GW_TOTP_SECRET         # base32 secret / otpauth URI in an env var
    totp: file:~/.ssh/sshjumper/totp/gw.key   # file must be chmod 600
    totp: JBSWY3DPEHPK3PXP           # inline base32 (or otpauth://totp/...)

How it works: ssh runs with ``SSH_ASKPASS_REQUIRE=force`` and our askpass
helper (``sshjumper_cli/askpass.py``). For every prompt the helper asks this
process over a private unix socket. A "(user@host) Verification code:" prompt
for a hop with ``totp`` gets a code generated at that moment; every other
prompt (host keys, passwords, retries after a rejected code) goes back to the
user's terminal. Secrets never leave this process.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from sshjumper_cli import ui
from sshjumper_cli.config import Hop
from sshjumper_cli.extensions.base import BaseExtension, ExtensionContext
from sshjumper_cli.totp import TotpSpec, parse_totp

ASKPASS_SCRIPT = Path(__file__).resolve().parents[2] / "askpass.py"
PROMPT_TARGET_RE = re.compile(r"^\s*\(([^)]*)\)\s*(.*)$", re.S)
TOTP_PROMPT_RE = re.compile(
    r"verification|one[- ]time|\botp\b|token|authenticator|\bcode\b", re.I
)
MIN_REMAINING_SECONDS = 3  # never send a code this close to expiring


def _openssh_supports_force() -> bool:
    """SSH_ASKPASS_REQUIRE needs OpenSSH 8.4+."""
    try:
        out = subprocess.run(["ssh", "-V"], capture_output=True, text=True).stderr
    except OSError:
        return False
    match = re.search(r"OpenSSH_(\d+)\.(\d+)", out)
    return bool(match) and (int(match.group(1)), int(match.group(2))) >= (8, 4)


def _keepass_totp(title: str, ctx: ExtensionContext) -> str:
    from sshjumper_cli.extensions.builtin.keepass import _KP_CACHE, KeepassExtension

    try:
        from pykeepass import PyKeePass
    except ImportError as exc:
        raise ValueError("pykeepass is not installed") from exc

    keepass = KeepassExtension()
    db_path = keepass._database_path()
    if db_path is None or not db_path.is_file():
        raise ValueError("KeePass database not found")
    master = ctx.extras.get("keepass_master") or keepass._unlock_password()
    if not master:
        raise ValueError("KeePass is locked")
    ctx.extras["keepass_master"] = master

    cache_key = f"{db_path.resolve()}:{master}"
    kp = _KP_CACHE.get(cache_key)
    if kp is None:
        kp = PyKeePass(str(db_path), password=master)
        _KP_CACHE[cache_key] = kp

    entry = kp.find_entries(title=title, first=True)
    if entry is None:
        raise ValueError(f"no KeePass entry titled {title!r}")

    props = entry.custom_properties or {}
    if props.get("otp"):  # KeePassXC
        return props["otp"]
    if props.get("TimeOtp-Secret-Base32"):  # KeePass 2.47+
        uri = f"otpauth://totp/x?secret={props['TimeOtp-Secret-Base32']}"
        if props.get("TimeOtp-Length"):
            uri += f"&digits={props['TimeOtp-Length']}"
        if props.get("TimeOtp-Period"):
            uri += f"&period={props['TimeOtp-Period']}"
        algorithm = props.get("TimeOtp-Algorithm", "")
        if algorithm:
            uri += "&algorithm=" + algorithm.replace("HMAC-", "").replace("-", "")
        return uri
    if props.get("TOTP Seed"):  # legacy KeePassXC
        settings = (props.get("TOTP Settings") or "30;6").split(";")
        return f"otpauth://totp/x?secret={props['TOTP Seed']}&period={settings[0]}&digits={settings[1]}"
    raise ValueError(f"KeePass entry {title!r} has no TOTP")


def _resolve_secret(source: str, ctx: ExtensionContext) -> TotpSpec:
    if source.startswith("keepass:"):
        return parse_totp(_keepass_totp(source.split(":", 1)[1].strip(), ctx))
    if source == "keepass":
        raise ValueError("use totp: keepass:<entry title>")
    if source.startswith("env:"):
        value = os.environ.get(source[4:].strip())
        if not value:
            raise ValueError(f"environment variable {source[4:]} is not set")
        return parse_totp(value)
    if source.startswith("file:"):
        path = Path(source[5:].strip()).expanduser()
        mode = path.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError(f"{path} must not be readable by others (chmod 600)")
        return parse_totp(path.read_text().strip())
    return parse_totp(source)


class _TotpBroker:
    """Hands out codes to the askpass helper; owns all secrets."""

    def __init__(self, hops: list[tuple[Hop, TotpSpec]]):
        self.hops = hops
        self.token = secrets.token_hex(32)
        self.lock = threading.Lock()
        self.answered: set[int] = set()  # hop numbers already sent a code
        self.last_counter: dict[bytes, int] = {}  # per secret: no code reuse

    def _find_hop(self, prompt: str) -> tuple[Hop, TotpSpec] | None:
        match = PROMPT_TARGET_RE.match(prompt)
        if match:
            target = match.group(1)
            user, _, host = target.rpartition("@")
            for hop, spec in self.hops:
                if hop.host == host and (not user or not hop.user or hop.user == user):
                    return hop, spec
            return None
        # No "(user@host)" prefix: only safe when exactly one hop uses TOTP
        return self.hops[0] if len(self.hops) == 1 else None

    def answer(self, prompt: str) -> str | None:
        if not TOTP_PROMPT_RE.search(prompt):
            return None
        found = self._find_hop(prompt)
        if found is None:
            return None
        hop, spec = found
        with self.lock:
            if hop.number in self.answered:
                # Asked again for the same hop: the code was rejected.
                ui.mark(ui.TOTP, "fail", "rejected")
                ui.end_line()
                return None
            if spec.remaining() < MIN_REMAINING_SECONDS:
                time.sleep(spec.remaining() + 0.2)
            counter = spec.counter()
            if self.last_counter.get(spec.secret, -1) >= counter:
                # Same secret already used this window (shared seed across hops)
                time.sleep(spec.remaining() + 0.2)
                counter = spec.counter()
            self.last_counter[spec.secret] = counter
            self.answered.add(hop.number)
            ui.mark(ui.TOTP)
            ui.end_line()
            return spec.code(counter)


def _make_handler(broker: _TotpBroker):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            creds = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _pid, uid, _gid = struct.unpack("3i", creds)
            if uid != os.getuid():
                return
            try:
                request = json.loads(self.rfile.readline(65536) or b"{}")
            except ValueError:
                return
            answer = None
            if hmac.compare_digest(str(request.get("token", "")), broker.token):
                answer = broker.answer(str(request.get("prompt", "")))
            if answer is None:
                ui.end_line()  # the user is about to be prompted on the terminal
            self.wfile.write(json.dumps({"answer": answer}).encode() + b"\n")

    return Handler


class OtpExtension(BaseExtension):
    name = "otp"
    description = "Auto-answer TOTP prompts for hops with totp: (via SSH_ASKPASS)"
    default_enabled = False

    def is_available(self) -> bool:
        return shutil.which("ssh") is not None and ASKPASS_SCRIPT.is_file()

    def pre_connect(self, ctx: ExtensionContext) -> None:
        totp_hops = [hop for hop in ctx.server.hops if hop.totp]
        if ctx.dry_run or not totp_hops:
            return
        if not _openssh_supports_force():
            ui.mark(ui.TOTP, "warn", "OpenSSH < 8.4")
            return

        resolved: list[tuple[Hop, TotpSpec]] = []
        for hop in totp_hops:
            try:
                resolved.append((hop, _resolve_secret(hop.totp or "", ctx)))
            except (OSError, ValueError) as exc:
                ui.mark(ui.TOTP, "warn", "no secret")
        if not resolved:
            return

        broker = _TotpBroker(resolved)
        workdir = Path(tempfile.mkdtemp(prefix="sshj-otp-"))  # mode 0700
        sock_path = workdir / "broker.sock"
        server = socketserver.ThreadingUnixStreamServer(str(sock_path), _make_handler(broker))
        server.daemon_threads = True
        os.chmod(sock_path, 0o600)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        helper = workdir / "askpass"
        helper.write_text(
            "#!/bin/sh\n"
            f"exec {shlex.quote(sys.executable)} -I {shlex.quote(str(ASKPASS_SCRIPT))} \"$@\"\n"
        )
        helper.chmod(0o700)

        ctx.ssh_env.update(
            {
                "SSH_ASKPASS": str(helper),
                "SSH_ASKPASS_REQUIRE": "force",
                "SSHJ_ASKPASS_SOCK": str(sock_path),
                "SSHJ_ASKPASS_TOKEN": broker.token,
            }
        )
        ctx.extras["otp_server"] = server
        ctx.extras["otp_workdir"] = workdir

    def post_connect(self, ctx: ExtensionContext, exit_code: int) -> None:
        ui.end_line()
        server = ctx.extras.pop("otp_server", None)
        if server is not None:
            server.shutdown()
            server.server_close()
        workdir = ctx.extras.pop("otp_workdir", None)
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)
