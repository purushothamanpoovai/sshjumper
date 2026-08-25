"""CLI helpers: sshjumper ext list|enable|disable."""

from __future__ import annotations

import sys

from sshjumper_cli.extensions.registry import (
    extension_status_rows,
    set_extension_enabled,
)
from sshjumper_cli.paths import extensions_state_path


def cmd_ext(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    action = argv[0]
    if action == "list":
        return _cmd_list()
    if action == "enable":
        if len(argv) < 2:
            print("Usage: sshjumper ext enable <name>", file=sys.stderr)
            return 1
        return _cmd_set(argv[1], True)
    if action == "disable":
        if len(argv) < 2:
            print("Usage: sshjumper ext disable <name>", file=sys.stderr)
            return 1
        return _cmd_set(argv[1], False)
    if action == "path":
        print(extensions_state_path())
        return 0

    print(f"Unknown ext command: {action}", file=sys.stderr)
    _print_help()
    return 1


def _print_help() -> None:
    print(
        "sshjumper ext — manage optional extensions\n"
        "\n"
        "Usage:\n"
        "  sshjumper ext list\n"
        "  sshjumper ext enable <name>\n"
        "  sshjumper ext disable <name>\n"
        "  sshjumper ext path\n"
        "\n"
        "State file: ~/.ssh/sshjumper/extensions.yml\n"
    )


def _cmd_list() -> int:
    rows = extension_status_rows()
    if not rows:
        print("No extensions registered.")
        return 0

    name_w = max(len(r[0]) for r in rows)
    print(f"{'NAME'.ljust(name_w)}  STATUS    AVAILABLE  DESCRIPTION")
    for name, enabled, available, description in rows:
        status = "on " if enabled else "off"
        avail = "yes" if available else "no "
        print(f"{name.ljust(name_w)}  {status:8}  {avail:9}  {description}")
    print(f"\nState: {extensions_state_path()}")
    return 0


def _cmd_set(name: str, enabled: bool) -> int:
    try:
        path = set_extension_enabled(name, enabled)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        return 1
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    verb = "enabled" if enabled else "disabled"
    print(f"Extension '{name}' {verb}.")
    print(f"State: {path}")
    return 0
