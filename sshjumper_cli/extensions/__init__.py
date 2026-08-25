"""SSHJumper extension / plugin system.

Builtin extensions live under ``sshjumper_cli.extensions.builtin``.
Enable or disable them with::

    sshjumper ext list
    sshjumper ext enable otp
    sshjumper ext disable clipboard

State file: ``~/.ssh/sshjumper/extensions.yml``
"""

from __future__ import annotations

from sshjumper_cli.config import ServerConfig
from sshjumper_cli.extensions.base import BaseExtension, Extension, ExtensionContext
from sshjumper_cli.extensions.registry import (
    all_extensions,
    enabled_extensions,
    extension_status_rows,
    get_extension,
    require_extension,
    run_post_connect,
    run_pre_connect,
    set_extension_enabled,
)


def run_extensions(server: ServerConfig) -> None:
    """Back-compat: run enabled pre_connect hooks only."""
    run_pre_connect(server)


__all__ = [
    "BaseExtension",
    "Extension",
    "ExtensionContext",
    "all_extensions",
    "enabled_extensions",
    "extension_status_rows",
    "get_extension",
    "require_extension",
    "run_extensions",
    "run_post_connect",
    "run_pre_connect",
    "set_extension_enabled",
]
