"""Records screen — filterable DNS record table for a zone."""

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static


class RecordsScreen(Screen):
    """Shows all DNS records for a zone with live filtering."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("p", "plan", "Plan"),
        Binding("ctrl+q", "app.quit", "Quit"),
    ]

    def __init__(self, zone_name: str, alias: str, token: str) -> None:
        super().__init__()
        self._zone_name = zone_name
        self._alias = alias
        self._token = token
        self._all_records: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" Zone: {self._zone_name}", id="records-zone-bar")
        yield Input(placeholder="Filter by type, name, or content…", id="filter-input")
        yield Label("Loading records…", id="records-status")
        table = DataTable(id="records-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Type", "Name", "Content", "TTL", "Proxied")
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
        for rec in matches:
            ttl = rec.get("ttl", 1)
            ttl_display = "Auto" if ttl == 1 else str(ttl)
            proxied = "yes" if rec.get("proxied") else ""
            table.add_row(
                rec.get("type", ""),
                rec.get("name", ""),
                rec.get("content", ""),
                ttl_display,
                proxied,
            )
        status = self.query_one("#records-status", Label)
        if query:
            status.update(f"{len(matches)} of {len(self._all_records)} records match '{query}'")
        else:
            status.update(f"{len(self._all_records)} records — Esc: back  P: plan")

    # ------------------------------------------------------------------ data

    @work(thread=True)
    def _load_records(self) -> None:
        from dnsctl.core.state_manager import load_zone

        state = load_zone(self._zone_name, self._alias)

        def _populate(state) -> None:
            status = self.query_one("#records-status", Label)
            if state is None:
                status.update(f"[red]Zone '{self._zone_name}' not synced.[/red]")
                return
            self._all_records = sorted(
                state.get("records", []),
                key=lambda r: (r.get("type", ""), r.get("name", "")),
            )
            self._apply_filter("")

        self.app.call_from_thread(_populate, state)

    # ------------------------------------------------------------------ actions

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_plan(self) -> None:
        from dnsctl.tui.screens.plan import PlanScreen

        self.app.push_screen(
            PlanScreen(zone_name=self._zone_name, alias=self._alias, token=self._token)
        )
