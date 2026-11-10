"""Builtin extension: copy secrets to the system clipboard."""

from __future__ import annotations

import threading

from sshjumper_cli import ui
from sshjumper_cli.extensions.base import BaseExtension, ExtensionContext
from sshjumper_cli.extensions.util.clipboard import (
    clear_clipboard_if_unchanged,
    clipboard_backend_available,
    copy_to_clipboard,
)

CLEAR_AFTER_SECONDS = 30


class ClipboardExtension(BaseExtension):
    name = "clipboard"
    description = "Copy KeePass/config secrets to the clipboard (requires xclip or wl-copy)"
    default_enabled = False

    def is_available(self) -> bool:
        return clipboard_backend_available()

    def pre_connect(self, ctx: ExtensionContext) -> None:
        if ctx.dry_run:
            return

        # KeePass extension already copied when both are enabled
        if ctx.extras.get("clipboard_done"):
            self._schedule_clear(ctx, ctx.extras.get("clipboard_secret"))
            return

        secret = self._resolve_secret(ctx)
        if not secret:
            return

        if copy_to_clipboard(secret):
            ctx.extras["clipboard_done"] = True
            self._schedule_clear(ctx, secret)
        # Keep quiet for KeePass-originated secrets (keepass prints status).
        if ctx.extras.get("clipboard_label", "").startswith("keepass:"):
            return
        if ctx.extras.get("clipboard_done"):
            label = ctx.extras.get("clipboard_label") or ctx.server.copy or "password"
            ui.mark(ui.CLIPBOARD)
            return
        if not clipboard_backend_available():
            ui.mark(ui.CLIPBOARD, "warn", "no clipboard")


    def post_connect(self, ctx: ExtensionContext, exit_code: int) -> None:
        timer = ctx.extras.pop("clipboard_timer", None)
        if timer is not None:
            timer.cancel()
            clear_clipboard_if_unchanged(ctx.extras.get("clipboard_copied", ""))

    def _schedule_clear(self, ctx: ExtensionContext, secret: str | None) -> None:
        """Clear the copied secret after a short delay, or when the session ends."""
        if not secret:
            return
        ctx.extras["clipboard_copied"] = secret
        timer = threading.Timer(CLEAR_AFTER_SECONDS, clear_clipboard_if_unchanged, args=(secret,))
        timer.daemon = True
        timer.start()
        ctx.extras["clipboard_timer"] = timer

    def _resolve_secret(self, ctx: ExtensionContext) -> str | None:
        # Preferred: another extension (e.g. keepass) already resolved it
        pending = ctx.extras.get("clipboard_secret")
        if isinstance(pending, str) and pending:
            return pending

        server = ctx.server
        # copy: field names which password key to use, or a literal marker
        if server.copy:
            key = str(server.copy).strip()
            passwords = server.password
            if isinstance(passwords, dict) and key in passwords:
                value = passwords[key]
                return str(value) if value is not None else None
            if isinstance(passwords, str) and key in ("password", "true", "yes", "1"):
                return passwords
            # If copy points at keepass-style name but keepass didn't run, nothing to do
            return None

        if isinstance(server.password, str) and server.password:
            return server.password
        return None
