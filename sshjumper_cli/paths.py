"""Path resolution and environment defaults."""

from __future__ import annotations

import os
from pathlib import Path


def default_config_path() -> Path:
    value = os.environ.get("SSHJUMPERCONFIGFILE")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".ssh" / "sshjumper" / "sshjconfig.yml"


def default_password_path() -> Path:
    value = os.environ.get("SSHJUMPERPASSWORDFILE")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".ssh" / "sshjumper" / "passwords.yml"


def ssh_keys_dir() -> Path:
    value = os.environ.get("SSHJUMPERSSHKEYS")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".ssh" / "ssh_keys"
