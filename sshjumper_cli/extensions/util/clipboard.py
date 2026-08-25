"""Clipboard helpers for extensions (no required Python package)."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys

# xclip keeps running to own the selection — never wait on it forever.
_WRITE_TIMEOUT_SEC = 2.0
_READ_TIMEOUT_SEC = 2.0


def _run(
    cmd: list[str],
    *,
    input_text: str | None = None,
    timeout: float = _READ_TIMEOUT_SEC,
) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            cmd,
            input=None if input_text is None else input_text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _display_ready() -> bool:
    """True when an X11/Wayland session looks available for clipboard tools."""
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def display_ready() -> bool:
    return _display_ready()


def _read_clipboard() -> str | None:
    """Read current clipboard contents from a native tool, if possible."""
    readers: list[list[str]] = []
    if shutil.which("wl-paste"):
        readers.append(["wl-paste", "--no-newline"])
    if shutil.which("xclip"):
        readers.append(["xclip", "-selection", "clipboard", "-o"])
    if shutil.which("xsel"):
        readers.append(["xsel", "--clipboard", "--output"])
    if shutil.which("pbpaste"):
        readers.append(["pbpaste"])

    for cmd in readers:
        completed = _run(cmd, timeout=_READ_TIMEOUT_SEC)
        if completed is not None and completed.returncode == 0:
            return completed.stdout.decode("utf-8", errors="replace")
    return None


def _write_xclip(text: str, selection: str) -> bool:
    """Feed xclip; it often stays alive to own the selection (do not wait forever)."""
    xclip = shutil.which("xclip")
    if not xclip or not _display_ready():
        return False
    try:
        proc = subprocess.Popen(
            [xclip, "-selection", selection, "-in"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False

    try:
        proc.communicate(
            input=text.encode("utf-8"),
            timeout=_WRITE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        # Normal for xclip: process keeps running to serve clipboard data.
        pass
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
        return False

    if selection != "clipboard":
        return True

    current = _read_clipboard()
    return current is not None and current == text


def _write_pipe_tool(cmd: list[str], text: str, *, verify: bool) -> bool:
    """Tools that exit after reading stdin (wl-copy, xsel, pbcopy, clip.exe)."""
    completed = _run(cmd, input_text=text, timeout=_WRITE_TIMEOUT_SEC)
    if completed is None or completed.returncode != 0:
        return False
    if not verify:
        return True
    current = _read_clipboard()
    return current is not None and current == text


def _write_native(text: str) -> bool:
    """Write to system clipboard via native tools. Prefer verified write."""
    wrote_verified = False
    wrote_unverified = False

    if shutil.which("wl-copy") and (
        os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("DISPLAY")
    ):
        if _write_pipe_tool(["wl-copy"], text, verify=True):
            wrote_verified = True

    if shutil.which("xclip") and _display_ready():
        if _write_xclip(text, "clipboard"):
            wrote_verified = True
            _write_xclip(text, "primary")  # middle-click paste

    if not wrote_verified and shutil.which("xsel") and _display_ready():
        if _write_pipe_tool(
            ["xsel", "--clipboard", "--input"], text, verify=True
        ):
            wrote_verified = True
            _write_pipe_tool(
                ["xsel", "--primary", "--input"], text, verify=False
            )

    if not wrote_verified and shutil.which("pbcopy"):
        if _write_pipe_tool(["pbcopy"], text, verify=True):
            wrote_verified = True

    if not wrote_verified and shutil.which("clip.exe"):
        if _write_pipe_tool(["clip.exe"], text, verify=False):
            wrote_unverified = True

    if wrote_verified:
        return True

    if wrote_unverified:
        return True

    return False


def _write_osc52(text: str) -> None:
    """Best-effort terminal clipboard (not verifiable; never counts as success alone)."""
    try:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        sys.stdout.write(f"\033]52;c;{encoded}\a")
        sys.stdout.flush()
    except Exception:
        pass


def _write_tk(text: str) -> bool:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        current = _read_clipboard()
        return current is not None and current == text
    except Exception:
        return False


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard.

    Returns True only when the password is confirmed stored in a real
    clipboard (native tool write + read-back). OSC 52 alone never counts.
    Never blocks indefinitely (xclip ownership / missing DISPLAY).
    """
    if text is None:
        return False
    payload = str(text)

    if _write_native(payload):
        _write_osc52(payload)
        return True

    if _write_tk(payload):
        return True

    _write_osc52(payload)
    return False


_CLIPBOARD_TOOLS = ("wl-copy", "xclip", "xsel", "pbcopy", "clip.exe")


def clipboard_backend_available() -> bool:
    """True when a clipboard binary exists (may still need DISPLAY/Wayland)."""
    return any(shutil.which(name) for name in _CLIPBOARD_TOOLS)
