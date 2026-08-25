"""Builtin extension: show password hints from server config / passwords.yml (phase)."""

from __future__ import annotations

from sshjumper_cli.extensions.base import BaseExtension, ExtensionContext


class PasswordsExtension(BaseExtension):
    name = "passwords"
    description = "Show password hints from server config (passwords.yml merge planned)"
    default_enabled = True

    def pre_connect(self, ctx: ExtensionContext) -> None:
        passwords = ctx.server.password
        if not passwords:
            return
        if isinstance(passwords, dict):
            for name, value in passwords.items():
                print(f" {name}: \033[8m\033[48;5;15m{value}\033[0m")
        elif isinstance(passwords, str):
            print(f" password: \033[8m\033[48;5;15m{passwords}\033[0m")
