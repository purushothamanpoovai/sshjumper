"""Build a minimal temporary OpenSSH config for ProxyJump chains.

Python writes only connection routing (Host, HostName, User, Port,
IdentityFile, ProxyJump). All SSH behaviour (auth, known_hosts, keepalive,
TTY, forwarding) is left to the system ``ssh`` binary and the user's
OpenSSH configuration.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sshjumper_cli.config import Hop, ServerConfig


def _sanitize_alias(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)


def hop_alias(server_name: str, hop: Hop) -> str:
    return f"sshj_{_sanitize_alias(server_name)}_hop{hop.number}"


@dataclass
class GeneratedSSHConfig:
    path: Path
    final_alias: str
    content: str

    def cleanup(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def _hop_block(alias: str, hop: Hop, proxy_jump: str | None) -> list[str]:
    lines = [f"Host {alias}", f"    HostName {hop.host}"]
    if hop.user:
        lines.append(f"    User {hop.user}")
    if hop.port:
        lines.append(f"    Port {hop.port}")
    if hop.resolved_key:
        lines.append(f"    IdentityFile {hop.resolved_key}")
    if proxy_jump:
        lines.append(f"    ProxyJump {proxy_jump}")
    return lines


def generate_ssh_config(server: ServerConfig) -> GeneratedSSHConfig:
    blocks: list[str] = []
    aliases: list[str] = []

    for index, hop in enumerate(server.hops):
        alias = hop_alias(server.name, hop)
        aliases.append(alias)
        proxy = aliases[index - 1] if index > 0 else None
        blocks.extend(_hop_block(alias, hop, proxy))
        blocks.append("")

    content = "\n".join(blocks).rstrip() + "\n"
    final_alias = aliases[-1]

    fd, raw_path = tempfile.mkstemp(prefix="sshjumper_", suffix=".conf")
    os.close(fd)
    path = Path(raw_path)
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    return GeneratedSSHConfig(path=path, final_alias=final_alias, content=content)
