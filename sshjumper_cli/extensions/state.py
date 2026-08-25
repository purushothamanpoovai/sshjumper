"""Persist which extensions are enabled (ON/OFF) and optional per-extension config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sshjumper_cli.paths import extensions_state_path


def _ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_raw(path: Path | None = None) -> dict[str, Any]:
    state_path = path or extensions_state_path()
    if not state_path.exists():
        return {}
    with state_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid extensions state in: {state_path}")
    return data


def load_extension_state(path: Path | None = None) -> dict[str, bool]:
    """Load enabled map from extensions.yml. Missing file → empty (use defaults)."""
    data = _load_raw(path)
    enabled = data.get("enabled", data if "config" not in data else {})
    if not isinstance(enabled, dict):
        raise ValueError("'enabled' must be a mapping in extensions.yml")

    result: dict[str, bool] = {}
    for name, value in enabled.items():
        if name in ("enabled", "config"):
            continue
        if isinstance(value, bool):
            result[str(name)] = value
        elif value in (0, 1, "0", "1", "true", "false", "yes", "no", "on", "off"):
            result[str(name)] = str(value).lower() in ("1", "true", "yes", "on")
        else:
            # Ignore nested maps under a mistaken flat layout
            if isinstance(value, dict):
                continue
            raise ValueError(f"Invalid enabled value for extension '{name}': {value}")
    return result


def load_extension_config(name: str | None = None, path: Path | None = None) -> dict[str, Any]:
    """Load optional ``config:`` section (or one extension's config block)."""
    data = _load_raw(path)
    config = data.get("config") or {}
    if not isinstance(config, dict):
        return {}
    if name is None:
        return dict(config)
    block = config.get(name) or {}
    return dict(block) if isinstance(block, dict) else {}


def save_extension_state(state: dict[str, bool], path: Path | None = None) -> Path:
    """Write enabled map while preserving any existing ``config:`` section."""
    state_path = path or extensions_state_path()
    _ensure_parent(state_path)
    existing = _load_raw(state_path)
    payload: dict[str, Any] = {
        "enabled": {name: bool(value) for name, value in sorted(state.items())},
    }
    if isinstance(existing.get("config"), dict) and existing["config"]:
        payload["config"] = existing["config"]

    with state_path.open("w", encoding="utf-8") as handle:
        handle.write("# SSHJumper extension toggles + optional config\n")
        handle.write("# Managed by: sshjumper ext list|enable|disable\n")
        yaml.safe_dump(payload, handle, default_flow_style=False, sort_keys=False)
    return state_path


def is_enabled(name: str, default: bool, state: dict[str, bool] | None = None) -> bool:
    current = state if state is not None else load_extension_state()
    if name in current:
        return current[name]
    return default
