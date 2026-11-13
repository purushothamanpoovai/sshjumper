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

# System / meta top-level keys (leading "_" = reserved, not a connectable server).
# Legacy aliases without "_" are still accepted when reading configs.
META_GLOBAL_KEYS = ("_global", "global")
META_HOSTS_KEYS = ("_hosts", "hosts")
RESERVED_TOP_LEVEL = frozenset({*META_GLOBAL_KEYS, *META_HOSTS_KEYS})

# Fields that ``_global:`` may set as defaults for every server.
# Per-server values win when explicitly set (SSH ``Host *`` style).
GLOBAL_SERVER_FIELDS = frozenset(
    {
        "keep_alive",
        "terminal",
        "x11",
        "quiet",
        "verbose",
        "localcommand",
        "remotecommand",
        "environment",
        "project",
        "copy",
        "ssh_options",
        "otp_secret",  # legacy: still accepted in _global so old configs load; unused
    }
)

HOP_FIELDS = frozenset({"host", "user", "port", "key", "port_forward", "totp", "ssh_options"})

# Written by sshjumper itself from the hop fields; not allowed in ssh_options.
_MANAGED_SSH_OPTIONS = frozenset(
    {"host", "match", "include", "hostname", "user", "port", "identityfile", "proxyjump"}
)
_SSH_OPTION_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


class _ConfigLoader(yaml.SafeLoader):
    """SafeLoader without YAML 1.1 base-60 integers.

    Plain YAML 1.1 reads ``8000:22`` as the integer 480022, which would silently
    break ``port_forward`` values. Here ``a:b`` scalars stay strings.
    """


_INT_TAG = "tag:yaml.org,2002:int"
_ConfigLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != _INT_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_ConfigLoader.add_implicit_resolver(
    _INT_TAG,
    re.compile(
        r"""^(?:[-+]?0b[0-1_]+
        |[-+]?0[0-7_]+
        |[-+]?(?:0|[1-9][0-9_]*)
        |[-+]?0x[0-9a-fA-F_]+)$""",
        re.X,
    ),
    list("-+0123456789"),
)

@dataclass
class ServerSummary:
    name: str
    description: str | None = None
    environment: str = GENERIC_GROUP
    project: str = GENERIC_GROUP


def parse_keep_alive(value: Any) -> int:
    """keep_alive: seconds between keep-alive probes; 0 (or omitted) = off."""
    if value is None:
        return 0
    text = str(value).strip().lower()
    if text.endswith("s"):
        text = text[:-1]
    if isinstance(value, bool) or not text.isdigit():
        raise ValueError(f"keep_alive must be a number of seconds (0 = off), got {value!r}")
    return int(text)


def normalize_group_label(value: Any) -> str:
    if value is None:
        return GENERIC_GROUP
    text = str(value).strip()
    return text if text else GENERIC_GROUP


@dataclass
class PortForward:
    """Local port forward (``ssh -L``): ``local_port`` on this machine -> ``remote_port``.

    ``remote_host`` is the destination as seen from the target hop; ``None`` means
    the target hop itself (``localhost`` there).
    """

    local_port: int
    remote_port: int
    remote_host: str | None = None

    def __str__(self) -> str:
        middle = f"{self.remote_host}:" if self.remote_host else ""
        return f"{self.local_port}:{middle}{self.remote_port}"


def _parse_forward_port(value: str, label: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid port in {label}: {value!r}") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"Port out of range in {label}: {port}")
    return port


def parse_port_forwards(value: Any, label: str) -> list[PortForward]:
    """Parse ``port_forward`` values.

    Accepted forms (single value or a list of them)::

        port_forward: 3306                  # local 3306 -> remote 3306
        port_forward: 3000:3306             # local 3000 -> remote 3306
        port_forward: 3000:db.internal:3306 # local 3000 -> db.internal:3306 (from that hop)
    """
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    forwards: list[PortForward] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            raise ValueError(f"{label} entries must be 'PORT', 'LOCAL:REMOTE' or 'LOCAL:HOST:REMOTE'")
        parts = [part.strip() for part in str(item).strip().split(":")]
        if len(parts) == 1:
            port = _parse_forward_port(parts[0], label)
            forwards.append(PortForward(local_port=port, remote_port=port))
        elif len(parts) == 2:
            forwards.append(
                PortForward(
                    local_port=_parse_forward_port(parts[0], label),
                    remote_port=_parse_forward_port(parts[1], label),
                )
            )
        elif len(parts) == 3 and parts[1]:
            forwards.append(
                PortForward(
                    local_port=_parse_forward_port(parts[0], label),
                    remote_host=parts[1],
                    remote_port=_parse_forward_port(parts[2], label),
                )
            )
        else:
            raise ValueError(f"Invalid {label}: {item!r} (use LOCAL:REMOTE or LOCAL:HOST:REMOTE)")
    return forwards


def parse_ssh_options(value: Any, label: str) -> dict[str, str]:
    """``ssh_options:`` mapping of extra OpenSSH options, e.g. ``WarnWeakCrypto: no-pq-kex``.

    Names are OpenSSH option names; values may be text, numbers or yes/no
    booleans. Options sshjumper writes itself (HostName, User, Port,
    IdentityFile, ProxyJump) are rejected: use the hop fields for those.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping of OpenSSH options (Option: value)")
    options: dict[str, str] = {}
    for name, raw in value.items():
        name = str(name).strip()
        if not _SSH_OPTION_NAME_RE.match(name):
            raise ValueError(f"{label}: invalid OpenSSH option name {name!r}")
        if name.lower() in _MANAGED_SSH_OPTIONS:
            raise ValueError(f"{label}: {name} is set by sshjumper from the hop fields, not ssh_options")
        if isinstance(raw, bool):
            text = "yes" if raw else "no"
        elif isinstance(raw, (int, float, str)) and str(raw).strip():
            text = str(raw).strip()
        else:
            raise ValueError(f"{label}.{name} must be text, a number or yes/no")
        if _CONTROL_CHARS_RE.search(text):
            raise ValueError(f"{label}.{name} contains control characters")
        options[name] = text
    return options


@dataclass
class Hop:
    number: int
    host: str
    user: str | None = None
    port: int | None = None
    key: str | None = None
    resolved_key: Path | None = None
    port_forwards: list[PortForward] = field(default_factory=list)
    totp: str | None = None  # TOTP source for this hop (used by the otp extension)
    ssh_options: dict[str, str] = field(default_factory=dict)  # this hop only


@dataclass
class ServerConfig:
    name: str
    hops: list[Hop] = field(default_factory=list)
    description: str | None = None
    environment: str = GENERIC_GROUP
    project: str = GENERIC_GROUP
    keep_alive: int = 0  # ServerAliveInterval seconds; 0 = off
    terminal: bool = True
    x11: bool = False
    quiet: bool = False
    verbose: bool = False
    localcommand: str | None = None
    remotecommand: str | None = None
    copy: str | None = None
    password: Any = None
    port_forwards: list[PortForward] = field(default_factory=list)
    ssh_options: dict[str, str] = field(default_factory=dict)  # every hop (_global + server)
    raw: dict[str, Any] = field(default_factory=dict)


def load_yaml_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with config_path.open(encoding="utf-8") as handle:
        data = yaml.load(handle, Loader=_ConfigLoader)  # noqa: S506 - SafeLoader subclass

    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML root in: {config_path}")

    return data


def _first_meta_section(
    data: dict[str, Any],
    keys: tuple[str, ...],
    *,
    label: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """Return (key_used, mapping) for the first present meta section."""
    found: list[str] = []
    for key in keys:
        if key not in data:
            continue
        found.append(key)
    if not found:
        return None, None
    if len(found) > 1:
        raise ValueError(
            f"Use only one of {', '.join(repr(k) for k in keys)} "
            f"(found: {', '.join(repr(k) for k in found)})"
        )
    key = found[0]
    raw = data[key]
    if raw is None:
        return key, {}
    if not isinstance(raw, dict):
        raise ValueError(f"'{key}' ({label}) must be a mapping")
    return key, raw


def load_global_defaults(data: dict[str, Any]) -> dict[str, Any]:
    """Load shared server defaults from ``_global:`` (alias: ``global:``)."""
    key, raw = _first_meta_section(data, META_GLOBAL_KEYS, label="global defaults")
    if raw is None:
        return {}

    defaults: dict[str, Any] = {}
    unknown: list[str] = []
    for field_name, field_value in raw.items():
        name = str(field_name)
        if name not in GLOBAL_SERVER_FIELDS:
            unknown.append(name)
            continue
        defaults[name] = field_value
    if unknown:
        raise ValueError(
            f"'{key}' unknown field(s): {', '.join(sorted(unknown))} "
            f"(allowed: {', '.join(sorted(GLOBAL_SERVER_FIELDS))})"
        )
    return defaults


def load_host_templates(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Load reusable hop templates from ``_hosts:`` (alias: ``hosts:``)."""
    key, raw = _first_meta_section(data, META_HOSTS_KEYS, label="hop templates")
    if raw is None:
        return {}

    section = key or "_hosts"
    templates: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        tmpl = str(name)
        if not isinstance(value, dict):
            raise ValueError(f"{section}.{tmpl} must be a mapping (host/user/port/key)")
        if not value.get("host"):
            raise ValueError(f"{section}.{tmpl} missing required field: host")
        templates[tmpl] = dict(value)
    return templates


def apply_global_defaults(
    section: dict[str, Any],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """Merge ``_global`` into a server section. Explicit server keys win."""
    if not defaults:
        return dict(section)
    merged = dict(section)
    for field_name, field_value in defaults.items():
        if field_name not in merged:
            merged[field_name] = field_value
    return merged


def resolve_hop_data(
    hop_label: str,
    hop_value: Any,
    templates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve a hop entry into a concrete hop mapping.

    Supported forms:
      hop1: bastion                 # reference _hosts.bastion
      hop1:                         # inline hop (unchanged)
        host: ...
      hop1:                         # reference + optional field overrides
        use: bastion
        user: other
    """
    if isinstance(hop_value, str):
        name = hop_value.strip()
        if not name:
            raise ValueError(f"{hop_label} host reference is empty")
        if name not in templates:
            raise ValueError(f"{hop_label} references unknown _hosts.{name}")
        return dict(templates[name])

    if not isinstance(hop_value, dict):
        raise ValueError(f"{hop_label} must be a mapping or a _hosts.* name")

    use_name = hop_value.get("use")
    if use_name is None:
        # Plain hop map — reject accidental "use"-less refs that only have unknown keys
        return dict(hop_value)

    if not isinstance(use_name, str):
        raise ValueError(f"{hop_label}.use must be a _hosts.* name (string)")

    name = use_name.strip()
    if not name:
        raise ValueError(f"{hop_label}.use is empty")
    if name not in templates:
        raise ValueError(f"{hop_label} references unknown _hosts.{name}")

    merged = dict(templates[name])
    for field_name, field_value in hop_value.items():
        if field_name == "use":
            continue
        if field_name not in HOP_FIELDS:
            raise ValueError(
                f"{hop_label} unknown field with use: {field_name} "
                f"(allowed: {', '.join(sorted(HOP_FIELDS))})"
            )
        merged[field_name] = field_value
    return merged

def list_servers(config_path: Path) -> list[ServerSummary]:
    data = load_yaml_config(config_path)
    servers: list[ServerSummary] = []
    for name, section in data.items():
        if str(name) in RESERVED_TOP_LEVEL:
            continue
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


_UNSAFE_HOST_USER_RE = re.compile(r"[\s\x00-\x1f\x7f]")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _safe_value(label: str, field_name: str, value: str, pattern: re.Pattern[str]) -> str:
    """Reject values that could inject extra directives into the generated ssh config."""
    if pattern.search(value):
        raise ValueError(f"{label} {field_name} contains spaces or control characters: {value!r}")
    return value


def resolve_key_path(key: str | None, keys_dir: Path) -> Path | None:
    if not key:
        return None
    path = Path(key).expanduser()
    if path.is_absolute():
        return path
    return keys_dir / key


def extract_hops(
    server_name: str,
    section: dict[str, Any],
    keys_dir: Path,
    templates: dict[str, dict[str, Any]] | None = None,
) -> list[Hop]:
    templates = templates or {}
    hop_entries: list[tuple[int, Any]] = []
    for key, value in section.items():
        match = HOP_KEY_RE.match(str(key))
        if not match:
            continue
        hop_entries.append((int(match.group(1)), value))

    if not hop_entries:
        raise ValueError(f"No hops configured for: {server_name}")

    hop_entries.sort(key=lambda item: item[0])

    hops: list[Hop] = []
    for number, hop_value in hop_entries:
        label = f"hop{number}"
        hop_data = resolve_hop_data(label, hop_value, templates)

        host = hop_data.get("host")
        if not host:
            raise ValueError(f"{label} missing required field: host")

        port = hop_data.get("port")
        if port is not None and not isinstance(port, int):
            try:
                port = int(port)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid port for {label}: {port}") from exc

        host = _safe_value(label, "host", str(host), _UNSAFE_HOST_USER_RE)
        user = hop_data.get("user")
        if user:
            user = _safe_value(label, "user", str(user), _UNSAFE_HOST_USER_RE)
        key = hop_data.get("key")
        if key:
            key = _safe_value(label, "key", str(key), _CONTROL_CHARS_RE)
        hops.append(
            Hop(
                number=number,
                host=host,
                user=user or None,
                port=port,
                key=str(key) if key else None,
                resolved_key=resolve_key_path(str(key) if key else None, keys_dir),
                port_forwards=parse_port_forwards(hop_data.get("port_forward"), f"{label}.port_forward"),
                totp=str(hop_data["totp"]).strip() if hop_data.get("totp") else None,
                ssh_options=parse_ssh_options(hop_data.get("ssh_options"), f"{label}.ssh_options"),
            )
        )

    return hops


def load_server(config_path: Path, server_name: str) -> ServerConfig:
    data = load_yaml_config(config_path)

    if server_name in RESERVED_TOP_LEVEL:
        raise KeyError(f"'{server_name}' is a reserved config section, not a server")

    if server_name not in data:
        raise KeyError(f"Server not found: {server_name}")

    section = data[server_name]
    if not isinstance(section, dict):
        raise ValueError(f"Invalid server config for: {server_name}")

    defaults = load_global_defaults(data)
    # ssh_options merge option by option: _global first, the server's own win.
    ssh_options = {
        **parse_ssh_options(defaults.get("ssh_options"), "_global.ssh_options"),
        **parse_ssh_options(section.get("ssh_options"), f"{server_name}.ssh_options"),
    }
    section = apply_global_defaults(section, defaults)
    templates = load_host_templates(data)
    keys_dir = ssh_keys_dir()
    hops = extract_hops(server_name, section, keys_dir, templates)
    return ServerConfig(
        name=server_name,
        hops=hops,
        description=str(section["description"]) if section.get("description") else None,
        environment=normalize_group_label(section.get("environment")),
        project=normalize_group_label(section.get("project")),
        keep_alive=parse_keep_alive(section.get("keep_alive")),
        terminal=optional_bool(section.get("terminal"), "terminal", True),
        x11=optional_bool(section.get("x11"), "x11", False),
        quiet=optional_bool(section.get("quiet"), "quiet", False),
        verbose=optional_bool(section.get("verbose"), "verbose", False),
        localcommand=str(section["localcommand"]) if section.get("localcommand") else None,
        remotecommand=str(section["remotecommand"]) if section.get("remotecommand") else None,
        copy=str(section["copy"]) if section.get("copy") else None,
        password=section.get("password"),
        port_forwards=parse_port_forwards(section.get("port_forward"), "port_forward"),
        ssh_options=ssh_options,
        raw=section,
    )
