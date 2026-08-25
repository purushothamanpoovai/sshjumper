"""Builtin extension package."""

from __future__ import annotations

from sshjumper_cli.extensions.base import BaseExtension
from sshjumper_cli.extensions.builtin.clipboard import ClipboardExtension
from sshjumper_cli.extensions.builtin.gui import GuiExtension
from sshjumper_cli.extensions.builtin.keepass import KeepassExtension
from sshjumper_cli.extensions.builtin.otp import OtpExtension
from sshjumper_cli.extensions.builtin.passwords import PasswordsExtension
from sshjumper_cli.extensions.builtin.terminal_title import TerminalTitleExtension


def builtin_extensions() -> list[BaseExtension]:
    """Ordered list of shipped extensions (stable names for enable/disable)."""
    return [
        GuiExtension(),
        PasswordsExtension(),
        KeepassExtension(),   # resolve secret before clipboard
        ClipboardExtension(),
        OtpExtension(),
        TerminalTitleExtension(),
    ]
