"""Configuration validation before SSH execution."""

from __future__ import annotations

from pathlib import Path

from sshjumper_cli.config import ServerConfig, load_server


def validate_server(config_path: Path, server_name: str) -> ServerConfig:
    server = load_server(config_path, server_name)

    if not server.hops:
        raise ValueError(f"No hops configured for: {server_name}")

    for hop in server.hops:
        label = f"hop{hop.number}"
        if not hop.host:
            raise ValueError(f"{label} missing required field: host")

        if hop.port is not None and (hop.port < 1 or hop.port > 65535):
            raise ValueError(f"Invalid port for {label}: {hop.port}")

        if hop.resolved_key is not None and not hop.resolved_key.exists():
            raise ValueError(f"Key file not found for {label}: {hop.resolved_key}")

    if server.localcommand is not None and not isinstance(server.localcommand, str):
        raise ValueError(f"localcommand must be a string for: {server_name}")

    if server.remotecommand is not None and not isinstance(server.remotecommand, str):
        raise ValueError(f"remotecommand must be a string for: {server_name}")

    return server
