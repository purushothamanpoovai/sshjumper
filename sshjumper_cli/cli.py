"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sshjumper_cli.config import list_servers
from sshjumper_cli.executor import RunOptions, run_connection
from sshjumper_cli.paths import default_config_path
from sshjumper_cli.validator import validate_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sshjumper",
        description="Multi-hop SSH jumper using OpenSSH ProxyJump",
        usage="%(prog)s [options] server [-- remote-command]",
        epilog=(
            "Examples:\n"
            "  %(prog)s --gui\n"
            "  %(prog)s -l\n"
            "  %(prog)s bastion\n"
            "  %(prog)s staging_app -i\n"
            "  %(prog)s prod_db -ii\n"
            "  %(prog)s web01 -- uptime\n"
            "  %(prog)s ext list\n"
            "  %(prog)s ext enable otp\n"
            "\n"
            "With no arguments, this help is shown.\n"
            "Open the interactive TUI with --gui.\n"
            "Manage plugins with: %(prog)s ext list|enable|disable."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-c", "--config", dest="config", help="Path to sshjconfig.yml")
    parser.add_argument("-i", "--info", action="store_true", help="Show SSH hop path without connecting")
    parser.add_argument(
        "-ii",
        "--info-detail",
        dest="info_detail",
        action="store_true",
        help="Show hop path, jumper chain, SSH config, and command without connecting",
    )
    parser.add_argument("-l", "--list", action="store_true", help="List available servers")
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open interactive TUI server picker (requires gui extension)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet SSH output")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose SSH output")
    parser.add_argument("-X", "--x11", action="store_true", help="Enable X11 forwarding")
    parser.add_argument("--no-tty", action="store_true", help="Disable terminal allocation")
    return parser


def resolve_config_path(args: argparse.Namespace) -> Path:
    if args.config:
        return Path(args.config).expanduser()
    return default_config_path()


def parse_remote_command(remote_args: list[str]) -> str | None:
    if not remote_args:
        return None
    return " ".join(remote_args)


def parse_server_and_remote(remaining: list[str]) -> tuple[str | None, list[str]]:
    if not remaining:
        return None, []

    server_name = remaining[0]
    tail = remaining[1:]
    if not tail:
        return server_name, []
    if tail[0] == "--":
        return server_name, tail[1:]
    return server_name, tail


def cmd_list(config_path: Path) -> int:
    try:
        servers = list_servers(config_path)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    if not servers:
        print(f"No servers in: {config_path}")
        return 0

    project_width = max(len(server.project) for server in servers)
    env_width = max(len(server.environment) for server in servers)
    name_width = max(len(server.name) for server in servers)

    for server in servers:
        line = (
            f"{server.project.ljust(project_width)}  "
            f"{server.environment.ljust(env_width)}  "
            f"{server.name.ljust(name_width)}"
        )
        if server.description:
            line += f"    {server.description}"
        print(line)
    return 0


def cmd_connect(config_path: Path, server_name: str, options: RunOptions) -> int:
    try:
        server = validate_server(config_path, server_name)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    except KeyError as exc:
        print(exc, file=sys.stderr)
        return 1
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    return run_connection(server, options)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Extension manager: sshjumper ext list|enable|disable|path
    if argv and argv[0] == "ext":
        from sshjumper_cli.extensions.cli import cmd_ext

        return cmd_ext(argv[1:])

    parser = build_parser()

    if not argv:
        parser.print_help()
        return 0

    args, remaining = parser.parse_known_args(argv)

    for token in remaining:
        if token.startswith("-") and token != "--":
            parser.error(f"unrecognized arguments: {token}")

    config_path = resolve_config_path(args)
    server_name, remote_args = parse_server_and_remote(remaining)

    options = RunOptions(
        info=args.info,
        info_detail=args.info_detail,
        quiet=args.quiet,
        verbose=args.verbose,
        x11=args.x11,
        no_tty=args.no_tty,
        remote_command=parse_remote_command(remote_args),
    )

    if args.list:
        return cmd_list(config_path)

    if args.gui:
        if server_name:
            parser.error("server name cannot be used with --gui")
        try:
            from sshjumper_cli.extensions import require_extension

            gui = require_extension("gui")
            return gui.launch(config_path, options)  # type: ignore[attr-defined]
        except (KeyError, RuntimeError) as exc:
            print(exc, file=sys.stderr)
            return 1
        except FileNotFoundError as exc:
            print(exc, file=sys.stderr)
            return 1
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        except ImportError as exc:
            print(f"GUI extension failed to load: {exc}", file=sys.stderr)
            return 1

    if not server_name:
        parser.print_help()
        return 0

    return cmd_connect(config_path, server_name, options)


if __name__ == "__main__":
    raise SystemExit(main())
