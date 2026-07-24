"""Fuzzy server name search with space/underscore equivalence."""

from __future__ import annotations

import re

from sshjumper_cli.config import ServerSummary

_TOKEN_SPLIT_RE = re.compile(r"[\s_]+")


def normalize_search(text: str) -> str:
    """Lowercase and remove spaces/underscores for comparison."""
    return _TOKEN_SPLIT_RE.sub("", text.lower())


def _subsequence_match(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    index = 0
    for char in haystack:
        if index < len(needle) and char == needle[index]:
            index += 1
    return index == len(needle)


def fuzzy_match(query: str, target: str) -> bool:
    """Return True if all query tokens fuzzy-match the target in order."""
    tokens = [token for token in _TOKEN_SPLIT_RE.split(query.strip().lower()) if token]
    if not tokens:
        return True

    haystack = normalize_search(target)
    return all(_subsequence_match(normalize_search(token), haystack) for token in tokens)


def prefix_match(query: str, target: str) -> bool:
    needle = normalize_search(query)
    if not needle:
        return True
    return normalize_search(target).startswith(needle)


def exact_match(query: str, target: str) -> bool:
    return normalize_search(query) == normalize_search(target)


def server_haystack(server: ServerSummary) -> str:
    parts = [server.name, server.environment, server.project]
    if server.description:
        parts.append(server.description)
    return " ".join(parts)


def filter_servers(servers: list[ServerSummary], query: str) -> list[ServerSummary]:
    text = query.strip()
    if not text:
        return servers
    return [server for server in servers if fuzzy_match(text, server_haystack(server))]


def resolve_server_name(server_names: list[str], query: str) -> tuple[str | None, str | None]:
    text = query.strip()
    if not text:
        return None, None

    exact = [name for name in server_names if exact_match(text, name)]
    if len(exact) == 1:
        return exact[0], None

    prefix = [name for name in server_names if prefix_match(text, name)]
    if len(prefix) == 1:
        return prefix[0], None
    if len(prefix) > 1:
        names = ", ".join(prefix[:6])
        return None, f"Ambiguous name. Tab to extend or pick from list: {names}"

    fuzzy = [name for name in server_names if fuzzy_match(text, name)]
    if len(fuzzy) == 1:
        return fuzzy[0], None
    if len(fuzzy) > 1:
        names = ", ".join(fuzzy[:6])
        return None, f"Multiple matches. Use Down arrow and Enter: {names}"

    return None, f"Server not found: {text}"


def prefix_completions(server_names: list[str], query: str) -> list[str]:
    if not query.strip():
        return []

    prefix = [name for name in server_names if prefix_match(query, name)]
    if prefix:
        return sorted(prefix, key=str.lower)

    fuzzy = [name for name in server_names if fuzzy_match(query, name)]
    return sorted(fuzzy, key=str.lower)


def common_prefix(query: str, names: list[str]) -> str:
    if not names:
        return query

    norm_query = normalize_search(query)
    norm_names = [normalize_search(name) for name in names]

    common_len = len(norm_query)
    max_len = min(len(name) for name in norm_names)
    while common_len < max_len:
        fragment = norm_names[0][: common_len + 1]
        if all(name.startswith(fragment) for name in norm_names):
            common_len += 1
        else:
            break

    if common_len <= len(norm_query):
        return query

    expanded: list[str] = []
    seen = 0
    for char in names[0]:
        if seen >= common_len:
            break
        if char not in (" ", "_"):
            seen += 1
        expanded.append(char)
    return "".join(expanded)
