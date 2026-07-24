"""Interactive TUI session loop: pick server, SSH, return to picker."""

from __future__ import annotations

import sys
from pathlib import Path

from sshjumper_cli.executor import RunOptions, run_connection
from sshjumper_cli.tui import pick_server
from sshjumper_cli.validator import validate_server


def run_tui_session(config_path: Path, options: RunOptions) -> int:
    while True:
        server_name = pick_server(config_path)
        if not server_name:
            return 0

        try:
            server = validate_server(config_path, server_name)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(exc, file=sys.stderr)
            continue

        exit_code = run_connection(server, options)

        if exit_code == 0:
            print(f"\nDisconnected from {server_name}. Select another server.\n")
        elif exit_code == 130:
            print("\nConnection interrupted. Select another server.\n", file=sys.stderr)
        else:
            print(
                f"\nCould not connect to {server_name} (exit {exit_code}). "
                "Select another server or press q to quit.\n",
                file=sys.stderr,
            )
