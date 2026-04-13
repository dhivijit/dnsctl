"""History screen — browse git commits, preview state, rollback, export."""

import json
import logging
from pathlib import Path

from textual import work

logger = logging.getLogger(__name__)
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Label, Static


class HistoryScreen(Screen):
    """Git commit browser for a single account's state repo."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("r", "rollback", "Rollback"),
        Binding("x", "export", "Export"),
        Binding("ctrl+q", "app.quit", "Quit"),
    ]

    def __init__(self, alias: str) -> None:
        super().__init__()
        self._alias = alias
        self._commits: list[dict] = []

    # ------------------------------------------------------------------ compose

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" History — {self._alias}", id="history-bar")
        with Horizontal(id="history-split"):
            with Vertical(id="history-left"):
                table = DataTable(id="history-table", cursor_type="row", zebra_stripes=True)
                table.add_columns("SHA", "Date", "Message")
                yield table
            with ScrollableContainer(id="history-preview"):
                yield Static("", id="preview-content")
        with Horizontal(id="history-buttons"):
            yield Button("Rollback to this commit", variant="error", id="rollback-btn", disabled=True)
            yield Button("Export state", id="export-btn", disabled=True)
            yield Button("Back", id="back-btn")
        yield Label("Select a commit to preview", id="history-status")
        yield Footer()

    # ------------------------------------------------------------------ mount / load

    def on_mount(self) -> None:
        self._load_history()

    @work(thread=True)
    def _load_history(self) -> None:
        from dnsctl.config import ACCOUNTS_DIR
        from dnsctl.core.git_manager import GitManager

        git = GitManager(ACCOUNTS_DIR / self._alias)
        git.auto_init()
        commits = git.log(max_count=100)

        def _populate(commits: list[dict]) -> None:
            from dnsctl.core.git_manager import GitManager
            table = self.query_one("#history-table", DataTable)
            table.clear()
            self._commits = commits
            if not commits:
                self.query_one("#history-status", Label).update("No commits yet — sync first.")
                return
            try:
                head_sha = git.repo.head.commit.hexsha
            except Exception:
                head_sha = None
            for c in commits:
                date = c.get("date", "")[:10]
                is_head = c["sha"] == head_sha
                sha_label = c["short_sha"] + (" [HEAD]" if is_head else "")
                title = c.get("title", c["message"])
                title_label = title + (" ← current" if is_head else "")
                table.add_row(sha_label, date, title_label, key=c["sha"])
            self.query_one("#history-status", Label).update(
                f"{len(commits)} commit(s) — R: rollback  X: export"
            )

        self.app.call_from_thread(_populate, commits)

    # ------------------------------------------------------------------ selection / preview

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "history-table":
            return
        row = event.cursor_row
        if 0 <= row < len(self._commits):
            self._update_buttons(True)
            self._load_preview(self._commits[row])
        else:
            self._update_buttons(False)

    def _update_buttons(self, enabled: bool) -> None:
        self.query_one("#rollback-btn", Button).disabled = not enabled
        self.query_one("#export-btn", Button).disabled = not enabled

    @work(thread=True)
    def _load_preview(self, commit: dict) -> None:
        from dnsctl.config import ACCOUNTS_DIR
        from dnsctl.core.git_manager import GitManager
        from dnsctl.core.state_manager import list_synced_zones

        git = GitManager(ACCOUNTS_DIR / self._alias)
        zones = list_synced_zones(self._alias)

        full_msg = commit.get("message", commit.get("title", ""))
        msg_lines = full_msg.split("\n")
        title = msg_lines[0]
        body = "\n".join(msg_lines[1:]).strip()

        lines: list[str] = [
            f"[bold]{commit['short_sha']}[/bold]  "
            f"[dim]{commit['date'][:19].replace('T', ' ')}[/dim]",
            "",
            f"[bold]{title}[/bold]",
        ]
        if body:
            lines.append("")
            for bline in body.split("\n"):
                # Colour-code the change markers
                if bline.startswith("+"):
                    lines.append(f"[green]{bline}[/green]")
                elif bline.startswith("~"):
                    lines.append(f"[yellow]{bline}[/yellow]")
                elif bline.startswith("-"):
                    lines.append(f"[red]{bline}[/red]")
                elif bline.startswith("!"):
                    lines.append(f"[bold red]{bline}[/bold red]")
                else:
                    lines.append(f"[dim]{bline}[/dim]")

        lines += ["", "[dim]── zone snapshot ──[/dim]"]
        found_any = False
        for zone_name in zones:
            content = git.show_file_at(commit["sha"], f"zones/{zone_name}.json")
            if not content:
                continue
            found_any = True
            try:
                data = json.loads(content)
                n = len(data.get("records", []))
                ts = data.get("last_synced_at", "?")[:19].replace("T", " ")
                lines.append(f"[green]{zone_name}[/green]  {n} records  (synced: {ts})")
            except json.JSONDecodeError:
                lines.append(f"[red]{zone_name}[/red]  (parse error)")

        if not found_any:
            lines.append("[dim]No zone files at this commit.[/dim]")

        preview_text = "\n".join(lines)
        self.app.call_from_thread(
            self.query_one("#preview-content", Static).update, preview_text
        )

    # ------------------------------------------------------------------ actions

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "rollback-btn":
            self.action_rollback()
        elif event.button.id == "export-btn":
            self.action_export()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_rollback(self) -> None:
        commit = self._selected_commit()
        if commit is None:
            return
        self._confirm_rollback(commit)

    @work
    async def _confirm_rollback(self, commit: dict) -> None:
        from dnsctl.config import ACCOUNTS_DIR
        from dnsctl.core.git_manager import GitManager
        from dnsctl.tui.screens.confirm import ConfirmScreen

        git = GitManager(ACCOUNTS_DIR / self._alias)
        try:
            head_sha = git.repo.head.commit.hexsha
        except Exception:
            head_sha = None

        if head_sha and commit["sha"] == head_sha:
            self.query_one("#history-status", Label).update(
                f"[yellow]{commit['short_sha']} is the current state — select an older commit to roll back.[/yellow]"
            )
            return

        confirmed = await self.app.push_screen_wait(
            ConfirmScreen(
                f"Roll back to {commit['short_sha']}?\n\n"
                f"\"{commit['message']}\"\n\n"
                "A new commit is created — no history is lost.\n"
                "Run Plan → Apply afterwards to push changes to Cloudflare.",
                confirm_label="Rollback",
            )
        )
        if not confirmed:
            return
        self._do_rollback(commit)

    @work(thread=True)
    def _do_rollback(self, commit: dict) -> None:
        from dnsctl.config import ACCOUNTS_DIR, LOG_FILE
        from dnsctl.core.git_manager import GitManager

        git = GitManager(ACCOUNTS_DIR / self._alias)
        try:
            new_sha = git.rollback(commit["sha"])
        except Exception as exc:
            logger.exception("TUI rollback failed for commit %s", commit["short_sha"])
            self.app.call_from_thread(
                self.query_one("#history-status", Label).update,
                f"[red]Rollback failed: {exc}\nSee log: {LOG_FILE}[/red]",
            )
            return

        if new_sha == commit["sha"]:
            self.app.call_from_thread(
                self.query_one("#history-status", Label).update,
                f"[yellow]Already at {commit['short_sha']} — nothing to roll back.[/yellow]",
            )
            return

        logger.info("TUI rollback complete: new commit %s", new_sha[:8])
        self.app.call_from_thread(
            self.query_one("#history-status", Label).update,
            f"[green]Rolled back to {commit['short_sha']}. New commit: {new_sha[:8]}. "
            "Run Plan → Apply to push to Cloudflare.[/green]",
        )
        self.app.call_from_thread(self._load_history)

    def action_export(self) -> None:
        commit = self._selected_commit()
        if commit is None:
            return
        self._do_export(commit)

    @work(thread=True)
    def _do_export(self, commit: dict) -> None:
        from dnsctl.config import ACCOUNTS_DIR
        from dnsctl.core.git_manager import GitManager
        from dnsctl.core.state_manager import list_synced_zones

        git = GitManager(ACCOUNTS_DIR / self._alias)
        zones = list_synced_zones(self._alias)
        export_data = {}
        for zone_name in zones:
            content = git.show_file_at(commit["sha"], f"zones/{zone_name}.json")
            if content:
                try:
                    export_data[zone_name] = json.loads(content)
                except json.JSONDecodeError:
                    pass

        if not export_data:
            self.app.call_from_thread(
                self.query_one("#history-status", Label).update,
                "[red]No zone data found at this commit.[/red]",
            )
            return

        dest = Path.home() / f"dnsctl-export-{commit['short_sha']}.json"
        dest.write_text(json.dumps(export_data, indent=2), encoding="utf-8")
        self.app.call_from_thread(
            self.query_one("#history-status", Label).update,
            f"[green]Exported {len(export_data)} zone(s) to: {dest}[/green]",
        )

    # ------------------------------------------------------------------ helpers

    def _selected_commit(self) -> dict | None:
        table = self.query_one("#history-table", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._commits):
            return self._commits[row]
        return None
