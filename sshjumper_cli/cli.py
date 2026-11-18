"""Command-line interface."""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

from sshjumper_cli import ui
from sshjumper_cli.config import list_servers
from sshjumper_cli.executor import RunOptions, run_connection
from sshjumper_cli.paths import default_config_path
from sshjumper_cli.validator import validate_server


_TRANSFER_HELP = {
    ("-u/--upload",): (
        "-u needs a local source and a remote destination",
        "SERVER -u LOCAL_SRC REMOTE_DST",
        "web01 -u ./app.tar.gz /tmp/",
    ),
    ("-d/--download",): (
        "-d needs a remote source and a local destination",
        "SERVER -d REMOTE_SRC LOCAL_DST",
        "web01 -d /var/log/app ./logs/",
    ),
}


class _Parser(argparse.ArgumentParser):
    """argparse with friendlier errors for the two-path -u / -d options."""

    def error(self, message: str):  # type: ignore[override]
        for options, (problem, form, example) in _TRANSFER_HELP.items():
            if any(message.startswith(f"argument {option}:") for option in options):
                self.exit(
                    2,
                    f"{self.prog}: error: {problem}\n"
                    f"  usage:   {self.prog} {form}\n"
                    f"  example: {self.prog} {example}\n",
                )
        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    from sshjumper_cli import __version__

    parser = _Parser(
        prog="sshjumper",
        allow_abbrev=False,  # "--i" must not silently mean --info
        description="Multi-hop SSH through jump servers, using the system OpenSSH (ProxyJump).",
        usage="%(prog)s [options] SERVER [options] [COMMAND | -- COMMAND]",
        epilog=(
            "Examples:\n"
            "  %(prog)s web01                        connect\n"
            "  %(prog)s web01 uptime                 run a command on web01\n"
            "  %(prog)s web01 -- ls -la              everything after -- goes to the server\n"
            "  %(prog)s prod_db -p                   connect with the configured tunnels\n"
            "  %(prog)s prod_db -i                   show the connection card (-ii: + commands)\n"
            "  %(prog)s prod_db -k                   copy the password, no login\n"
            "  %(prog)s prod_db -o                   copy the current TOTP code, no login\n"
            "  %(prog)s web01 -u ./app.tar.gz /tmp/  upload (folders are recursive)\n"
            "  %(prog)s web01 -d /var/log/app ./logs download\n"
            "  %(prog)s -l | -g | -e                 list servers / picker / edit config\n"
            "  %(prog)s ext list                     manage extensions\n"
            "\n"
            "Options are read before and right after SERVER; the first other word\n"
            "starts the remote command (web01 -p ls -p runs 'ls -p' with tunnels on)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    connect = parser.add_argument_group("Connection")
    connect.add_argument(
        "-p", "--port-forward", dest="port_forward", action="store_true",
        help="open the tunnels configured in port_forward (ssh -L); off by default",
    )
    connect.add_argument("-X", "--x11", action="store_true", help="enable X11 forwarding")
    connect.add_argument("-T", "--no-tty", dest="no_tty", action="store_true", help="do not allocate a terminal")

    inspect = parser.add_argument_group("Inspect (no login)")
    inspect.add_argument(
        "-i", "--info", action="count", default=0,
        help="show the connection card; twice (-ii) adds the copy/paste ssh commands",
    )
    inspect.add_argument("-l", "--list", action="store_true", help="list the configured servers")
    inspect.add_argument("-g", "--gui", action="store_true", help="pick a server in the interactive terminal UI")

    creds = parser.add_argument_group("Credentials (no login)")
    creds.add_argument(
        "-k", "--copy-password", dest="copy_pass", action="store_true",
        help="copy the server's KeePass password to the clipboard (cleared after 30s)",
    )
    creds.add_argument(
        "-o", "--copy-otp", dest="copy_otp", action="store_true",
        help="copy the current TOTP one-time code to the clipboard (cleared when it expires)",
    )

    transfer = parser.add_argument_group("File transfer (rsync, scp fallback)")
    transfer.add_argument(
        "-u", "--upload", nargs=2, metavar=("LOCAL_SRC", "REMOTE_DST"),
        help="upload a file or folder to the server",
    )
    transfer.add_argument(
        "-d", "--download", nargs=2, metavar=("REMOTE_SRC", "LOCAL_DST"),
        help="download a file or folder from the server",
    )

    config = parser.add_argument_group("Configuration")
    config.add_argument("-c", "--config", dest="config", metavar="FILE", help="use this config file instead of sshjconfig.yml")
    config.add_argument(
        "-e", "--edit", dest="edit_config", action="store_true",
        help="edit the config in $EDITOR (default vim); refuses if already open",
    )

    general = parser.add_argument_group("General")
    general.add_argument("-q", "--quiet", action="store_true", help="less output")
    general.add_argument("-v", "--verbose", action="store_true", help="more output (ssh -vvv)")
    general.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}", help="show the version and exit")
    general.add_argument("-h", "--help", action="help", help="show this help and exit")
    return parser


def resolve_config_path(args: argparse.Namespace) -> Path:
    if args.config:
        return Path(args.config).expanduser()
    return default_config_path()


def parse_remote_command(remote_args: list[str]) -> str | None:
    if not remote_args:
        return None
    return " ".join(remote_args)


def _option_arity(parser: argparse.ArgumentParser) -> dict[str, int]:
    """Map each option string to how many values it takes (0 for flags)."""
    return {
        opt: action.nargs if isinstance(action.nargs, int) else (0 if action.nargs == 0 else 1)
        for opt, action in parser._option_string_actions.items()
    }


def _transfer(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    server_name: str | None,
    remote_args: list[str],
) -> tuple[str, str, str] | None:
    if not args.upload and not args.download:
        return None
    if args.upload and args.download:
        parser.error("use either -u/--upload or -d/--download, not both")
    if not server_name:
        parser.error("-u / -d need a server name")
    if remote_args:
        parser.error("a remote command cannot be combined with -u / -d")
    if args.upload:
        return ("upload", args.upload[0], args.upload[1])
    return ("download", args.download[0], args.download[1])


def split_argv(
    parser: argparse.ArgumentParser, argv: list[str]
) -> tuple[list[str], str | None, list[str]]:
    """Split into (sshjumper options, server name, remote command).

    Options before the server and directly after it belong to sshjumper. The
    first other word after the server starts the remote command, and ``--``
    forces everything after it to the remote command, so
    ``server -P ls -P`` runs ``ls -P`` with sshjumper's ``-P`` on.
    """
    arity = _option_arity(parser)
    own: list[str] = []
    server: str | None = None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            return own, server, argv[index + 1 :]
        if token.startswith("-") and len(token) > 1:
            # Unknown options are left to argparse to reject (a typo must never
            # become a remote command); a command starting with "-" needs "--".
            own.append(token)
            values = arity.get(token, 0)
            own.extend(argv[index + 1 : index + 1 + values])
            index += values
        elif server is None:
            server = token
        else:
            break
        index += 1
    return own, server, argv[index:]


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


def _vim_swap_files(config_path: Path) -> list[Path]:
    """Return existing vim/neovim swap files for config_path."""
    resolved = config_path.resolve()
    found = list(resolved.parent.glob(f".{resolved.name}.sw[a-p]"))

    # Swap files kept in a central directory have the full path encoded with '%'.
    encoded = str(resolved).replace("/", "%")
    swap_dirs = [
        Path.home() / ".vim" / "swap",
        Path.home() / ".local" / "state" / "vim" / "swap",
        Path.home() / ".local" / "state" / "nvim" / "swap",
        Path.home() / ".local" / "share" / "nvim" / "swap",
    ]
    for swap_dir in swap_dirs:
        if swap_dir.is_dir():
            found.extend(swap_dir.glob(f"{glob.escape(encoded)}.sw[a-p]"))
    return found


def cmd_edit_config(config_path: Path) -> int:
    if not config_path.is_file():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 1

    swap_files = _vim_swap_files(config_path)
    if swap_files:
        print(f"{config_path} appears to be open in another editor already.", file=sys.stderr)
        for swap in swap_files:
            print(f"  swap file: {swap}", file=sys.stderr)
        print("Close that session (or remove a stale swap file) and try again.", file=sys.stderr)
        return 1

    editor = _editor_command()
    if editor is None:
        print("No editor found: set $EDITOR (e.g. export EDITOR=vim) or install vim", file=sys.stderr)
        return 1

    rc = subprocess.call([*editor, str(config_path)])
    if rc == 0:
        try:
            from sshjumper_cli.config import load_yaml_config

            load_yaml_config(config_path)
        except Exception as exc:  # show the problem now, not at the next connect
            print(f"Warning: {config_path} has a problem: {exc}", file=sys.stderr)
            return 1
    return rc


def _editor_command() -> list[str] | None:
    """$VISUAL, then $EDITOR (may include arguments, e.g. "code -w"), then vim / vi."""
    import shlex

    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var, "").strip()
        if value:
            try:
                parts = shlex.split(value)
            except ValueError:
                continue
            if parts and shutil.which(parts[0]):
                return parts
    for fallback in ("vim", "vi"):
        if shutil.which(fallback):
            return [fallback]
    return None


def cmd_copy(config_path: Path, server_name: str, otp: bool) -> int:
    try:
        server = validate_server(config_path, server_name)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    from sshjumper_cli.copy_cmd import copy_otp, copy_password
    from sshjumper_cli.executor import _print_title

    _print_title(server)
    try:
        return copy_otp(server) if otp else copy_password(server)
    finally:
        ui.end_line()


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


def _files_are_private(argv: list[str]) -> bool:
    """Stop before anything runs if sshjumper's files are open to other users."""
    from sshjumper_cli.paths import insecure_files

    config = None
    for flag in ("-c", "--config"):
        if flag in argv[:-1]:
            config = Path(argv[argv.index(flag) + 1]).expanduser()
    problems = insecure_files(config)
    if not problems:
        return True
    print("sshjumper: unsafe permissions, refusing to run:", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    print("Fix the permissions above, then run sshjumper again.", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from sshjumper_cli.paths import take_secret_env

    take_secret_env()  # child processes never see the KeePass master password

    if not _files_are_private(argv):
        return 1

    # Extension manager: sshjumper ext list|enable|disable|path
    if argv and argv[0] == "ext":
        from sshjumper_cli.extensions.cli import cmd_ext

        return cmd_ext(argv[1:])

    parser = build_parser()

    if not argv:
        parser.print_help()
        return 0

    own_args, server_name, remote_args = split_argv(parser, argv)
    args = parser.parse_args(own_args)

    config_path = resolve_config_path(args)

    options = RunOptions(
        info=args.info == 1,
        info_detail=args.info >= 2,
        quiet=args.quiet,
        verbose=args.verbose,
        x11=args.x11,
        no_tty=args.no_tty,
        remote_command=parse_remote_command(remote_args),
        transfer=_transfer(parser, args, server_name, remote_args),
        port_forward=args.port_forward,
    )

    if args.edit_config:
        if server_name:
            parser.error("server name cannot be used with -e/--edit")
        return cmd_edit_config(config_path)

    if args.copy_pass or args.copy_otp:
        if args.copy_pass and args.copy_otp:
            parser.error("use either -k/--copy-password or -o/--copy-otp, not both")
        if not server_name:
            parser.error("-k / -o need a server name")
        if remote_args:
            parser.error(
                "-k / -o take no command; for an ssh option (ssh -o Name=value) "
                "use ssh_options in the config"
            )
        return cmd_copy(config_path, server_name, otp=args.copy_otp)

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
