"""Extension discovery, enable/disable, and hook runner."""

from __future__ import annotations

from pathlib import Path

from sshjumper_cli.config import ServerConfig
from sshjumper_cli.extensions.base import BaseExtension, ExtensionContext
from sshjumper_cli.extensions.builtin import builtin_extensions
from sshjumper_cli.extensions.state import (
    is_enabled,
    load_extension_state,
    save_extension_state,
)


def all_extensions() -> list[BaseExtension]:
    """Return registered extensions (builtins first; user plugins later)."""
    return list(builtin_extensions())


def get_extension(name: str) -> BaseExtension | None:
    for ext in all_extensions():
        if ext.name == name:
            return ext
    return None


def enabled_extensions(state: dict[str, bool] | None = None) -> list[BaseExtension]:
    current = state if state is not None else load_extension_state()
    active: list[BaseExtension] = []
    for ext in all_extensions():
        if is_enabled(ext.name, ext.default_enabled, current):
            active.append(ext)
    return active


def extension_status_rows() -> list[tuple[str, bool, bool, str]]:
    """Rows: (name, enabled, available, description)."""
    state = load_extension_state()
    rows: list[tuple[str, bool, bool, str]] = []
    for ext in all_extensions():
        rows.append(
            (
                ext.name,
                is_enabled(ext.name, ext.default_enabled, state),
                ext.is_available(),
                ext.description,
            )
        )
    return rows


def require_extension(name: str) -> BaseExtension:
    """Return extension if enabled and available; raise KeyError/RuntimeError otherwise."""
    ext = get_extension(name)
    if ext is None:
        known = ", ".join(e.name for e in all_extensions()) or "(none)"
        raise KeyError(f"Unknown extension '{name}'. Known: {known}")

    if not is_enabled(ext.name, ext.default_enabled):
        raise RuntimeError(
            f"Extension '{name}' is disabled. Enable with: sshjumper ext enable {name}"
        )
    if not ext.is_available():
        raise RuntimeError(
            f"Extension '{name}' is not available (missing dependency)."
        )
    return ext


def set_extension_enabled(name: str, enabled: bool) -> Path:
    ext = get_extension(name)
    if ext is None:
        known = ", ".join(e.name for e in all_extensions()) or "(none)"
        raise KeyError(f"Unknown extension '{name}'. Known: {known}")

    state = load_extension_state()
    for item in all_extensions():
        state.setdefault(item.name, item.default_enabled)
    state[name] = enabled
    return save_extension_state(state)


def run_pre_connect(
    server: ServerConfig,
    *,
    config_path: Path | None = None,
    dry_run: bool = False,
) -> ExtensionContext:
    ctx = ExtensionContext(server=server, config_path=config_path, dry_run=dry_run)
    for ext in enabled_extensions():
        try:
            ext.pre_connect(ctx)
        except Exception:
            # Never dump stack / exception text to end users
            print(f"{ext.name}: failed", flush=True)
    return ctx


def run_post_connect(ctx: ExtensionContext, exit_code: int) -> None:
    for ext in enabled_extensions():
        try:
            ext.post_connect(ctx, exit_code)
        except Exception:
            print(f"{ext.name}: failed", flush=True)
