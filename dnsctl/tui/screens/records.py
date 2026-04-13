"""Records screen — filterable DNS record table with full CRUD."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static


class RecordsScreen(Screen):
    """Shows all DNS records for a zone with live filtering and add/edit/delete."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("p", "plan", "Plan"),
        Binding("n", "add_record", "Add"),
        Binding("e", "edit_record", "Edit"),
        Binding("d", "delete_record", "Delete"),
        Binding("t", "toggle_protect", "Protect"),
        Binding("ctrl+q", "app.quit", "Quit"),
    ]

    def __init__(self, zone_name: str, alias: str, token: str) -> None:
        super().__init__()
        self._zone_name = zone_name
        self._alias = alias
        self._token = token
        self._all_records: list[dict] = []
        self._displayed_records: list[dict] = []
        self._zone_id: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" Zone: {self._zone_name}", id="records-zone-bar")
        yield Input(placeholder="Filter by type, name, or content…", id="filter-input")
        yield Label("Loading records…", id="records-status")
        table = DataTable(id="records-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Type", "Name", "Content", "TTL", "Proxied", "Protected")
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self._load_records()

    # ------------------------------------------------------------------ filter

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            self._apply_filter(event.value.strip().lower())

    def _apply_filter(self, query: str) -> None:
        table = self.query_one("#records-table", DataTable)
        table.clear()
        from dnsctl.core.state_manager import load_protected_records
        protected_set = {
            (p.get("type", ""), p.get("name", ""))
            for p in load_protected_records()
        }
        matches = (
            self._all_records
            if not query
            else [
                r for r in self._all_records
                if query in r.get("type", "").lower()
                or query in r.get("name", "").lower()
                or query in r.get("content", "").lower()
            ]
        )
        self._displayed_records = list(matches)
        for rec in matches:
            ttl = rec.get("ttl", 1)
            ttl_display = "Auto" if ttl == 1 else str(ttl)
            proxied = "yes" if rec.get("proxied") else ""
            key = (rec.get("type", ""), rec.get("name", ""))
            protected = "\U0001f6e1" if key in protected_set else ""
            table.add_row(
                rec.get("type", ""),
                rec.get("name", ""),
                rec.get("content", ""),
                ttl_display,
                proxied,
                protected,
            )
        status = self.query_one("#records-status", Label)
        if query:
            status.update(f"{len(matches)} of {len(self._all_records)} records match '{query}'")
        else:
            status.update(
                f"{len(self._all_records)} records — "
                "N: add  E: edit  D: delete  T: protect  P: plan  Esc: back"
            )

    # ------------------------------------------------------------------ data load

    @work(thread=True)
    def _load_records(self) -> None:
        from dnsctl.core.state_manager import load_zone

        state = load_zone(self._zone_name, self._alias)

        def _populate(state) -> None:
            status = self.query_one("#records-status", Label)
            if state is None:
                status.update(f"[red]Zone '{self._zone_name}' not synced.[/red]")
                return
            self._zone_id = state.get("zone_id", "")
            self._all_records = sorted(
                state.get("records", []),
                key=lambda r: (r.get("type", ""), r.get("name", "")),
            )
            self._apply_filter(self.query_one("#filter-input", Input).value.strip().lower())

        self.app.call_from_thread(_populate, state)

    # ------------------------------------------------------------------ save helpers

    def _save_zone_and_commit(self, commit_msg: str) -> None:
        """Persist current records to disk and create a git commit."""
        from dnsctl.config import ACCOUNTS_DIR
        from dnsctl.core.git_manager import GitManager
        from dnsctl.core.state_manager import save_zone

        if not self._zone_id:
            return
        save_zone(self._zone_id, self._zone_name, self._all_records, self._alias)
        GitManager(ACCOUNTS_DIR / self._alias).commit(commit_msg)

    def _get_selected_record(self) -> dict | None:
        table = self.query_one("#records-table", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._displayed_records):
            return self._displayed_records[row]
        return None

    def _refresh(self) -> None:
        """Re-sort and re-apply the current filter after a mutation."""
        self._all_records.sort(key=lambda r: (r.get("type", ""), r.get("name", "")))
        self._apply_filter(self.query_one("#filter-input", Input).value.strip().lower())

    # ------------------------------------------------------------------ CRUD actions

    def action_add_record(self) -> None:
        self._open_add_record()

    @work
    async def _open_add_record(self) -> None:
        from dnsctl.tui.screens.record_editor import RecordEditorScreen

        result = await self.app.push_screen_wait(
            RecordEditorScreen(zone_name=self._zone_name)
        )
        if result is None:
            return
        record, protect_changed = result
        self._all_records.append(record)
        self._apply_protect_change(record, protect_changed)
        from dnsctl.core.commit_messages import add_record_message
        self._save_zone_and_commit(add_record_message(record, self._zone_name))
        self._refresh()
        self.query_one("#records-status", Label).update(
            f"[green]Added {record['type']} {record['name']}[/green]"
        )

    def action_edit_record(self) -> None:
        record = self._get_selected_record()
        if record is None:
            self.query_one("#records-status", Label).update("No record selected.")
            return
        self._open_edit_record(record)

    @work
    async def _open_edit_record(self, existing: dict) -> None:
        from dnsctl.tui.screens.record_editor import RecordEditorScreen

        result = await self.app.push_screen_wait(
            RecordEditorScreen(zone_name=self._zone_name, existing=existing)
        )
        if result is None:
            return
        new_record, protect_changed = result
        # Replace the record in the list
        rec_id = existing.get("id")
        rec_key = (existing.get("type", ""), existing.get("name", ""), existing.get("content", ""))
        for i, r in enumerate(self._all_records):
            matched = (
                r is existing
                or (rec_id and r.get("id") == rec_id)
                or (
                    not rec_id
                    and (r.get("type", ""), r.get("name", ""), r.get("content", "")) == rec_key
                )
            )
            if matched:
                self._all_records[i] = new_record
                break
        self._apply_protect_change(new_record, protect_changed)
        from dnsctl.core.commit_messages import edit_record_message
        self._save_zone_and_commit(edit_record_message(existing, new_record, self._zone_name))
        self._refresh()
        self.query_one("#records-status", Label).update(
            f"[green]Updated {new_record['type']} {new_record['name']}[/green]"
        )

    def action_delete_record(self) -> None:
        record = self._get_selected_record()
        if record is None:
            self.query_one("#records-status", Label).update("No record selected.")
            return
        self._confirm_delete(record)

    @work
    async def _confirm_delete(self, record: dict) -> None:
        from dnsctl.tui.screens.confirm import ConfirmScreen

        confirmed = await self.app.push_screen_wait(
            ConfirmScreen(
                f"Delete {record.get('type')} record\n{record.get('name')}\n{record.get('content')}?",
                confirm_label="Delete",
            )
        )
        if not confirmed:
            return
        # Remove from list
        rec_id = record.get("id")
        rec_key = (record.get("type", ""), record.get("name", ""), record.get("content", ""))
        self._all_records = [
            r for r in self._all_records
            if not (
                r is record
                or (rec_id and r.get("id") == rec_id)
                or (
                    not rec_id
                    and (r.get("type", ""), r.get("name", ""), r.get("content", "")) == rec_key
                )
            )
        ]
        from dnsctl.core.commit_messages import delete_record_message
        self._save_zone_and_commit(delete_record_message(record, self._zone_name))
        self._refresh()
        self.query_one("#records-status", Label).update(
            f"[green]Deleted {record.get('type')} {record.get('name')}[/green]"
        )

    def action_toggle_protect(self) -> None:
        record = self._get_selected_record()
        if record is None:
            self.query_one("#records-status", Label).update("No record selected.")
            return
        self._open_protect_toggle(record)

    @work
    async def _open_protect_toggle(self, record: dict) -> None:
        from dnsctl.core.state_manager import (
            add_protected_record,
            load_protected_records,
            remove_protected_record,
        )
        from dnsctl.tui.screens.confirm import ConfirmScreen

        rtype = record.get("type", "")
        rname = record.get("name", "")
        protected = load_protected_records()
        is_protected = any(
            p.get("type") == rtype and p.get("name") == rname for p in protected
        )

        if is_protected:
            confirmed = await self.app.push_screen_wait(
                ConfirmScreen(
                    f"Remove protection from\n{rtype} {rname}?",
                    confirm_label="Remove",
                    confirm_variant="warning",
                )
            )
            if confirmed:
                remove_protected_record(rtype, rname)
                self._refresh()
                self.query_one("#records-status", Label).update(
                    f"[yellow]Protection removed from {rtype} {rname}[/yellow]"
                )
        else:
            from dnsctl.tui.screens.record_editor import RecordEditorScreen
            # Open editor in edit mode just for the protected toggle
            result = await self.app.push_screen_wait(
                RecordEditorScreen(zone_name=self._zone_name, existing=record)
            )
            if result is None:
                return
            new_record, protect_changed = result
            self._apply_protect_change(new_record, protect_changed)
            self._refresh()
            if protect_changed and protect_changed[1]:
                self.query_one("#records-status", Label).update(
                    f"[green]Protected {rtype} {rname}[/green]"
                )

    @staticmethod
    def _apply_protect_change(record: dict, protect_changed: tuple | None) -> None:
        if protect_changed is None:
            return
        was, now, reason = protect_changed
        from dnsctl.core.state_manager import add_protected_record, remove_protected_record

        rtype = record.get("type", "")
        rname = record.get("name", "")
        if now and not was:
            add_protected_record(rtype, rname, reason)
        elif was and not now:
            remove_protected_record(rtype, rname)
        elif now:
            # Refresh reason in case it changed
            remove_protected_record(rtype, rname)
            add_protected_record(rtype, rname, reason)

    # ------------------------------------------------------------------ navigation

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_plan(self) -> None:
        from dnsctl.tui.screens.plan import PlanScreen

        self.app.push_screen(
            PlanScreen(zone_name=self._zone_name, alias=self._alias, token=self._token)
        )
