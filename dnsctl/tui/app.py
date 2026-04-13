"""dnsctl TUI — main Textual application and auth flow."""

from textual import work
from textual.app import App

from dnsctl.core.security import get_token, is_logged_in
from dnsctl.core.state_manager import get_current_account, init_state_dir, list_accounts

_FORGOT = "__forgot__"


class DNSCtlApp(App):
    """Main TUI application."""

    TITLE = "dnsctl"
    SUB_TITLE = "Cloudflare DNS Manager"
    CSS_PATH = "tui.tcss"

    def on_mount(self) -> None:
        self._auth_flow()

    @work
    async def _auth_flow(self) -> None:
        from dnsctl.tui.screens.auth import LoginScreen, UnlockScreen
        from dnsctl.tui.screens.dashboard import DashboardScreen

        init_state_dir()
        accounts = list_accounts()

        if not accounts:
            result = await self.push_screen_wait(LoginScreen())
            if result is None:
                self.exit()
                return
            alias, token = result
        else:
            alias = get_current_account() or accounts[0]["alias"]
            if not any(a["alias"] == alias for a in accounts):
                alias = accounts[0]["alias"]
            label = next((a["label"] for a in accounts if a["alias"] == alias), alias)

            if not is_logged_in(alias):
                # Keyring entry gone — force re-login
                result = await self.push_screen_wait(LoginScreen(reauth_alias=alias))
                if result is None:
                    self.exit()
                    return
                alias, token = result
            else:
                token = get_token(alias)
                if token is None:
                    # Session locked — show unlock dialog
                    result = await self.push_screen_wait(
                        UnlockScreen(alias=alias, label=label)
                    )
                    if result is None:
                        self.exit()
                        return
                    if result == _FORGOT:
                        # All accounts wiped — start fresh
                        result = await self.push_screen_wait(LoginScreen())
                        if result is None:
                            self.exit()
                            return
                        alias, token = result
                    else:
                        token = result

        self.push_screen(DashboardScreen(alias=alias, token=token))


def _setup_logging() -> None:
    """Write dnsctl DEBUG+ to the log file; keep terminal quiet."""
    import logging
    from dnsctl.config import LOG_FILE
    from dnsctl.core.state_manager import init_state_dir

    init_state_dir()  # ensures logs/ directory exists
    handlers: list[logging.Handler] = []
    if LOG_FILE.parent.exists():
        handlers.append(logging.FileHandler(str(LOG_FILE), encoding="utf-8"))
    if handlers:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=handlers,
        )
    logging.getLogger("dnsctl").setLevel(logging.DEBUG)


def run_tui() -> None:
    """Launch the TUI application."""
    _setup_logging()
    DNSCtlApp().run()
