"""Accounts screen — list and switch between Cloudflare accounts."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static


class AccountsScreen(Screen):
    """Shows all stored accounts and allows switching the active one."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("enter", "switch_account", "Switch", priority=True),
        Binding("ctrl+q", "app.quit", "Quit"),
    ]

    def __init__(self, current_alias: str, token: str) -> None:
        super().__init__()
        self._current_alias = current_alias
        self._token = token

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" Accounts", id="accounts-bar")
        yield Label("Enter to switch account  —  Esc to go back", id="accounts-status")
        table = DataTable(id="accounts-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("", "Alias", "Label", "Session")
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self._load_accounts()

    def _load_accounts(self) -> None:
        from dnsctl.core.security import get_token
        from dnsctl.core.state_manager import list_accounts

        table = self.query_one("#accounts-table", DataTable)
        table.clear()
        for account in list_accounts():
            active = "*" if account["alias"] == self._current_alias else ""
            session = "unlocked" if get_token(account["alias"]) else "locked"
            table.add_row(
                active,
                account["alias"],
                account["label"],
                session,
                key=account["alias"],
            )

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_switch_account(self) -> None:
        table = self.query_one("#accounts-table", DataTable)
        if table.cursor_row < 0:
            return
        row = table.get_row_at(table.cursor_row)
        alias = str(row[1])

        if alias == self._current_alias:
            self.app.pop_screen()
            return

        from dnsctl.core.security import get_token
        from dnsctl.core.state_manager import set_current_account

        set_current_account(alias)
        token = get_token(alias)

        if token is None:
            # Session locked — need to unlock first
            from dnsctl.core.state_manager import list_accounts

            accounts = list_accounts()
            label = next((a["label"] for a in accounts if a["alias"] == alias), alias)
            from dnsctl.tui.screens.auth import UnlockScreen

            async def _after_unlock(result) -> None:
                if result and result != "__forgot__":
                    self._relaunch_dashboard(alias, result)
                elif result == "__forgot__":
                    self.app.pop_screen()

            self.app.push_screen(UnlockScreen(alias=alias, label=label), _after_unlock)
        else:
            self._relaunch_dashboard(alias, token)

    def _relaunch_dashboard(self, alias: str, token: str) -> None:
        """Pop back to root and push a fresh dashboard for the new account."""
        from dnsctl.tui.screens.dashboard import DashboardScreen

        # Pop until we reach the bottom of the screen stack (the app root)
        while len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        self.app.push_screen(DashboardScreen(alias=alias, token=token))
