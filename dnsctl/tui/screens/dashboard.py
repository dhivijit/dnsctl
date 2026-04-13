"""Dashboard screen — zone list with sync, plan, history, and session management."""

import time

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static

from dnsctl.config import SESSION_TIMEOUT_SECONDS


class DashboardScreen(Screen):
    """Main dashboard showing all synced zones."""

    BINDINGS = [
        Binding("enter", "open_records", "Records", priority=True),
        Binding("s", "sync_zone", "Sync"),
        Binding("p", "plan_zone", "Plan"),
        Binding("h", "open_history", "History"),
        Binding("i", "import_zone", "Import"),
        Binding("a", "switch_account", "Accounts"),
        Binding("ctrl+l", "lock_session", "Lock"),
        Binding("ctrl+q", "app.quit", "Quit"),
    ]

    def __init__(self, alias: str, token: str) -> None:
        super().__init__()
        self._alias = alias
        self._token = token
        self._last_activity = time.monotonic()
        self._session_timer = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._account_bar_text(), id="account-bar")
        yield Label("Loading zones…", id="status-label")
        table = DataTable(id="zone-table", cursor_type="row", zebra_stripes=True)
        table.add_column("Zone", key="zone")
        table.add_column("Records", key="records")
        table.add_column("Last Synced", key="synced")
        table.add_column("Drift", key="drift")
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self._load_zones()
        self._session_timer = self.set_interval(60.0, self._check_session)

    # ------------------------------------------------------------------ activity tracking

    def on_key(self, event) -> None:
        self._last_activity = time.monotonic()

    # ------------------------------------------------------------------ session management

    def _check_session(self) -> None:
        if time.monotonic() - self._last_activity > SESSION_TIMEOUT_SECONDS:
            self._expire_session()

    def _expire_session(self) -> None:
        if self._session_timer:
            self._session_timer.stop()
        from dnsctl.core.security import lock
        lock(self._alias)
        self._open_unlock_after_lock()

    def action_lock_session(self) -> None:
        if self._session_timer:
            self._session_timer.stop()
        from dnsctl.core.security import lock
        lock(self._alias)
        self._open_unlock_after_lock()

    @work
    async def _open_unlock_after_lock(self) -> None:
        from dnsctl.tui.screens.auth import LoginScreen, UnlockScreen
        from dnsctl.core.state_manager import list_accounts

        accounts = list_accounts()
        label = next(
            (a["label"] for a in accounts if a["alias"] == self._alias), self._alias
        )
        result = await self.app.push_screen_wait(
            UnlockScreen(alias=self._alias, label=label)
        )
        if result is None:
            self.app.exit()
            return
        if result == "__forgot__":
            result = await self.app.push_screen_wait(LoginScreen())
            if result is None:
                self.app.exit()
                return
            self._alias, self._token = result
        else:
            self._token = result

        self._last_activity = time.monotonic()
        self._session_timer = self.set_interval(60.0, self._check_session)
        self.query_one("#account-bar", Static).update(self._account_bar_text())
        self._load_zones()

    # ------------------------------------------------------------------ helpers

    def _account_bar_text(self) -> str:
        from dnsctl.core.state_manager import list_accounts

        accounts = list_accounts()
        label = next(
            (a["label"] for a in accounts if a["alias"] == self._alias), self._alias
        )
        total = len(accounts)
        suffix = f"  ({total} account{'s' if total != 1 else ''})" if total > 1 else ""
        return f" Account: {label} ({self._alias}){suffix}  — Ctrl+L to lock"

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
                    "No zones synced. Press [bold]S[/bold] to sync from Cloudflare."
                )
                return
            status.update(f"{len(zones)} zone(s) — Enter: records  S: sync  P: plan  H: history")
            for zone_name in zones:
                state = load_zone(zone_name, self._alias)
                if state is None:
                    continue
                n_records = len(state.get("records", []))
                last_synced = state.get("last_synced_at", "never")
                if last_synced and last_synced != "never":
                    last_synced = last_synced[:19].replace("T", " ")
                table.add_row(zone_name, str(n_records), last_synced, "[dim]…[/dim]", key=zone_name)
                self._check_drift(zone_name, zone_name)

        self.app.call_from_thread(_populate, zones)

    # ------------------------------------------------------------------ drift detection

    @work(thread=True)
    def _check_drift(self, zone_name: str, row_key: str) -> None:
        try:
            from dnsctl.core.sync_engine import SyncEngine

            engine = SyncEngine(alias=self._alias)
            drift = engine.detect_drift(zone_name, self._token)
        except Exception:
            drift = None

        def _update(drift) -> None:
            table = self.query_one("#zone-table", DataTable)
            if row_key not in table.rows:
                return
            if drift is None:
                badge = "[dim]error[/dim]"
            elif drift.has_changes:
                badge = f"[yellow]{drift.summary}[/yellow]"
            else:
                badge = "[green]clean[/green]"
            table.update_cell(row_key, "drift", badge)

        self.app.call_from_thread(_update, drift)

    # ------------------------------------------------------------------ actions

    def action_open_records(self) -> None:
        self._last_activity = time.monotonic()
        table = self.query_one("#zone-table", DataTable)
        if table.cursor_row < 0:
            return
        row_key = table.get_row_at(table.cursor_row)
        zone_name = str(row_key[0])
        from dnsctl.tui.screens.records import RecordsScreen

        self.app.push_screen(
            RecordsScreen(zone_name=zone_name, alias=self._alias, token=self._token)
        )

    def action_sync_zone(self) -> None:
        self._last_activity = time.monotonic()
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
            from dnsctl.config import ACCOUNTS_DIR
            from dnsctl.core.cloudflare_client import CloudflareClient
            from dnsctl.core.commit_messages import sync_message
            from dnsctl.core.git_manager import GitManager
            from dnsctl.core.state_manager import save_zone

            cf = CloudflareClient()
            zones = cf.list_zones(self._token)
            synced: list[tuple[str, int]] = []
            for z in zones:
                records = cf.list_records(self._token, z["id"])
                save_zone(z["id"], z["name"], records, self._alias)
                synced.append((z["name"], len(records)))

            GitManager(ACCOUNTS_DIR / self._alias).commit(sync_message(synced))
            self.app.call_from_thread(status.update, f"Synced {len(synced)} zone(s).")
            self.app.call_from_thread(self._load_zones)
        except Exception as exc:
            self.app.call_from_thread(status.update, f"[red]Sync failed: {exc}[/red]")

    @work(thread=True)
    def _sync_single(self, zone_name: str, status: Label) -> None:
        try:
            from dnsctl.config import ACCOUNTS_DIR
            from dnsctl.core.cloudflare_client import CloudflareClient
            from dnsctl.core.commit_messages import sync_message
            from dnsctl.core.git_manager import GitManager
            from dnsctl.core.state_manager import save_zone

            cf = CloudflareClient()
            zones = cf.list_zones(self._token)
            target = next((z for z in zones if z["name"] == zone_name), None)
            if target is None:
                self.app.call_from_thread(
                    status.update, f"[red]Zone '{zone_name}' not found in Cloudflare.[/red]"
                )
                return
            records = cf.list_records(self._token, target["id"])
            save_zone(target["id"], zone_name, records, self._alias)
            GitManager(ACCOUNTS_DIR / self._alias).commit(
                sync_message([(zone_name, len(records))])
            )
            self.app.call_from_thread(
                status.update, f"Synced {zone_name} ({len(records)} records)."
            )
            self.app.call_from_thread(self._load_zones)
        except Exception as exc:
            self.app.call_from_thread(status.update, f"[red]Sync failed: {exc}[/red]")

    def action_plan_zone(self) -> None:
        self._last_activity = time.monotonic()
        table = self.query_one("#zone-table", DataTable)
        if table.cursor_row < 0:
            return
        row_key = table.get_row_at(table.cursor_row)
        zone_name = str(row_key[0])
        from dnsctl.tui.screens.plan import PlanScreen

        self.app.push_screen(
            PlanScreen(zone_name=zone_name, alias=self._alias, token=self._token)
        )

    def action_open_history(self) -> None:
        self._last_activity = time.monotonic()
        from dnsctl.tui.screens.history import HistoryScreen

        self.app.push_screen(HistoryScreen(alias=self._alias))

    def action_import_zone(self) -> None:
        self._last_activity = time.monotonic()
        self._run_import()

    @work
    async def _run_import(self) -> None:
        from dnsctl.tui.screens.input_modal import InputScreen

        path_str = await self.app.push_screen_wait(
            InputScreen(
                prompt="Enter the path to the JSON file to import:",
                placeholder="/path/to/zone-export.json",
                confirm_label="Import",
            )
        )
        if not path_str:
            return

        status = self.query_one("#status-label", Label)
        self._do_import(path_str, status)

    @work(thread=True)
    def _do_import(self, path_str: str, status) -> None:
        from pathlib import Path

        from dnsctl.config import ACCOUNTS_DIR
        from dnsctl.core.commit_messages import import_message
        from dnsctl.core.git_manager import GitManager
        from dnsctl.core.state_manager import import_zone

        src = Path(path_str)
        if not src.exists():
            self.app.call_from_thread(
                status.update, f"[red]File not found: {path_str}[/red]"
            )
            return

        try:
            state = import_zone(src, self._alias)
            zone_name = state["zone_name"]
            n = len(state.get("records", []))
            GitManager(ACCOUNTS_DIR / self._alias).commit(import_message(zone_name, n))
            self.app.call_from_thread(
                status.update,
                f"[green]Imported {zone_name} ({n} records). Press S to sync to Cloudflare.[/green]",
            )
            self.app.call_from_thread(self._load_zones)
        except ValueError as exc:
            self.app.call_from_thread(
                status.update, f"[red]Import failed: {exc}[/red]"
            )

    def action_switch_account(self) -> None:
        self._last_activity = time.monotonic()
        from dnsctl.tui.screens.accounts import AccountsScreen

        self.app.push_screen(AccountsScreen(current_alias=self._alias, token=self._token))
