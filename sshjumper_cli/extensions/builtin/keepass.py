"""Builtin extension: fetch KeePass password by matching server/entry name."""

from __future__ import annotations

import getpass
import shutil
import subprocess
import sys
from pathlib import Path

from sshjumper_cli import ui
from sshjumper_cli.extensions.base import BaseExtension, ExtensionContext
from sshjumper_cli.extensions.builtin.clipboard import CLEAR_AFTER_SECONDS
from sshjumper_cli.extensions.state import is_enabled, load_extension_config
from sshjumper_cli.extensions.util.clipboard import (
    clipboard_backend_available,
    copy_to_clipboard,
    display_ready,
)
from sshjumper_cli.paths import keepass_database_path, keepass_password

# Cache unlocked DB across servers in one process (TUI session)
_KP_CACHE: dict[str, object] = {}


def _entry_path_text(item: object) -> str:
    """Safe path string for a pykeepass entry (path parts may be None)."""
    title = getattr(item, "title", None) or ""
    raw_path = getattr(item, "path", None)
    if not raw_path:
        return title
    parts = [str(part) for part in raw_path if part is not None and str(part) != ""]
    return "/".join(parts) if parts else title


class KeepassExtension(BaseExtension):
    name = "keepass"
    description = "Copy KeePass password for entry matching the server name"
    default_enabled = False

    def is_available(self) -> bool:
        if shutil.which("keepassxc-cli"):
            return True
        try:
            import pykeepass  # noqa: F401

            return True
        except ImportError:
            return False

    def pre_connect(self, ctx: ExtensionContext) -> None:
        if ctx.dry_run:
            return

        def not_available() -> None:
            ui.mark(ui.KEEPASS, "warn", "no password")

        def dep_missing() -> None:
            ui.mark(ui.KEEPASS, "warn", "no clipboard")

        def dep_display() -> None:
            ui.mark(ui.KEEPASS, "warn", "no display")

        if not self.is_available():
            not_available()
            return

        db_path = self._database_path()
        if db_path is None or not db_path.is_file():
            not_available()
            return

        queries = self._lookup_queries(ctx)
        master = self._unlock_password()
        if master is None:
            not_available()
            return
        ctx.extras["keepass_master"] = master  # reused by otp (no second prompt)

        try:
            secret, matched = self._read_entry_password(db_path, queries, master)
        except Exception:
            not_available()
            return

        if not secret:
            not_available()
            return

        # Password was found — remaining issues are clipboard/deps only
        ctx.extras["clipboard_secret"] = secret
        ctx.extras["clipboard_label"] = f"keepass:{matched or queries[0]}"

        if not is_enabled("clipboard", default=False):
            dep_missing()
            return

        if not clipboard_backend_available():
            dep_missing()
            return

        if not display_ready():
            dep_display()
            return

        if not copy_to_clipboard(secret):
            dep_missing()
            return

        ctx.extras["clipboard_done"] = True
        ui.mark(ui.KEEPASS)

    def _lookup_queries(self, ctx: ExtensionContext) -> list[str]:
        queries: list[str] = []
        raw = ctx.server.raw or {}
        for key in ("keepass_entry", "copy_pass_from_keepass", "keepass"):
            value = raw.get(key)
            if (
                isinstance(value, str)
                and value.strip()
                and value.strip().lower() not in ("true", "yes", "1", "on")
            ):
                queries.append(value.strip())

        queries.append(ctx.server.name)
        if ctx.server.description:
            queries.append(str(ctx.server.description))

        if ctx.server.hops:
            hop = ctx.server.hops[0]
            if hop.host:
                queries.append(str(hop.host))
            if hop.user and hop.host:
                queries.append(f"{hop.user}@{hop.host}")

        seen: set[str] = set()
        ordered: list[str] = []
        for item in queries:
            if item and item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered

    def _database_path(self) -> Path | None:
        env_path = keepass_database_path()
        if env_path is not None:
            return env_path
        cfg = load_extension_config(self.name)
        value = cfg.get("database")
        if value:
            return Path(str(value)).expanduser()
        return None

    def _unlock_password(self) -> str | None:
        env = keepass_password()
        if env is not None:
            return env
        cfg = load_extension_config(self.name)
        file_pw = cfg.get("password")
        if isinstance(file_pw, str) and file_pw:
            return file_pw
        if not sys.stdin.isatty():
            return None
        try:
            ui.end_line()
            return getpass.getpass("KeePass master password: ")
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return None

    def _read_entry_password(
        self,
        db_path: Path,
        queries: list[str],
        master: str,
    ) -> tuple[str | None, str | None]:
        if shutil.which("keepassxc-cli"):
            for query in queries:
                secret = self._cli_show_password(db_path, query, master)
                if secret is not None:
                    return secret, query
                matches = self._cli_search(db_path, query, master)
                if matches:
                    exact = [
                        m
                        for m in matches
                        if m.rstrip("/").split("/")[-1].lower() == query.lower()
                    ]
                    chosen = exact[0] if exact else matches[0]
                    secret = self._cli_show_password(db_path, chosen, master)
                    if secret is not None:
                        return secret, chosen

        return self._pykeepass_password(db_path, queries, master)

    def _pykeepass_password(
        self,
        db_path: Path,
        queries: list[str],
        master: str,
    ) -> tuple[str | None, str | None]:
        try:
            from pykeepass import PyKeePass
        except ImportError:
            return None, None

        cache_key = f"{db_path.resolve()}:{master}"
        kp = _KP_CACHE.get(cache_key)
        if kp is None:
            kp = PyKeePass(str(db_path), password=master)
            _KP_CACHE[cache_key] = kp

        entries = list(kp.entries)
        for query in queries:
            found = kp.find_entries(title=query, first=True)
            if found is not None and found.password:
                return found.password, found.title or query

            q = query.lower()
            for item in entries:
                title = item.title or ""
                if title.lower() == q and item.password:
                    return item.password, title

            for item in entries:
                title = item.title or ""
                path = _entry_path_text(item)
                if q in title.lower() or path.lower().endswith(q) or q in path.lower():
                    if item.password:
                        return item.password, title or path

        return None, None

    def _cli_show_password(self, db_path: Path, entry: str, master: str) -> str | None:
        cmd = [
            "keepassxc-cli",
            "show",
            "-q",
            "-a",
            "Password",
            str(db_path),
            entry,
        ]
        try:
            completed = subprocess.run(
                cmd,
                input=f"{master}\n".encode("utf-8"),
                capture_output=True,
                check=False,
            )
        except OSError:
            return None

        if completed.returncode != 0:
            return None
        text = completed.stdout.decode("utf-8", errors="replace").strip("\r\n")
        return text if text else None

    def _cli_search(self, db_path: Path, query: str, master: str) -> list[str]:
        cmd = ["keepassxc-cli", "search", str(db_path), query]
        try:
            completed = subprocess.run(
                cmd,
                input=f"{master}\n".encode("utf-8"),
                capture_output=True,
                check=False,
            )
        except OSError:
            return []
        if completed.returncode != 0:
            return []
        lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
        return [line.strip() for line in lines if line.strip()]
