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


_KEEPASS_PASSWORD_VARS = ("SSHJUMPERKEEPASSPASSWORD", "SSHJUMBERKEEPASSPASSWORD")
_keepass_password: str | None = None


def take_secret_env() -> None:
    """Move the KeePass master password out of ``os.environ``.

    Everything sshjumper starts (ssh, rsync, scp, localcommand, the editor,
    clipboard tools) inherits ``os.environ``; none of them needs the master
    password, so it is kept only inside this process.
    """
    global _keepass_password
    for var in _KEEPASS_PASSWORD_VARS:
        value = os.environ.pop(var, None)
        if value and _keepass_password is None:
            _keepass_password = value


def keepass_password() -> str | None:
    """KeePass master password: passwords.yml, then the environment variable."""
    from_file = _password_file_value("keepass", "master_password")
    if from_file:
        return from_file
    take_secret_env()  # also covers callers that skip cli.main
    return _keepass_password or None


def _password_file_value(section: str, key: str) -> str | None:
    """Read ``section.key`` from passwords.yml (must be private: chmod 600)."""
    path = default_password_path()
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
    except OSError:
        return None
    check_private_file(path)
    import yaml

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid passwords file: {path}")
    value = (data.get(section) or {}).get(key) if isinstance(data.get(section), dict) else None
    return str(value) if value not in (None, "") else None


def check_private_file(path: Path) -> None:
    """Refuse a file another user can read or change (secrets, localcommand)."""
    problem = _permission_problem(path, 0o077)
    if problem:
        raise ValueError(problem)


def _permission_problem(path: Path, forbidden: int) -> str | None:
    try:
        info = path.stat()
    except OSError:
        return None
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        return f"{path} is not owned by you"
    if info.st_mode & forbidden:
        mode = "700" if path.is_dir() else "600"
        return f"{path} is accessible by other users (mode {info.st_mode & 0o777:o}); run: chmod {mode} {path}"
    return None


def insecure_files(config_path: Path | None = None) -> list[str]:
    """Problems with sshjumper's own folder and files (config, extensions, passwords)."""
    paths = [sshjumper_dir(), default_config_path(), extensions_state_path(), default_password_path()]
    if config_path is not None:
        paths.append(config_path)
    problems: list[str] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        problem = _permission_problem(resolved, 0o077)
        if problem:
            problems.append(problem)
    return problems
