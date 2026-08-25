"""Extension base types and connection context."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sshjumper_cli.config import ServerConfig


@dataclass
class ExtensionContext:
    """Shared context passed to extension hooks around a connection."""

    server: ServerConfig
    config_path: Path | None = None
    dry_run: bool = False
    extras: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Extension(Protocol):
    """Contract for SSHJumper extensions / plugins."""

    @property
    def name(self) -> str:
        """Stable id used in enable/disable and extensions.yml."""

    @property
    def description(self) -> str:
        """Short human-readable summary."""

    @property
    def default_enabled(self) -> bool:
        """Whether the extension is on before the user toggles it."""

    def is_available(self) -> bool:
        """Return False if required tools/deps are missing."""

    def pre_connect(self, ctx: ExtensionContext) -> None:
        """Run before OpenSSH starts (passwords, OTP, clipboard, title, …)."""

    def post_connect(self, ctx: ExtensionContext, exit_code: int) -> None:
        """Run after the SSH session ends (cleanup, restore title, …)."""


class BaseExtension:
    """Convenience base class for builtin and third-party extensions."""

    name: str = "unnamed"
    description: str = ""
    default_enabled: bool = False

    def is_available(self) -> bool:
        return True

    def pre_connect(self, ctx: ExtensionContext) -> None:
        return None

    def post_connect(self, ctx: ExtensionContext, exit_code: int) -> None:
        return None
