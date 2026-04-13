"""Authentication screens: Login (new account / re-auth) and Unlock."""

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static


class LoginScreen(Screen):
    """Add a new Cloudflare account, or re-authenticate an existing one."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        reauth_alias: str | None = None,
        reuse_password: str | None = None,
    ) -> None:
        super().__init__()
        self._reauth_alias = reauth_alias
        self._reuse_password = reuse_password  # skip password fields when set

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="auth-container"):
            with Vertical(id="auth-form"):
                if self._reauth_alias:
                    yield Static(
                        f"Re-enter credentials for '{self._reauth_alias}'",
                        id="auth-header",
                    )
                elif self._reuse_password is not None:
                    yield Static(
                        "Add account — your existing password will be reused",
                        id="auth-header",
                    )
                else:
                    yield Static("Add your Cloudflare account", id="auth-header")

                if self._reauth_alias is None:
                    yield Label("Account name")
                    yield Input(
                        placeholder="e.g. Personal, Work, Client A",
                        id="name-input",
                    )

                yield Label("Cloudflare API token")
                yield Input(placeholder="Your API token", password=True, id="token-input")

                # Only show password fields when no active session to reuse from
                if self._reuse_password is None:
                    yield Label("Master password")
                    yield Input(placeholder="Min 8 characters", password=True, id="password-input")

                    yield Label("Confirm password")
                    yield Input(placeholder="Repeat password", password=True, id="confirm-input")

                yield Label("", id="error-label", classes="error")

                with Horizontal(id="auth-buttons"):
                    yield Button("Login", variant="primary", id="login-btn")
                    yield Button("Cancel", id="cancel-btn")
        yield Footer()

    # ------------------------------------------------------------------ events

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "login-btn":
            self._do_login()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_login()

    def action_cancel(self) -> None:
        self.dismiss(None)

    # ------------------------------------------------------------------ logic

    def _do_login(self) -> None:
        error = self.query_one("#error-label", Label)

        raw_token = self.query_one("#token-input", Input).value.strip()
        if not raw_token:
            error.update("API token is required.")
            return

        from dnsctl.core.cloudflare_client import sanitize_token

        try:
            token = sanitize_token(raw_token)
        except ValueError as exc:
            error.update(str(exc))
            return

        if self._reuse_password is not None:
            password = self._reuse_password
        else:
            password = self.query_one("#password-input", Input).value
            confirm = self.query_one("#confirm-input", Input).value
            if len(password) < 8:
                error.update("Password must be at least 8 characters.")
                return
            if password != confirm:
                error.update("Passwords do not match.")
                return

        name_label: str
        if self._reauth_alias is None:
            name_label = self.query_one("#name-input", Input).value.strip()
            if not name_label:
                error.update("Account name is required.")
                return
        else:
            name_label = self._reauth_alias

        self.query_one("#login-btn", Button).disabled = True
        error.update("Verifying token with Cloudflare…")
        error.remove_class("error")
        error.add_class("muted")
        self._verify_and_login(token, name_label, password)

    @work(thread=True)
    def _verify_and_login(self, token: str, name_label: str, password: str) -> None:
        def _set_error(msg: str) -> None:
            error = self.query_one("#error-label", Label)
            error.remove_class("muted")
            error.add_class("error")
            error.update(msg)
            self.query_one("#login-btn", Button).disabled = False

        try:
            from dnsctl.core.cloudflare_client import CloudflareClient

            CloudflareClient().verify_token(token)
        except Exception as exc:
            self.app.call_from_thread(_set_error, f"Token verification failed: {exc}")
            return

        try:
            from dnsctl.config import ACCOUNTS_DIR
            from dnsctl.core.git_manager import GitManager
            from dnsctl.core.security import login, unlock
            from dnsctl.core.state_manager import (
                add_account,
                list_accounts,
                set_current_account,
                slugify,
            )

            if self._reauth_alias is None:
                existing = {a["alias"] for a in list_accounts()}
                slug = slugify(name_label)
                base, n = slug, 2
                while slug in existing:
                    slug = f"{base}_{n}"
                    n += 1
                alias = slug
                add_account(alias, name_label)
                set_current_account(alias)
                GitManager(ACCOUNTS_DIR / alias).auto_init()
            else:
                alias = self._reauth_alias

            login(token, password, alias)
            unlock(password, alias)
            # Unlock any other existing accounts with the same password
            other_aliases = [
                a["alias"] for a in list_accounts() if a["alias"] != alias
            ]
            if other_aliases:
                from dnsctl.core.security import unlock_all
                unlock_all(password, other_aliases)
            self.app.call_from_thread(self.dismiss, (alias, token))
        except Exception as exc:
            self.app.call_from_thread(_set_error, f"Login failed: {exc}")


# ---------------------------------------------------------------------------


class UnlockScreen(Screen):
    """Unlock an existing session by entering the master password."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, alias: str, label: str = "") -> None:
        super().__init__()
        self._alias = alias
        self._label = label or alias
        self._confirming_forgot = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="auth-container"):
            with Vertical(id="auth-form"):
                yield Static(
                    f"Enter master password for '{self._label}'",
                    id="auth-header",
                )
                yield Label("Master password")
                yield Input(placeholder="Your master password", password=True, id="password-input")
                yield Label("", id="error-label", classes="error")

                with Horizontal(id="auth-buttons"):
                    yield Button("Unlock", variant="primary", id="unlock-btn")
                    yield Button("Cancel", id="cancel-btn")

                yield Button(
                    "Forgot password",
                    variant="error",
                    id="forgot-btn",
                    classes="forgot-btn",
                )
                yield Label("", id="forgot-warning", classes="warning")
                yield Button(
                    "Yes, delete ALL accounts",
                    variant="error",
                    id="confirm-forgot-btn",
                    classes="hidden",
                )
        yield Footer()

    # ------------------------------------------------------------------ events

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "unlock-btn":
            self._do_unlock()
        elif event.button.id == "forgot-btn":
            self._stage_forgot()
        elif event.button.id == "confirm-forgot-btn":
            self._do_forgot()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_unlock()

    def action_cancel(self) -> None:
        self.dismiss(None)

    # ------------------------------------------------------------------ logic

    def _do_unlock(self) -> None:
        error = self.query_one("#error-label", Label)
        password = self.query_one("#password-input", Input).value
        if not password:
            error.update("Password is required.")
            return
        try:
            from dnsctl.core.security import unlock, unlock_all
            from dnsctl.core.state_manager import list_accounts

            token = unlock(password, self._alias)
            # Unlock all other accounts with the same password in one go
            other_aliases = [
                a["alias"] for a in list_accounts() if a["alias"] != self._alias
            ]
            if other_aliases:
                unlock_all(password, other_aliases)
            self.dismiss(token)
        except Exception:
            error.update("Wrong password.")

    def _stage_forgot(self) -> None:
        """First click — show warning and confirm button."""
        accounts = self._get_all_account_names()
        warning = self.query_one("#forgot-warning", Label)
        warning.update(
            f"This will permanently delete ALL accounts: {accounts}\n"
            "This cannot be undone."
        )
        self.query_one("#confirm-forgot-btn").remove_class("hidden")

    def _do_forgot(self) -> None:
        """Confirmed — wipe all accounts and dismiss with sentinel."""
        from dnsctl.core.security import logout
        from dnsctl.core.state_manager import list_accounts, remove_account

        for account in list_accounts():
            logout(account["alias"])
            try:
                remove_account(account["alias"])
            except Exception:
                pass
        self.dismiss("__forgot__")

    def _get_all_account_names(self) -> str:
        from dnsctl.core.state_manager import list_accounts

        accounts = list_accounts()
        return ", ".join(f"'{a['label']}'" for a in accounts)
