"""Invoke the system OpenSSH client — no SSH protocol handling in Python."""

from __future__ import annotations

import atexit
import shlex
import subprocess
import sys
from dataclasses import dataclass

from sshjumper_cli.config import Hop, ServerConfig
from sshjumper_cli.extensions import run_extensions
from sshjumper_cli.ssh_config import GeneratedSSHConfig, generate_ssh_config, hop_alias

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


def _merge_options(server: ServerConfig, options: RunOptions) -> RunOptions:
    return RunOptions(
        info=options.info,
        info_detail=options.info_detail,
        quiet=options.quiet or server.quiet,
        verbose=options.verbose or server.verbose,
        x11=options.x11 or server.x11,
        no_tty=options.no_tty,
        remote_command=options.remote_command or server.remotecommand,
    )


def build_ssh_command(
    server: ServerConfig,
    generated: GeneratedSSHConfig,
    options: RunOptions,
    terminal: bool,
) -> list[str]:
    """Assemble argv for the system ``ssh`` binary. OpenSSH handles the session."""
    cmd = ["ssh", "-F", str(generated.path)]

    if terminal and not options.no_tty:
        cmd.append("-t")
    if options.x11:
        cmd.append("-X")
    if options.quiet:
        cmd.extend(["-o", "LogLevel=QUIET"])
    if options.verbose:
        cmd.append("-vvv")
    if server.keep_alive:
        cmd.extend(["-o", "ServerAliveInterval=120", "-o", "ServerAliveCountMax=3"])

    cmd.append(generated.final_alias)

    if options.remote_command:
        cmd.append(options.remote_command)

    return cmd


def invoke_ssh(cmd: list[str]) -> int:
    """Run ``ssh`` as a subprocess and return its exit code. No shell."""
    try:
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        print("\nConnection interrupted.", file=sys.stderr)
        return 130


def _print_banner(server: ServerConfig, options: RunOptions) -> None:
    title = server.description or server.name
    print(f"{GREEN}{title}{RESET}")

    run_extensions(server)

    if options.info or options.info_detail:
        return

    print(f"{MAGENTA}Going to{YELLOW}", end="")
    for hop in server.hops:
        port_text = f" {CYAN}{hop.port}{RESET}" if hop.port else ""
        print(f" {hop.user + '@' if hop.user else ''}{hop.host}{port_text}{YELLOW} ->", end="")
    remote = options.remote_command or ""
    print(f"\b\b\b {BLUE}${remote}{RESET}")


def _format_hop_endpoint(hop: Hop) -> str:
    user = f"{hop.user}@" if hop.user else ""
    if hop.port and hop.port != 22:
        return f"{user}{hop.host}:{hop.port}"
    return f"{user}{hop.host}"


def _print_ssh_chain(server: ServerConfig, generated: GeneratedSSHConfig) -> None:
    print("SSH connection chain:")
    ip_chain = " -> ".join(hop.host for hop in server.hops)
    print(f"  Route: local -> {ip_chain}")
    print()

    for index, hop in enumerate(server.hops):
        alias = hop_alias(server.name, hop)
        step = index + 1
        print(f"  Hop {step} ({alias})")
        print(f"    Target:    {_format_hop_endpoint(hop)}")
        print(f"    IP:        {hop.host}")
        if hop.port:
            print(f"    Port:      {hop.port}")
        if hop.resolved_key:
            print(f"    Key:       {hop.resolved_key}")
        elif hop.key:
            print(f"    Key:       {hop.key}")
        if index == 0:
            print("    Via:       direct SSH from your machine")
        else:
            previous = hop_alias(server.name, server.hops[index - 1])
            print(f"    Via:       ProxyJump {previous}")
        print()

    print(f"  OpenSSH connects to: {generated.final_alias}")
    print(f"  Final endpoint:      {_format_hop_endpoint(server.final_hop)}")
    print(f"  Final IP:            {server.final_hop.host}")
    print()


def _format_hop_detail(hop: Hop) -> str:
    details = [_format_hop_endpoint(hop)]
    if hop.port and hop.port != 22:
        details.append(f"port={hop.port}")
    key = hop.resolved_key or hop.key
    if key:
        details.append(f"key={key}")
    return "  ".join(details)


def _print_info_simple(server: ServerConfig) -> None:
    print("Hop path:")
    print("  local", end="")
    for index, hop in enumerate(server.hops, start=1):
        print(f"\n    -> hop{index}: {_format_hop_detail(hop)}", end="")
    print()


def _print_info_detail(
    server: ServerConfig,
    generated: GeneratedSSHConfig,
    cmd: list[str],
    options: RunOptions,
) -> None:
    print(f"Server: {server.name}")
    if server.description:
        print(f"Description: {server.description}")
    print(f"Project: {server.project}")
    print(f"Environment: {server.environment}")
    _print_info_simple(server)
    if server.localcommand:
        print(f"Local command: `{server.localcommand}`")
    if options.remote_command:
        print(f"Remote command: `{options.remote_command}`")
    print()
    _print_ssh_chain(server, generated)
    print("Generated SSH config:")
    print(generated.content)
    print("Final SSH command:")
    print(shlex.join(cmd))


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

    _print_banner(server, options)

    if options.info_detail:
        _print_info_detail(server, generated, cmd, options)
        generated.cleanup()
        return 0

    if options.info:
        _print_info_simple(server)
        generated.cleanup()
        return 0

    if server.localcommand:
        subprocess.run(server.localcommand, shell=True, check=False)

    cleanup = _register_cleanup(generated)
    try:
        exit_code = invoke_ssh(cmd)
    finally:
        cleanup()

    if exit_code not in (0, 130) and not options.quiet:
        print(
            f"SSH exited with code {exit_code} for {server.name}",
            file=sys.stderr,
        )

    return exit_code
