"""Builtin extension: set / restore terminal title around SSH sessions — stub."""

from __future__ import annotations

from sshjumper_cli.extensions.base import BaseExtension, ExtensionContext


class TerminalTitleExtension(BaseExtension):
    name = "terminal_title"
    description = "Set terminal title to server name on connect; restore on disconnect"
    default_enabled = False

    def pre_connect(self, ctx: ExtensionContext) -> None:
        if ctx.dry_run:
            return
        title = ctx.server.description or ctx.server.name
        # OSC 0 ; title ST — widely supported
        print(f"\033]0;sshjumper: {title}\007", end="", flush=True)

    def post_connect(self, ctx: ExtensionContext, exit_code: int) -> None:
        if ctx.dry_run:
            return
        print("\033]0;\007", end="", flush=True)
