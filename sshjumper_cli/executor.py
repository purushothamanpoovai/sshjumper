"""Invoke the system OpenSSH client — no SSH protocol handling in Python."""

from __future__ import annotations

import atexit
import subprocess
import sys
from pathlib import Path
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


def _forward_destination(server: ServerConfig, target: int, fwd) -> str:
    return fwd.remote_host or server.hops[target].host


def _print_forwards(server: ServerConfig) -> None:
    """Compact one-line-per-forward summary (shown when connecting with -P)."""
    for target, fwd in collect_port_forwards(server):
        dest = _forward_destination(server, target, fwd)
        print(
            f"{MAGENTA}Tunnel{RESET} localhost:{CYAN}{fwd.local_port}{RESET}"
            f" {YELLOW}━━▶{RESET} {dest}:{CYAN}{fwd.remote_port}{RESET}",
            flush=True,
        )


DIM = "\033[2m"
BOLD = "\033[1m"


def _format_hop_endpoint(hop: Hop) -> str:
    user = f"{hop.user}@" if hop.user else ""
    if hop.port and hop.port != 22:
        return f"{user}{hop.host}:{hop.port}"
    return f"{user}{hop.host}"


def _short_path(value: object) -> str:
    text = str(value)
    home = str(Path.home())
    return "~" + text[len(home):] if text.startswith(home + "/") else text


def _server_tags(server: ServerConfig, options: RunOptions, terminal: bool) -> list[str]:
    tags = [label for label in (server.project, server.environment) if label != "Generic"]
    if server.keep_alive:
        tags.append("keep-alive")
    if not terminal:
        tags.append("no-tty")
    if options.x11:
        tags.append("x11")
    if options.quiet:
        tags.append("quiet")
    if options.verbose:
        tags.append("verbose")
    return tags


def _tunnel_lines(server: ServerConfig, options: RunOptions) -> dict[int, list[str]]:
    """Tunnel detail lines grouped by the hop index they terminate at."""
    lines: dict[int, list[str]] = {}
    state = f"{GREEN}on{RESET}" if options.port_forward else f"{DIM}off{RESET}"
    for target, fwd in collect_port_forwards(server):
        dest = f"{fwd.remote_host}:" if fwd.remote_host else ":"
        lines.setdefault(target, []).append(
            f"tunnel  {CYAN}localhost:{fwd.local_port}{RESET} {YELLOW}━━▶{RESET} "
            f"{dest}{CYAN}{fwd.remote_port}{RESET}  {DIM}[{RESET}{state}{DIM}]{RESET}"
        )
    return lines


def _print_card(server: ServerConfig, options: RunOptions, terminal: bool) -> None:
    """One compact view of everything about a connection (used by -i and -ii)."""
    rail = f"{DIM}│{RESET}"
    tags = _server_tags(server, options, terminal)
    tag_text = f"  {DIM}{' · '.join(tags)}{RESET}" if tags else ""

    print(f"{DIM}╭─{RESET} {GREEN}{server.name}{RESET}{tag_text}")
    if server.description:
        print(f"{rail}  {server.description}")
    print(rail)

    # Local node
    print(f"{rail}  {GREEN}◉{RESET} {BOLD}local{RESET}")
    if server.localcommand:
        print(f"{rail}  ┃   {DIM}└{RESET} run     {server.localcommand}")

    tunnels = _tunnel_lines(server, options)
    last = len(server.hops) - 1
    width = max(len(_format_hop_endpoint(hop)) for hop in server.hops)
    for index, hop in enumerate(server.hops):
        is_last = index == last
        branch = "┗━━▶" if is_last else "┣━━▶"
        stem = "    " if is_last else "┃   "
        role = "target" if is_last else "jump"
        role_color = MAGENTA if is_last else YELLOW
        endpoint = _format_hop_endpoint(hop).ljust(width)
        print(f"{rail}  ┃")
        print(
            f"{rail}  {branch} {DIM}hop{hop.number}{RESET}  {BOLD}{endpoint}{RESET}"
            f"  {role_color}{role}{RESET}"
        )

        details: list[str] = []
        key = hop.resolved_key or hop.key
        if key:
            details.append(f"key     {DIM}{_short_path(key)}{RESET}")
        details.extend(tunnels.get(index, []))
        if is_last and options.remote_command:
            details.append(f"run     {BLUE}${RESET} {options.remote_command}")

        for position, detail in enumerate(details, start=1):
            corner = "└" if position == len(details) else "├"
            print(f"{rail}  {stem}   {DIM}{corner}{RESET} {detail}")

    print(rail)
    if tunnels and not options.port_forward:
        print(f"{DIM}╰─{RESET} tunnels are off · connect with {BOLD}sshjumper -P {server.name}{RESET}")
    else:
        flag = "-P " if tunnels else ""
        print(f"{DIM}╰─{RESET} connect with {BOLD}sshjumper {flag}{server.name}{RESET}")


def _print_copy_paste_commands(
    server: ServerConfig,
    generated: GeneratedSSHConfig,
    options: RunOptions,
    terminal: bool,
) -> None:
    kwargs = _info_connection_kwargs(server, options, terminal)
    chain = build_nested_ssh_chain(server, **kwargs)
    proxy = build_proxyjump_stdin_command(generated, server, **kwargs)

    if collect_port_forwards(server) and not options.port_forward:
        print()
        print(f"{YELLOW}!{RESET} tunnels not included below · add {BOLD}-P{RESET} to include the -L flags")
    print()
    print(f"{DIM}──{RESET} {BOLD}Nested SSH chain{RESET} {DIM}(copy/paste) ─────────────────{RESET}")
    print(chain)
    print()
    print(f"{DIM}──{RESET} {BOLD}ProxyJump{RESET} {DIM}(copy/paste, no temp file) ──────────{RESET}")
    print(proxy)


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
    if not dry_run:
        _print_title(server)
    ext_ctx = run_pre_connect(server, dry_run=dry_run)
    _print_route(server, options)

    if dry_run:
        _print_card(server, options, terminal)
        if options.info_detail:
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
