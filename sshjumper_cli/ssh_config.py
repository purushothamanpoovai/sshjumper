"""Build a minimal temporary OpenSSH config for ProxyJump chains.

Python writes only connection routing (Host, HostName, User, Port,
IdentityFile, ProxyJump). All SSH behaviour (auth, known_hosts, keepalive,
TTY, forwarding) is left to the system ``ssh`` binary and the user's
OpenSSH configuration.
"""

from __future__ import annotations

import os
import re
import shlex
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sshjumper_cli.config import Hop, PortForward, ServerConfig


def _sanitize_alias(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)


def hop_alias(server_name: str, hop: Hop) -> str:
    return f"sshj_{_sanitize_alias(server_name)}_hop{hop.number}"


def collect_port_forwards(server: ServerConfig) -> list[tuple[int, PortForward]]:
    """Return ``(target_hop_index, forward)`` pairs.

    Server-level ``port_forward`` targets the final hop; a hop-level
    ``port_forward`` targets that hop. Duplicate local ports are rejected.
    """
    pairs: list[tuple[int, PortForward]] = []
    last = len(server.hops) - 1
    pairs.extend((last, fwd) for fwd in server.port_forwards)
    for index, hop in enumerate(server.hops):
        pairs.extend((index, fwd) for fwd in hop.port_forwards)

    seen: set[int] = set()
    for _, fwd in pairs:
        if fwd.local_port in seen:
            raise ValueError(f"Duplicate port_forward local port {fwd.local_port} for: {server.name}")
        seen.add(fwd.local_port)
    return pairs


def proxyjump_forward_specs(server: ServerConfig) -> list[str]:
    """``-L`` specs for the single ProxyJump ``ssh`` (runs against the final hop).

    Destinations are resolved by the final host: its own ports are
    ``localhost``; an intermediate hop is reached by its configured ``host``.
    """
    last = len(server.hops) - 1
    specs: list[str] = []
    for target, fwd in collect_port_forwards(server):
        if fwd.remote_host:
            dest = fwd.remote_host
        elif target == last:
            dest = "localhost"
        else:
            dest = server.hops[target].host
        specs.append(f"{fwd.local_port}:{dest}:{fwd.remote_port}")
    return specs


def nested_forward_specs(server: ServerConfig, hop_index: int) -> list[str]:
    """``-L`` specs for the ``ssh`` that connects to ``hop_index`` in a nested chain.

    Hops before the target relay on the same port (``L:localhost:L``); the
    target hop's ``ssh`` delivers to the real destination.
    """
    specs: list[str] = []
    for target, fwd in collect_port_forwards(server):
        if hop_index < target:
            specs.append(f"{fwd.local_port}:localhost:{fwd.local_port}")
        elif hop_index == target:
            dest = fwd.remote_host or "localhost"
            specs.append(f"{fwd.local_port}:{dest}:{fwd.remote_port}")
    return specs


def _forward_args(specs: list[str]) -> list[str]:
    args: list[str] = []
    for spec in specs:
        args.extend(["-L", spec])
    return args


def ssh_cli_options(
    server: ServerConfig,
    *,
    terminal: bool,
    no_tty: bool = False,
    quiet: bool = False,
    verbose: bool = False,
    x11: bool = False,
) -> list[str]:
    """Shared OpenSSH CLI flags for connect and info output."""
    opts: list[str] = []
    if terminal and not no_tty:
        opts.append("-t")
    if x11:
        opts.append("-X")
    if quiet:
        opts.extend(["-o", "LogLevel=QUIET"])
    if verbose:
        opts.append("-vvv")
    if server.keep_alive:
        opts.extend(["-o", "ServerAliveInterval=120", "-o", "ServerAliveCountMax=3"])
    return opts


def _hop_endpoint(hop: Hop) -> str:
    user = f"{hop.user}@" if hop.user else ""
    return f"{user}{hop.host}"


def _hop_identity(hop: Hop) -> str | None:
    if hop.resolved_key:
        return str(hop.resolved_key)
    if hop.key:
        return str(hop.key)
    return None


def _shell_quote_argv(argv: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in argv)


def build_nested_ssh_chain(
    server: ServerConfig,
    *,
    remote_command: str | None = None,
    terminal: bool = True,
    no_tty: bool = False,
    quiet: bool = False,
    verbose: bool = False,
    x11: bool = False,
    port_forward: bool = False,
) -> str:
    """Build a nested ``ssh`` chain that can be pasted into a shell.

    Example::

        ssh -t user1@host1 ssh user2@host2 'sudo su -'
    """
    nested: str | None = None
    force_tty = remote_command is not None

    for index in range(len(server.hops) - 1, -1, -1):
        hop = server.hops[index]
        argv: list[str] = ["ssh"]
        if index == 0:
            argv.extend(
                ssh_cli_options(
                    server,
                    terminal=terminal,
                    no_tty=no_tty,
                    quiet=quiet,
                    verbose=verbose,
                    x11=x11,
                )
            )
        elif force_tty and not no_tty:
            argv.append("-t")
        if port_forward:
            argv.extend(_forward_args(nested_forward_specs(server, index)))
        identity = _hop_identity(hop)
        if identity:
            argv.extend(["-i", identity])
        if hop.port and hop.port != 22:
            argv.extend(["-p", str(hop.port)])
        argv.append(_hop_endpoint(hop))
        if nested is not None:
            argv.append(nested)
        elif remote_command is not None and index == len(server.hops) - 1:
            argv.append(remote_command)

        if index == 0:
            return _shell_quote_argv(argv)
        nested = _shell_quote_argv(argv)

    raise ValueError(f"No hops configured for: {server.name}")


def build_proxyjump_stdin_command(
    generated: GeneratedSSHConfig,
    server: ServerConfig,
    *,
    remote_command: str | None = None,
    terminal: bool = True,
    no_tty: bool = False,
    quiet: bool = False,
    verbose: bool = False,
    x11: bool = False,
    port_forward: bool = False,
) -> str:
    """ProxyJump command using ``ssh -F /dev/stdin`` (no temp file needed)."""
    argv = ["ssh", "-F", "/dev/stdin"]
    argv.extend(
        ssh_cli_options(
            server,
            terminal=terminal,
            no_tty=no_tty,
            quiet=quiet,
            verbose=verbose,
            x11=x11,
        )
    )
    if port_forward:
        argv.extend(_forward_args(proxyjump_forward_specs(server)))
    argv.append(generated.final_alias)
    if remote_command is not None:
        argv.append(remote_command)
    cmd_line = _shell_quote_argv(argv)
    return f"{cmd_line} <<'EOF'\n{generated.content}EOF"


@dataclass
class GeneratedSSHConfig:
    path: Path
    final_alias: str
    content: str

    def cleanup(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def _hop_block(alias: str, hop: Hop, proxy_jump: str | None) -> list[str]:
    lines = [f"Host {alias}", f"    HostName {hop.host}"]
    if hop.user:
        lines.append(f"    User {hop.user}")
    if hop.port:
        lines.append(f"    Port {hop.port}")
    if hop.resolved_key:
        lines.append(f"    IdentityFile {hop.resolved_key}")
    if proxy_jump:
        lines.append(f"    ProxyJump {proxy_jump}")
    return lines


def generate_ssh_config(server: ServerConfig) -> GeneratedSSHConfig:
    blocks: list[str] = []
    aliases: list[str] = []

    for index, hop in enumerate(server.hops):
        alias = hop_alias(server.name, hop)
        aliases.append(alias)
        proxy = aliases[index - 1] if index > 0 else None
        blocks.extend(_hop_block(alias, hop, proxy))
        blocks.append("")

    content = "\n".join(blocks).rstrip() + "\n"
    final_alias = aliases[-1]

    fd, raw_path = tempfile.mkstemp(prefix="sshjumper_", suffix=".conf")
    os.close(fd)
    path = Path(raw_path)
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    return GeneratedSSHConfig(path=path, final_alias=final_alias, content=content)
