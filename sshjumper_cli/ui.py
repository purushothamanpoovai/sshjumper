"""Shared terminal styling: one compact status line per connection.

::

    ● Live Gateway Script Server · prod  → 10.30.1.12 › 10.30.1.10  ⚿ ✓  ◷ ✓

Checks are bold symbols, green when done, amber when left to the user, red
when failed; a short reason replaces the ✓/▲/✗ when there is one
(``⚿ not found``). The line stays open while ssh logs in so the TOTP check
lands on it; anything after it closes goes on an indented ``└`` line.
Colour is dropped when stdout is not a terminal or ``NO_COLOR`` is set.
"""

from __future__ import annotations

import os
import sys
import threading

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"

# Check names (used by callers) and their symbols. Text symbols, not emoji.
KEEPASS = "keepass"
CLIPBOARD = "clipboard"
TOTP = "mfa"
TUNNEL = "tunnel"
ICONS = {KEEPASS: "⚿", TOTP: "◷", CLIPBOARD: "⎘", TUNNEL: "⇄", "upload": "⇡", "download": "⇣"}

_MARKS = {"ok": ("✓", GREEN), "warn": ("▲", YELLOW), "fail": ("✗", RED)}

_lock = threading.Lock()  # the TOTP broker writes from another thread
_line_open = False


def _use_color() -> bool:
    if "NO_COLOR" in os.environ:
        return False
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def paint(text: str, *codes: str) -> str:
    if not codes or not _use_color():
        return text
    return "".join(codes) + text + RESET


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _prefix() -> str:
    """Spacing on the open line, or a continuation line once it closed."""
    return "  " if _line_open else "  " + paint("└ ", DIM)


def header(title: str, meta: list[str] | None = None) -> None:
    """Start the status line (left open for checks)."""
    global _line_open
    with _lock:
        if _line_open:
            _write("\n")
        suffix = paint(" · " + " · ".join(meta), DIM) if meta else ""
        _write(f"{paint('●', GREEN, BOLD)} {paint(title, BOLD)}{suffix}")
        _line_open = True


def segment(label: str, text: str) -> None:
    """Dim context on the line: target host, remote command, tunnel ports."""
    global _line_open
    icon = ICONS.get(label)
    with _lock:
        _write(_prefix() + paint(f"{icon} {text}" if icon else text, DIM))
        _line_open = True


def mark(label: str, kind: str = "ok", note: str = "") -> None:
    """Bold ``icon ✓`` / ``icon ✗``, or ``icon <reason>``, in the state colour."""
    global _line_open
    symbol, color = _MARKS[kind]
    icon = ICONS.get(label, label)
    with _lock:
        _write(_prefix() + paint(f"{icon} {note or symbol}", color, BOLD))
        _line_open = True


def end_line() -> None:
    """Close the status line before anything else uses the terminal."""
    global _line_open
    with _lock:
        if _line_open:
            _write("\n")
            _line_open = False
