"""Invoke the system OpenSSH client — no SSH protocol handling in Python."""

from __future__ import annotations

import atexit
import subprocess
import sys
from dataclasses import dataclass

from sshjumper_cli.config import Hop, ServerConfig
from sshjumper_cli.extensions import run_post_connect, run_pre_connect
from sshjumper_cli.ssh_config import (
    GeneratedSSHConfig,
    build_nested_ssh_chain,
    build_proxyjump_stdin_command,
    collect_port_forwards,
    generate_ssh_config,
    proxyjump_forward_specs,
    ssh_cli_options,
)

GREEN = "\033[1;32m"
MAGENTA = "\033[1;35m"
YELLOW = "\033[1;33m"
CYAN = "\033[36m"
BLUE = "\033[1;34m"
RESET = "\033[0m"


@dataclass
class RunOptions:
    info: bool = False
    info_detail: bool = False
    quiet: bool = False
    verbose: bool = False
    x11: bool = False
    no_tty: bool = False
    remote_command: str | None = None
    port_forward: bool = False


def _merge_options(server: ServerConfig, options: RunOptions) -> RunOptions:
    return RunOptions(
        info=options.info,
        info_detail=options.info_detail,
        quiet=options.quiet or server.quiet,
        verbose=options.verbose or server.verbose,
        x11=options.x11 or server.x11,
        no_tty=options.no_tty,
        remote_command=options.remote_command or server.remotecommand,
        port_forward=options.port_forward,
    )


def build_ssh_command(
    server: ServerConfig,
    generated: GeneratedSSHConfig,
    options: RunOptions,
    terminal: bool,
) -> list[str]:
    """Assemble argv for the system ``ssh`` binary. OpenSSH handles the session."""
    cmd = ["ssh", "-F", str(generated.path)]
    cmd.extend(
        ssh_cli_options(
            server,
            terminal=terminal,
            no_tty=options.no_tty,
            quiet=options.quiet,
            verbose=options.verbose,
            x11=options.x11,
        )
    )
    if options.port_forward:
        for spec in proxyjump_forward_specs(server):
            cmd.extend(["-L", spec])
    cmd.append(generated.final_alias)

    if options.remote_command:
        cmd.append(options.remote_command)

    return cmd


def _info_connection_kwargs(
    server: ServerConfig,
    options: RunOptions,
    terminal: bool,
) -> dict[str, object]:
    return {
        "remote_command": options.remote_command,
        "terminal": terminal,
        "no_tty": options.no_tty,
        "quiet": options.quiet,
        "verbose": options.verbose,
        "x11": options.x11,
        "port_forward": options.port_forward,
    }


def invoke_ssh(cmd: list[str]) -> int:
    """Run ``ssh`` as a subprocess and return its exit code. No shell."""
    try:
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        print("\nConnection interrupted.", file=sys.stderr)
        return 130


def _print_title(server: ServerConfig) -> None:
    title = server.description or server.name
    print(f"{GREEN}{title}{RESET}", flush=True)


def _print_route(server: ServerConfig, options: RunOptions) -> None:
    if options.info or options.info_detail:
        return

    print(f"{MAGENTA}Going to{YELLOW}", end="")
    for hop in server.hops:
        port_text = f" {CYAN}{hop.port}{RESET}" if hop.port else ""
        print(f" {hop.user + '@' if hop.user else ''}{hop.host}{port_text}{YELLOW} ->", end="")
    remote = options.remote_command or ""
    print(f"\b\b\b {BLUE}${remote}{RESET}", flush=True)
    if options.port_forward:
        _print_forwards(server)


# Common service names, shown next to forwarded ports for readability.
WELL_KNOWN_PORTS = {
    22: "SSH",
    80: "HTTP",
    443: "HTTPS",
    1433: "MSSQL",
    1521: "Oracle",
    3306: "MySQL",
    5432: "PostgreSQL",
    5672: "RabbitMQ",
    6379: "Redis",
    8080: "HTTP",
    9200: "Elasticsearch",
    11211: "Memcached",
    27017: "MongoDB",
}

# Ready-to-run client hint per service (local port is appended).
CLIENT_HINTS = {
    3306: "mysql -h 127.0.0.1 -P {port} -u <user> -p",
    5432: "psql -h 127.0.0.1 -p {port} -U <user>",
    6379: "redis-cli -h 127.0.0.1 -p {port}",
    27017: "mongosh --host 127.0.0.1 --port {port}",
    22: "ssh -p {port} <user>@127.0.0.1",
    80: "http://127.0.0.1:{port}",
    443: "https://127.0.0.1:{port}",
    8080: "http://127.0.0.1:{port}",
}


def _service_label(port: int) -> str:
    name = WELL_KNOWN_PORTS.get(port)
    return f" {BLUE}{name}{RESET}" if name else ""


def _forward_destination(server: ServerConfig, target: int, fwd) -> str:
    return fwd.remote_host or server.hops[target].host


def _print_forwards(server: ServerConfig) -> None:
    """Compact one-line-per-forward summary (shown when connecting with -P)."""
    for target, fwd in collect_port_forwards(server):
        dest = _forward_destination(server, target, fwd)
        print(
            f"{MAGENTA}Tunnel{RESET} localhost:{CYAN}{fwd.local_port}{RESET}"
            f" {YELLOW}==>{RESET} {dest}:{CYAN}{fwd.remote_port}{RESET}"
            f"{_service_label(fwd.remote_port)}",
            flush=True,
        )


def _print_forward_flow(server: ServerConfig, target: int, fwd, index: int) -> None:
    """Visual path of one forward: you -> each hop -> destination port."""
    dest = _forward_destination(server, target, fwd)
    service = WELL_KNOWN_PORTS.get(fwd.remote_port)
    title = f"{service} on {dest}" if service else dest
    print(
        f"  [{index}] localhost:{CYAN}{fwd.local_port}{RESET}"
        f"  {YELLOW}==>{RESET}  {title}:{CYAN}{fwd.remote_port}{RESET}"
    )
    print(f"      {GREEN}you{RESET}  (listening on 127.0.0.1:{fwd.local_port})")

    indent = "      "
    last = len(server.hops) - 1
    for i, hop in enumerate(server.hops):
        role = "jump" if i < last else "server"
        port_note = ""
        if fwd.remote_host is None and i == target:
            port_note = f"   port {CYAN}{fwd.remote_port}{RESET}{_service_label(fwd.remote_port)}  <- destination"
        print(f"{indent}  +--> hop{hop.number}  {_format_hop_endpoint(hop)}  ({role}){port_note}")
        indent += "     "
        if port_note:
            break  # destination reached; later hops are not part of this path
    if fwd.remote_host is not None:
        print(
            f"{indent}  +--> {fwd.remote_host}  port {CYAN}{fwd.remote_port}{RESET}"
            f"{_service_label(fwd.remote_port)}  <- destination"
        )

    hint = CLIENT_HINTS.get(fwd.remote_port, "connect to 127.0.0.1:{port}")
    print(f"      Use: {hint.format(port=fwd.local_port)}")


def _format_hop_endpoint(hop: Hop) -> str:
    user = f"{hop.user}@" if hop.user else ""
    if hop.port and hop.port != 22:
        return f"{user}{hop.host}:{hop.port}"
    return f"{user}{hop.host}"


def _format_hop_detail(hop: Hop) -> str:
    details = [_format_hop_endpoint(hop)]
    if hop.port and hop.port != 22:
        details.append(f"port={hop.port}")
    key = hop.resolved_key or hop.key
    if key:
        details.append(f"key={key}")
    return "  ".join(details)


def _format_route(server: ServerConfig) -> str:
    return " -> ".join(_format_hop_endpoint(hop) for hop in server.hops)


def _print_info_simple(server: ServerConfig) -> None:
    print("Hop path:")
    print("  local", end="")
    for index, hop in enumerate(server.hops, start=1):
        print(f"\n    -> hop{index}: {_format_hop_detail(hop)}", end="")
    print()


def _print_forward_info(server: ServerConfig, options: RunOptions) -> None:
    pairs = collect_port_forwards(server)
    if not pairs:
        return
    print()
    if options.port_forward:
        status = f"{GREEN}ON{RESET}"
    else:
        status = f"{YELLOW}OFF{RESET} (add -P / --port-forward to enable)"
    print(f"Port forwards: {status}")
    for index, (target, fwd) in enumerate(pairs, start=1):
        _print_forward_flow(server, target, fwd, index)
    print("      Tunnel stays open while the SSH session is open.")


def _print_copy_paste_commands(
    server: ServerConfig,
    generated: GeneratedSSHConfig,
    options: RunOptions,
    terminal: bool,
) -> None:
    kwargs = _info_connection_kwargs(server, options, terminal)
    chain = build_nested_ssh_chain(server, **kwargs)
    proxy = build_proxyjump_stdin_command(generated, server, **kwargs)

    print()
    print("SSH chain (copy/paste):")
    print(chain)
    print()
    print("ProxyJump (copy/paste):")
    print(proxy)


def _print_info_detail(
    server: ServerConfig,
    generated: GeneratedSSHConfig,
    options: RunOptions,
    terminal: bool,
) -> None:
    meta = [server.name]
    if server.project != "Generic" or server.environment != "Generic":
        meta.append(f"{server.project} / {server.environment}")
    print(f"{' · '.join(meta)}")
    print(f"Route: {_format_route(server)}")
    if options.remote_command:
        print(f"Remote: {options.remote_command}")
    if server.localcommand:
        print(f"Local: {server.localcommand}")
    _print_forward_info(server, options)
    _print_copy_paste_commands(server, generated, options, terminal)


def _register_cleanup(generated: GeneratedSSHConfig):
    def _cleanup() -> None:
        generated.cleanup()

    atexit.register(_cleanup)
    return _cleanup


def run_connection(server: ServerConfig, options: RunOptions) -> int:
    options = _merge_options(server, options)
    terminal = server.terminal and not options.no_tty
    generated = generate_ssh_config(server)
    cmd = build_ssh_command(server, generated, options, terminal)

    dry_run = options.info or options.info_detail
    # Title → extensions (KeePass/clipboard prompts) → route → SSH
    # so a password prompt never looks like a hung SSH session.
    _print_title(server)
    ext_ctx = run_pre_connect(server, dry_run=dry_run)
    _print_route(server, options)

    if options.info_detail:
        _print_info_detail(server, generated, options, terminal)
        generated.cleanup()
        run_post_connect(ext_ctx, 0)
        return 0

    if options.info:
        _print_info_simple(server)
        _print_forward_info(server, options)
        _print_copy_paste_commands(server, generated, options, terminal)
        generated.cleanup()
        run_post_connect(ext_ctx, 0)
        return 0

    if server.localcommand:
        subprocess.run(server.localcommand, shell=True, check=False)

    cleanup = _register_cleanup(generated)
    exit_code = 1
    try:
        exit_code = invoke_ssh(cmd)
    finally:
        cleanup()
        run_post_connect(ext_ctx, exit_code)

    if exit_code not in (0, 130) and not options.quiet:
        print(
            f"SSH exited with code {exit_code} for {server.name}",
            file=sys.stderr,
        )

    return exit_code
