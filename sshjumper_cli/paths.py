"""Path resolution and environment defaults."""

from __future__ import annotations

import os
from pathlib import Path


def sshjumper_dir() -> Path:
    return Path.home() / ".ssh" / "sshjumper"


def default_config_path() -> Path:
    value = os.environ.get("SSHJUMPERCONFIGFILE")
    if value:
        return Path(value).expanduser()
    return sshjumper_dir() / "sshjconfig.yml"


def default_password_path() -> Path:
    value = os.environ.get("SSHJUMPERPASSWORDFILE")
    if value:
        return Path(value).expanduser()
    return sshjumper_dir() / "passwords.yml"


def extensions_state_path() -> Path:
    value = os.environ.get("SSHJUMPEREXTENSIONSFILE")
    if value:
        return Path(value).expanduser()
    return sshjumper_dir() / "extensions.yml"


def ssh_keys_dir() -> Path:
    value = os.environ.get("SSHJUMPERSSHKEYS")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".ssh" / "ssh_keys"


def keepass_database_path() -> Path | None:
    """KeePass DB path from env, else None (extension config may override)."""
    value = os.environ.get("SSHJUMPERKEEPASSDATABASE")
    if value:
        return Path(value).expanduser()
    return None


def keepass_password() -> str | None:
    value = os.environ.get("SSHJUMPERKEEPASSPASSWORD")
    if value is None or value == "":
        return None
    return value
