"""Builtin extension: copy secrets to the system clipboard."""

from __future__ import annotations

from sshjumper_cli.extensions.base import BaseExtension, ExtensionContext
from sshjumper_cli.extensions.util.clipboard import (
    clipboard_backend_available,
    copy_to_clipboard,
)


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
            return

        secret = self._resolve_secret(ctx)
        if not secret:
            return

        if copy_to_clipboard(secret):
            ctx.extras["clipboard_done"] = True
        # Keep quiet for KeePass-originated secrets (keepass prints status).
        if ctx.extras.get("clipboard_label", "").startswith("keepass:"):
            return
        if ctx.extras.get("clipboard_done"):
            label = ctx.extras.get("clipboard_label") or ctx.server.copy or "password"
            print(f"Clipboard: copied '{label}'", flush=True)
            return
        if not clipboard_backend_available():
            print(
                "Clipboard: dependency missing (install xclip or wl-clipboard)",
                flush=True,
            )


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
