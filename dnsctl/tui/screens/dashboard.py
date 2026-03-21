"""Dashboard screen — zone list with account info."""

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static


class DashboardScreen(Screen):
    """Main dashboard showing all synced zones."""

    BINDINGS = [
        Binding("enter", "open_records", "Records", priority=True),
        Binding("s", "sync_zone", "Sync"),
        Binding("p", "plan_zone", "Plan"),
        Binding("a", "switch_account", "Accounts"),
        Binding("ctrl+q", "app.quit", "Quit"),
    ]

    def __init__(self, alias: str, token: str) -> None:
        super().__init__()
        self._alias = alias
        self._token = token

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._account_bar_text(), id="account-bar")
        yield Label("Loading zones…", id="status-label")
        table = DataTable(id="zone-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Zone", "Records", "Last Synced", "Drift")
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self._load_zones()

    # ------------------------------------------------------------------ helpers

    def _account_bar_text(self) -> str:
        from dnsctl.core.state_manager import list_accounts

        accounts = list_accounts()
        label = next((a["label"] for a in accounts if a["alias"] == self._alias), self._alias)
        total = len(accounts)
        suffix = f"  ({total} account{'s' if total != 1 else ''})" if total > 1 else ""
        return f" Account: {label} ({self._alias}){suffix}"

    # ------------------------------------------------------------------ data loading

    @work(thread=True)
    def _load_zones(self) -> None:
        from dnsctl.core.state_manager import list_synced_zones, load_zone

        zones = list_synced_zones(self._alias)

        def _populate(zones: list[str]) -> None:
            table = self.query_one("#zone-table", DataTable)
            status = self.query_one("#status-label", Label)
            table.clear()
            if not zones:
                status.update(
                    "No zones synced. Run [bold]dnsctl sync[/bold] first, "
                    "or press [bold]S[/bold] to sync from Cloudflare."
                )
                return
            status.update(f"{len(zones)} zone(s) — Enter to view records, S to sync")
            for zone_name in zones:
                state = load_zone(zone_name, self._alias)
                if state is None:
                    continue
                n_records = len(state.get("records", []))
                last_synced = state.get("last_synced_at", "never")
                if last_synced and last_synced != "never":
                    # Trim to seconds-precision
                    last_synced = last_synced[:19].replace("T", " ")
                table.add_row(zone_name, str(n_records), last_synced, "—", key=zone_name)

        self.app.call_from_thread(_populate, zones)

    # ------------------------------------------------------------------ drift detection

    @work(thread=True)
    def _check_drift(self, zone_name: str, row_key: str) -> None:
        """Async drift check — updates the Drift column when done."""
        try:
            from dnsctl.core.sync_engine import SyncEngine

            engine = SyncEngine(alias=self._alias)
            drift = engine.detect_drift(zone_name, self._token)
        except Exception:
            drift = None

        def _update(drift) -> None:
            table = self.query_one("#zone-table", DataTable)
            if drift is None:
                badge = "[dim]error[/dim]"
            elif drift.has_changes:
                badge = f"[yellow]{drift.summary}[/yellow]"
            else:
                badge = "[green]clean[/green]"
            # Find the row and update the Drift cell
            for row in table.rows:
                if row == row_key:
                    table.update_cell(row_key, "Drift", badge)
                    break

        self.app.call_from_thread(_update, drift)

    # ------------------------------------------------------------------ actions

    def action_open_records(self) -> None:
        table = self.query_one("#zone-table", DataTable)
        if table.cursor_row < 0:
            return
        row_key = table.get_row_at(table.cursor_row)
        zone_name = str(row_key[0])
        from dnsctl.tui.screens.records import RecordsScreen

        self.app.push_screen(RecordsScreen(zone_name=zone_name, alias=self._alias, token=self._token))

    def action_sync_zone(self) -> None:
        table = self.query_one("#zone-table", DataTable)
        status = self.query_one("#status-label", Label)
        if table.row_count == 0:
            self._sync_all(status)
            return
        row_key = table.get_row_at(table.cursor_row)
        zone_name = str(row_key[0])
        status.update(f"Syncing {zone_name}…")
        self._sync_single(zone_name, status)

    @work(thread=True)
    def _sync_all(self, status: Label) -> None:
        self.app.call_from_thread(status.update, "Syncing all zones from Cloudflare…")
        try:
            from dnsctl.core.cloudflare_client import CloudflareClient
            from dnsctl.core.git_manager import GitManager
            from dnsctl.core.state_manager import save_zone
            from dnsctl.config import ACCOUNTS_DIR

            cf = CloudflareClient()
            zones = cf.list_zones(self._token)
            for z in zones:
                records = cf.list_records(self._token, z["id"])
                save_zone(z["id"], z["name"], records, self._alias)
            GitManager(ACCOUNTS_DIR / self._alias).commit(f"Sync ({len(zones)} zones)")
            self.app.call_from_thread(status.update, f"Synced {len(zones)} zone(s).")
            self.app.call_from_thread(self._load_zones)
        except Exception as exc:
            self.app.call_from_thread(status.update, f"[red]Sync failed: {exc}[/red]")

    @work(thread=True)
    def _sync_single(self, zone_name: str, status: Label) -> None:
        try:
            from dnsctl.core.cloudflare_client import CloudflareClient
            from dnsctl.core.git_manager import GitManager
            from dnsctl.core.state_manager import save_zone
            from dnsctl.config import ACCOUNTS_DIR

            cf = CloudflareClient()
            zones = cf.list_zones(self._token)
            target = next((z for z in zones if z["name"] == zone_name), None)
            if target is None:
                self.app.call_from_thread(status.update, f"[red]Zone '{zone_name}' not found in Cloudflare.[/red]")
                return
            records = cf.list_records(self._token, target["id"])
            save_zone(target["id"], zone_name, records, self._alias)
            GitManager(ACCOUNTS_DIR / self._alias).commit(f"Sync {zone_name}")
            self.app.call_from_thread(status.update, f"Synced {zone_name} ({len(records)} records).")
            self.app.call_from_thread(self._load_zones)
        except Exception as exc:
            self.app.call_from_thread(status.update, f"[red]Sync failed: {exc}[/red]")

    def action_plan_zone(self) -> None:
        table = self.query_one("#zone-table", DataTable)
        if table.cursor_row < 0:
            return
        row_key = table.get_row_at(table.cursor_row)
        zone_name = str(row_key[0])
        from dnsctl.tui.screens.plan import PlanScreen

        self.app.push_screen(PlanScreen(zone_name=zone_name, alias=self._alias, token=self._token))

    def action_switch_account(self) -> None:
        from dnsctl.tui.screens.accounts import AccountsScreen

        self.app.push_screen(AccountsScreen(current_alias=self._alias, token=self._token))
