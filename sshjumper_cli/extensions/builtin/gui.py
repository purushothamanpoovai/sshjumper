"""Builtin extension: interactive Textual TUI (--gui)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sshjumper_cli.extensions.base import BaseExtension


class GuiExtension(BaseExtension):
    name = "gui"
    description = "Interactive Textual TUI server picker (--gui)"
    default_enabled = True

    def is_available(self) -> bool:
        try:
            import textual  # noqa: F401
        except ImportError:
            return False
        return True

    def launch(self, config_path: Path, options: Any) -> int:
        """Start the interactive picker. Only call when enabled + available."""
        from sshjumper_cli.session import run_tui_session

        return run_tui_session(config_path, options)
