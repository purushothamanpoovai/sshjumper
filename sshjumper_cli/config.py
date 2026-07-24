"""YAML configuration loading and hop extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sshjumper_cli.boolean import optional_bool
from sshjumper_cli.paths import ssh_keys_dir

HOP_KEY_RE = re.compile(r"^hop(\d+)$", re.IGNORECASE)
GENERIC_GROUP = "Generic"


@dataclass
class ServerSummary:
    name: str
    description: str | None = None
    environment: str = GENERIC_GROUP
    project: str = GENERIC_GROUP


def normalize_group_label(value: Any) -> str:
    if value is None:
        return GENERIC_GROUP
    text = str(value).strip()
    return text if text else GENERIC_GROUP


@dataclass
class Hop:
    number: int
    host: str
    user: str | None = None
    port: int | None = None
    key: str | None = None
    resolved_key: Path | None = None


@dataclass
class ServerConfig:
    name: str
    hops: list[Hop] = field(default_factory=list)
    description: str | None = None
    environment: str = GENERIC_GROUP
    project: str = GENERIC_GROUP
    keep_alive: bool = False
    terminal: bool = True
    x11: bool = False
    quiet: bool = False
    verbose: bool = False
    localcommand: str | None = None
    remotecommand: str | None = None
    copy: str | None = None
    otp_secret: str | None = None
    password: Any = None
    sudo: Any = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def final_hop(self) -> Hop:
        return self.hops[-1]

    @property
    def hop_path(self) -> str:
        return " -> ".join(hop.host for hop in self.hops)


def load_yaml_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML root in: {config_path}")

    return data


def list_servers(config_path: Path) -> list[ServerSummary]:
    data = load_yaml_config(config_path)
    servers: list[ServerSummary] = []
    for name, section in data.items():
        if not isinstance(section, dict):
            continue
        desc = section.get("description")
        servers.append(
            ServerSummary(
                name=str(name),
                description=str(desc) if desc is not None else None,
                environment=normalize_group_label(section.get("environment")),
                project=normalize_group_label(section.get("project")),
            )
        )
    return sorted(servers, key=lambda item: (item.project.lower(), item.environment.lower(), item.name.lower()))


def group_servers(
    servers: list[ServerSummary],
) -> list[tuple[str, list[tuple[str, list[ServerSummary]]]]]:
    """Group servers as project -> environment -> servers."""
    grouped: dict[str, dict[str, list[ServerSummary]]] = {}
    for server in servers:
        grouped.setdefault(server.project, {}).setdefault(server.environment, []).append(server)

    def project_sort_key(project: str) -> tuple[int, str]:
        return (int(project == GENERIC_GROUP), project.lower())

    def environment_sort_key(environment: str) -> tuple[int, str]:
        return (int(environment == GENERIC_GROUP), environment.lower())

    result: list[tuple[str, list[tuple[str, list[ServerSummary]]]]] = []
    for project in sorted(grouped, key=project_sort_key):
        environments = grouped[project]
        env_groups = [
            (environment, sorted(entries, key=lambda item: item.name.lower()))
            for environment, entries in sorted(environments.items(), key=lambda item: environment_sort_key(item[0]))
        ]
        result.append((project, env_groups))
    return result


def resolve_key_path(key: str | None, keys_dir: Path) -> Path | None:
    if not key:
        return None
    path = Path(key).expanduser()
    if path.is_absolute():
        return path
    return keys_dir / key


def extract_hops(server_name: str, section: dict[str, Any], keys_dir: Path) -> list[Hop]:
    hop_entries: list[tuple[int, dict[str, Any]]] = []
    for key, value in section.items():
        match = HOP_KEY_RE.match(str(key))
        if not match:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"{key} must be a mapping for server: {server_name}")
        hop_entries.append((int(match.group(1)), value))

    if not hop_entries:
        raise ValueError(f"No hops configured for: {server_name}")

    hop_entries.sort(key=lambda item: item[0])

    hops: list[Hop] = []
    for number, hop_data in hop_entries:
        host = hop_data.get("host")
        if not host:
            raise ValueError(f"hop{number} missing required field: host")

        port = hop_data.get("port")
        if port is not None and not isinstance(port, int):
            try:
                port = int(port)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid port for hop{number}: {port}") from exc

        key = hop_data.get("key")
        hops.append(
            Hop(
                number=number,
                host=str(host),
                user=str(hop_data["user"]) if hop_data.get("user") else None,
                port=port,
                key=str(key) if key else None,
                resolved_key=resolve_key_path(str(key) if key else None, keys_dir),
            )
        )

    return hops


def load_server(config_path: Path, server_name: str) -> ServerConfig:
    data = load_yaml_config(config_path)

    if server_name not in data:
        raise KeyError(f"Server not found: {server_name}")

    section = data[server_name]
    if not isinstance(section, dict):
        raise ValueError(f"Invalid server config for: {server_name}")

    keys_dir = ssh_keys_dir()
    hops = extract_hops(server_name, section, keys_dir)

    return ServerConfig(
        name=server_name,
        hops=hops,
        description=str(section["description"]) if section.get("description") else None,
        environment=normalize_group_label(section.get("environment")),
        project=normalize_group_label(section.get("project")),
        keep_alive=optional_bool(section.get("keep_alive"), "keep_alive", False),
        terminal=optional_bool(section.get("terminal"), "terminal", True),
        x11=optional_bool(section.get("x11"), "x11", False),
        quiet=optional_bool(section.get("quiet"), "quiet", False),
        verbose=optional_bool(section.get("verbose"), "verbose", False),
        localcommand=str(section["localcommand"]) if section.get("localcommand") else None,
        remotecommand=str(section["remotecommand"]) if section.get("remotecommand") else None,
        copy=str(section["copy"]) if section.get("copy") else None,
        otp_secret=str(section["otp_secret"]) if section.get("otp_secret") else None,
        password=section.get("password"),
        sudo=section.get("sudo"),
        raw=section,
    )
