"""Interactive TUI for server selection."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.widgets import Static, Tree

from sshjumper_cli.config import GENERIC_GROUP, ServerSummary, group_servers, list_servers
from sshjumper_cli.search import (
    common_prefix,
    filter_servers,
    prefix_completions,
    resolve_server_name,
)
from sshjumper_cli.validator import validate_server


class ServerPickerApp(App):
    """Pick a server with global typing and a static grouped tree."""

    TITLE = "SSHJumper"

    CSS = """
    Screen {
        layout: vertical;
    }

    #search-display {
        margin: 1 2 0 2;
        padding: 0;
        color: $success;
        text-style: bold;
        height: 3;
        content-align: left middle;
    }

    #error {
        padding: 0 2;
        color: $error;
        text-style: bold;
        min-height: 1;
    }

    #servers {
        height: 1fr;
        margin: 0 1 1 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
    ]

    def __init__(self, config_path: Path, servers: list[ServerSummary]) -> None:
        super().__init__()
        self.config_path = config_path
        self.servers = servers
        self.server_names = [server.name for server in servers]
        self.selected_server: str | None = None
        self._query = ""
        self._cursor_visible = True

    def compose(self) -> ComposeResult:
        yield Static("", id="search-display")
        yield Static("", id="error")
        yield Tree("", id="servers")

    def on_mount(self) -> None:
        tree = self.query_one("#servers", Tree)
        tree.can_focus = False
        tree.show_root = False
        tree.auto_expand = False
        tree.root.expand()
        tree.root.allow_expand = False
        self.set_interval(0.5, self._toggle_cursor)
        self._apply_query()

    def _toggle_cursor(self) -> None:
        self._cursor_visible = not self._cursor_visible
        self._update_search_display()

    def _update_search_display(self) -> None:
        cursor = "_" if self._cursor_visible else " "
        self.query_one("#search-display", Static).update(f"{self._query}{cursor}")

    def _filtered_servers(self, query: str) -> list[ServerSummary]:
        return filter_servers(self.servers, query)

    def _rebuild_tree(self, preserve_server: str | None = None) -> None:
        tree = self.query_one("#servers", Tree)
        previous = preserve_server or self._highlighted_server()
        tree.clear()
        tree.root.expand()
        filtered = self._filtered_servers(self._query)

        if not filtered:
            tree.root.add_leaf("No matching servers", data=None)
            return

        for project, environments in group_servers(filtered):
            project_node = tree.root.add(project, expand=True, allow_expand=False)
            for environment, entries in environments:
                parent = project_node
                if not (project == GENERIC_GROUP and environment == GENERIC_GROUP):
                    parent = project_node.add(environment, expand=True, allow_expand=False)
                for entry in entries:
                    label = entry.name
                    if entry.description:
                        label = f"{entry.name}  —  {entry.description}"
                    parent.add_leaf(label, data=entry.name)

        leaves = self._server_leaves(tree)
        if previous:
            for leaf in leaves:
                if leaf.data == previous:
                    tree.select_node(leaf)
                    return

        if leaves:
            tree.select_node(leaves[0])

    def _tree(self) -> Tree:
        return self.query_one("#servers", Tree)

    def _server_leaves(self, tree: Tree) -> list:
        leaves = []
        for project in tree.root.children:
            for child in project.children:
                if child.data is not None:
                    leaves.append(child)
                else:
                    leaves.extend(child.children)
        return leaves

    def _highlighted_server(self) -> str | None:
        node = self._tree().cursor_node
        if node is None or node.data is None:
            return None
        return str(node.data)

    def _apply_query(self) -> None:
        self._show_error("")
        self._update_search_display()
        self._rebuild_tree()

    def _prefix_matches(self, query: str) -> list[str]:
        return prefix_completions(self.server_names, query)

    def _resolve_server(self, query: str) -> tuple[str | None, str | None]:
        return resolve_server_name(self.server_names, query)

    def _try_connect(self, server_name: str) -> None:
        try:
            validate_server(self.config_path, server_name)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            self._show_error(str(exc))
            return

        self.selected_server = server_name
        self.exit()

    def _connect_current(self) -> None:
        query = self._query.strip()

        if query:
            match, error = self._resolve_server(query)
            if match:
                self._try_connect(match)
                return
            if error:
                highlighted = self._highlighted_server()
                if highlighted:
                    self._try_connect(highlighted)
                    return
                self._show_error(error)
                return

        highlighted = self._highlighted_server()
        if highlighted:
            self._try_connect(highlighted)
            return

        self._show_error("Type a server name, Tab to complete, or Down to pick from the tree")

    def _accept_tab_completion(self) -> None:
        query = self._query
        if not query:
            return

        matches = self._prefix_matches(query)
        if not matches:
            self._show_error(f"No completion for: {query}")
            return

        if len(matches) == 1:
            self._query = matches[0]
            self._apply_query()
            self._show_error("")
            return

        completed = common_prefix(query, matches)
        if completed == query:
            self._show_error(f"{len(matches)} matches — Tab again or use Down arrow")
            return

        self._query = completed
        self._apply_query()
        self._show_error(f"{len(self._prefix_matches(self._query))} matches — Tab again or use Down arrow")

    def _show_error(self, message: str) -> None:
        self.query_one("#error", Static).update(message)

    def on_key(self, event: Key) -> None:
        tree = self._tree()

        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self._accept_tab_completion()
            return

        if event.key == "down":
            event.prevent_default()
            event.stop()
            tree.action_cursor_down()
            return

        if event.key == "up":
            event.prevent_default()
            event.stop()
            tree.action_cursor_up()
            return

        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self._connect_current()
            return

        if event.key == "backspace":
            event.prevent_default()
            event.stop()
            if self._query:
                self._query = self._query[:-1]
                self._apply_query()
            return

        if event.key == "ctrl+u":
            event.prevent_default()
            event.stop()
            if self._query:
                self._query = ""
                self._apply_query()
            return

        if event.is_printable and event.character:
            event.prevent_default()
            event.stop()
            self._query += event.character
            self._apply_query()

    def action_quit(self) -> None:
        self.exit()


def pick_server(config_path: Path) -> str | None:
    servers = list_servers(config_path)
    if not servers:
        print(f"No servers found in: {config_path}")
        return None

    app = ServerPickerApp(config_path, servers)
    app.run()
    return app.selected_server
