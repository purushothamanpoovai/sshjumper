"""--copy-pass / --copy-otp: put a server's credential on the clipboard without connecting."""

from __future__ import annotations

import os
import time

from sshjumper_cli import ui
from sshjumper_cli.config import ServerConfig
from sshjumper_cli.extensions.base import ExtensionContext
from sshjumper_cli.extensions.builtin.clipboard import CLEAR_AFTER_SECONDS
from sshjumper_cli.extensions.builtin.keepass import KeepassExtension
from sshjumper_cli.extensions.builtin.otp import _resolve_secret
from sshjumper_cli.extensions.util.clipboard import (
    clear_clipboard_if_unchanged,
    copy_to_clipboard,
)

MIN_OTP_SECONDS = 5  # don't hand out a code the user can't paste in time


def _clear_later(secret: str, seconds: float) -> None:
    """Clear the clipboard in a detached child, since this process exits right away."""
    try:
        pid = os.fork()
    except OSError:
        return
    if pid:
        return
    try:
        os.setsid()
        devnull = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(devnull, fd)
        time.sleep(seconds)
        clear_clipboard_if_unchanged(secret)
    finally:
        os._exit(0)


def _copy(secret: str, icon: str, clear_after: float) -> int:
    if not copy_to_clipboard(secret):
        ui.mark(icon, "fail", "no clipboard")
        return 1
    _clear_later(secret, clear_after)
    ui.mark(icon, "ok", f"copied · {int(clear_after)}s")
    return 0


def copy_password(server: ServerConfig) -> int:
    keepass = KeepassExtension()
    db_path = keepass._database_path()
    if not keepass.is_available() or db_path is None or not db_path.is_file():
        ui.mark(ui.KEEPASS, "fail", "no database")
        return 1
    master = keepass._unlock_password()
    if master is None:
        ui.mark(ui.KEEPASS, "fail", "locked")
        return 1
    queries = keepass._lookup_queries(ExtensionContext(server=server))
    try:
        secret, _matched = keepass._read_entry_password(db_path, queries, master)
    except Exception:
        secret = None
    if not secret:
        ui.mark(ui.KEEPASS, "fail", "not found")
        return 1
    return _copy(secret, ui.KEEPASS, CLEAR_AFTER_SECONDS)


def copy_otp(server: ServerConfig) -> int:
    hop = next((hop for hop in server.hops if hop.totp), None)
    if hop is None:
        ui.mark(ui.TOTP, "fail", "no totp")
        return 1
    try:
        spec = _resolve_secret(hop.totp or "", ExtensionContext(server=server))
    except (OSError, ValueError):
        ui.mark(ui.TOTP, "fail", "no secret")
        return 1
    if spec.remaining() < MIN_OTP_SECONDS:
        ui.segment("wait", f"waiting {int(spec.remaining()) + 1}s")
        time.sleep(spec.remaining() + 0.2)
    remaining = spec.remaining()
    return _copy(spec.code(spec.counter()), ui.TOTP, remaining)
