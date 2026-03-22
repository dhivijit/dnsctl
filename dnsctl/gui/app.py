"""dnsctl-g — PyQt6 GUI entry point."""

import logging
import platform
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QCursor
from PyQt6.QtWidgets import QApplication
from PyQt6 import uic

from dnsctl.config import LOG_FILE
from dnsctl.core.security import get_token, is_logged_in
from dnsctl.core.state_manager import (
    init_state_dir,
    list_accounts,
    add_account,
    get_current_account,
    set_current_account,
    slugify,
)
from dnsctl.gui import theme as _gui_theme
from dnsctl.gui.controllers.main_controller import MainController

# Detect if running as PyInstaller bundle
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # Running as PyInstaller bundle - resources are in temporary directory
    _BASE_PATH = Path(sys._MEIPASS)
    UI_DIR = _BASE_PATH / "dnsctl" / "gui" / "ui"
    ICON_PATH = _BASE_PATH / "dnsctl" / "icon.png"
else:
    # Running in normal Python environment
    UI_DIR = Path(__file__).parent / "ui"
    ICON_PATH = Path(__file__).parent.parent / "icon.png"


class _VerifyWorker(QThread):
    """Background thread that verifies a Cloudflare API token."""

    finished = pyqtSignal(bool, str)  # success, error_message

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def run(self) -> None:
        try:
            from dnsctl.core.cloudflare_client import CloudflareClient
            cf = CloudflareClient()
            cf.verify_token(self._token)
            self.finished.emit(True, "")
        except Exception as exc:
            self.finished.emit(False, str(exc))


def _set_platform_icon():
    """Set platform-specific icon configurations.
    
    - Windows: Sets AppUserModelID to prevent grouping with python.exe
    - Linux: Icon handled by app.setWindowIcon() and .desktop file (if installed)
    - macOS: Icon handled by app.setWindowIcon() (for .app bundles, use .icns)
    """
    if platform.system() == 'Windows':
        try:
            # On Windows, we need to set the AppUserModelID to prevent
            # the app from being grouped with python.exe in the taskbar
            import ctypes
            myappid = 'dhivijit.dnsctl.gui.1.1.1'  # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass  # Failed to set, continue anyway
    
    # Linux and macOS work out of the box with app.setWindowIcon()
    # For Linux system integration, create a .desktop file with Icon=dnsctl
    # For macOS .app bundles, use an .icns file in the bundle


def _load_ui(name: str):
    """Load a .ui file from the gui/ui/ directory and return the widget."""
    path = UI_DIR / name
    widget = uic.loadUi(str(path))
    # Set icon on all windows/dialogs
    if ICON_PATH.exists():
        widget.setWindowIcon(QIcon(str(ICON_PATH)))
    return widget


def _show_login_dialog(app: QApplication, alias: str | None = None, reuse_password: str | None = None) -> bool:
    """Show the login dialog.  Returns True if login succeeded.

    If *alias* is ``None``, the user fills in an account name which becomes
    the new alias.  If *alias* is provided (re-login), the name field is
    pre-filled and disabled.

    If *reuse_password* is provided, the password fields are hidden and that
    password is used automatically (for adding secondary accounts).
    """
    from dnsctl.core.security import login, unlock
    from dnsctl.core.cloudflare_client import sanitize_token

    dialog = _load_ui("login_dialog.ui")
    colors = _gui_theme.SEMANTIC_COLORS[_gui_theme.load_theme_pref()]
    dialog.errorLabel.setStyleSheet(f"color: {colors['error']};")

    # If re-login for an existing account, lock the name field
    if alias is not None:
        accounts = list_accounts()
        label = next((a["label"] for a in accounts if a["alias"] == alias), alias)
        dialog.accountNameEdit.setText(label)
        dialog.accountNameEdit.setEnabled(False)
        dialog.headerLabel.setText(
            f"Re-enter your Cloudflare API token for account \u2018{label}\u2019."
        )

    # When reusing a password (adding secondary account), hide password rows
    if reuse_password is not None:
        dialog.passwordLabel.hide()
        dialog.passwordEdit.hide()
        dialog.confirmLabel.hide()
        dialog.confirmEdit.hide()
        dialog.headerLabel.setText(
            "Enter a name and your Cloudflare API token.\n"
            "Your existing master password will be used to secure it."
        )
        dialog.adjustSize()

    # Hover glow on dialog buttons
    from dnsctl.gui.hover_anim import install_hover_animation as _ha
    _accent = _gui_theme.ACCENT_COLOR[_gui_theme.load_theme_pref()]
    _ha(dialog.loginButton, color=_accent)
    _ha(dialog.cancelButton, color=_accent)

    def on_help():
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(dialog)
        msg.setWindowTitle("Create an API Token")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(
            '<p>Create a token at:<br>'
            '<a href="https://dash.cloudflare.com/profile/api-tokens">'
            'https://dash.cloudflare.com/profile/api-tokens</a></p>'
            '<p>Use <b>Custom Token</b> with these settings:</p>'
            '<ul>'
            '<li><b>Permissions:</b> Zone &rarr; DNS &rarr; Edit</li>'
            '<li><b>Zone Resources:</b> Include &rarr; All Zones</li>'
            '</ul>'
        )
        msg.exec()

    dialog.helpButton.clicked.connect(on_help)

    def on_login():
        name_label = dialog.accountNameEdit.text().strip()
        raw_token = dialog.tokenEdit.text().strip()

        # --- validate account name (new accounts only) ---
        if alias is None:
            if not name_label:
                dialog.errorLabel.setText("Account name is required.")
                return
            # Slugify and deduplicate
            slug = slugify(name_label)
            existing_aliases = {a["alias"] for a in list_accounts()}
            base = slug
            n = 2
            while slug in existing_aliases:
                slug = f"{base}_{n}"
                n += 1
            account_alias = slug
        else:
            account_alias = alias
            name_label = dialog.accountNameEdit.text().strip()

        # --- validate token / password ---
        if not raw_token:
            dialog.errorLabel.setText("API token is required.")
            return
        try:
            token = sanitize_token(raw_token)
        except ValueError as exc:
            dialog.errorLabel.setText(str(exc))
            return

        # Use the reused password if provided, otherwise read from fields
        password = reuse_password if reuse_password is not None else dialog.passwordEdit.text()

        if reuse_password is None:
            if len(password) < 8:
                dialog.errorLabel.setText("Password must be at least 8 characters.")
                return
            if password != dialog.confirmEdit.text():
                dialog.errorLabel.setText("Passwords do not match.")
                return

        # Verify the token against Cloudflare in a background thread
        dialog.errorLabel.setText("Verifying token with Cloudflare…")
        dialog.errorLabel.setStyleSheet(f"color: {colors['muted']};")
        dialog.loginButton.setEnabled(False)

        worker = _VerifyWorker(token)
        dialog._verify_worker = worker  # keep alive during execution
        dialog._verify_cancelled = False

        def on_verified(success: bool, error: str) -> None:
            QApplication.restoreOverrideCursor()
            if dialog._verify_cancelled:
                return  # dialog was cancelled; ignore the result
            if not success:
                dialog.errorLabel.setStyleSheet(f"color: {colors['error']};")
                dialog.errorLabel.setText(f"Token verification failed: {error}")
                dialog.loginButton.setEnabled(True)
                return
            try:
                if alias is None:
                    add_account(account_alias, name_label)
                    set_current_account(account_alias)
                    # Init per-account git repo
                    from dnsctl.core.git_manager import GitManager
                    from dnsctl.config import ACCOUNTS_DIR
                    GitManager(ACCOUNTS_DIR / account_alias).auto_init()
                login(token, password, account_alias)
                # Start the session immediately so get_token() works right away
                unlock(password, account_alias)
                dialog.accept()
            except Exception as exc:
                dialog.errorLabel.setStyleSheet(f"color: {colors['error']};")
                dialog.errorLabel.setText(f"Login failed: {exc}")
                dialog.loginButton.setEnabled(True)

        def on_cancel() -> None:
            dialog._verify_cancelled = True
            worker.quit()
            dialog.reject()

        worker.finished.connect(on_verified)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        worker.start()

    dialog._verify_cancelled = False  # initialise before any click handler runs

    def _cancel() -> None:
        if hasattr(dialog, "_verify_worker") and dialog._verify_worker is not None:
            dialog._verify_cancelled = True
            dialog._verify_worker.quit()
            QApplication.restoreOverrideCursor()
        dialog.reject()

    dialog.loginButton.clicked.connect(on_login)
    dialog.cancelButton.clicked.connect(_cancel)
    return dialog.exec() == 1  # QDialog.DialogCode.Accepted


_FORGOT_PASSWORD = "__forgot__"


def _show_unlock_dialog(app: QApplication, alias: str = "default", label: str = "") -> str | None:
    """Show the unlock dialog for *alias*.  Returns the token, or None on cancel.

    If the user clicks Forgot Password, stored credentials are wiped and
    the sentinel ``_FORGOT_PASSWORD`` is returned so the caller can show
    the login dialog again.
    """
    from dnsctl.core.security import unlock, logout
    from PyQt6.QtWidgets import QMessageBox

    dialog = _load_ui("unlock_dialog.ui")
    _uc = _gui_theme.SEMANTIC_COLORS[_gui_theme.load_theme_pref()]
    dialog.errorLabel.setStyleSheet(f"color: {_uc['error']};")
    dialog.forgotButton.setStyleSheet(f"color: {_uc['danger']};")

    # Show which account is being unlocked
    account_display = label or alias
    if hasattr(dialog, "headerLabel") and account_display:
        dialog.headerLabel.setText(f"Enter your master password for account \u2018{account_display}\u2019.")

    # Hover glow on dialog buttons
    from dnsctl.gui.hover_anim import install_hover_animation as _ha2
    _accent2 = _gui_theme.ACCENT_COLOR[_gui_theme.load_theme_pref()]
    _ha2(dialog.unlockButton, color=_accent2)
    _ha2(dialog.cancelButton, color=_accent2)
    _ha2(dialog.forgotButton, color=_uc["danger"], blur_end=12)
    result = {"token": None}

    def on_unlock():
        password = dialog.passwordEdit.text()
        if not password:
            dialog.errorLabel.setText("Password is required.")
            return
        try:
            result["token"] = unlock(password, alias)
            from dnsctl.core.security import unlock_all
            from dnsctl.core.state_manager import list_accounts as _list_accts
            other_aliases = [a["alias"] for a in _list_accts() if a["alias"] != alias]
            unlock_all(password, other_aliases)
            dialog.accept()
        except Exception:
            dialog.errorLabel.setText("Wrong password.")

    def on_forgot():
        from dnsctl.core.state_manager import list_accounts as _list_accts, remove_account as _remove_acct
        all_accounts = _list_accts()
        account_names = ", ".join(f"\u2018{a['label']}\u2019" for a in all_accounts)
        confirm = QMessageBox.warning(
            dialog,
            "Forgot Password",
            "This will permanently delete ALL stored accounts and their local zone data.\n\n"
            f"Accounts that will be removed: {account_names}\n\n"
            "You will need to re-add your Cloudflare accounts from scratch.\n"
            "This action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            for account in all_accounts:
                logout(account["alias"])
                try:
                    _remove_acct(account["alias"])
                except Exception:
                    pass
            result["token"] = _FORGOT_PASSWORD
            dialog.accept()

    dialog.unlockButton.clicked.connect(on_unlock)
    dialog.cancelButton.clicked.connect(dialog.reject)
    dialog.forgotButton.clicked.connect(on_forgot)

    if dialog.exec() == 1:
        return result["token"]
    return None



def main() -> None:
    init_state_dir()

    # Set up file logging
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if LOG_FILE.parent.exists():
        handlers.append(logging.FileHandler(str(LOG_FILE), encoding="utf-8"))
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    # Set platform-specific icon configuration (must be before QApplication)
    _set_platform_icon()

    app = QApplication(sys.argv)
    app.setApplicationName("DNSCTL")

    # Apply modern theme before any windows are shown
    _current_theme = _gui_theme.load_theme_pref()
    _gui_theme.apply_theme(app, _current_theme)

    # Set application-wide icon for all windows and taskbar
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    # --- Authentication flow ---
    accounts = list_accounts()
    if not accounts:
        # Fresh install or all accounts removed — add first account
        if not _show_login_dialog(app):
            sys.exit(0)
        accounts = list_accounts()
        if not accounts:
            sys.exit(0)

    alias = get_current_account() or accounts[0]["alias"]
    # Ensure alias is valid (e.g. if config was edited manually)
    if not any(a["alias"] == alias for a in accounts):
        alias = accounts[0]["alias"]
    label = next((a["label"] for a in accounts if a["alias"] == alias), alias)

    if not is_logged_in(alias):
        # Keyring entry missing — force re-login for this account
        if not _show_login_dialog(app, alias=alias):
            sys.exit(0)

    token = get_token(alias)
    if token is None:
        token = _show_unlock_dialog(app, alias=alias, label=label)
        if token is None:
            sys.exit(0)
        if token == _FORGOT_PASSWORD:
            # All accounts wiped — start fresh with a new account
            if not _show_login_dialog(app):
                sys.exit(0)
            accounts = list_accounts()
            if not accounts:
                sys.exit(0)
            alias = accounts[0]["alias"]
            token = get_token(alias)
            if token is None:
                sys.exit(0)

    # --- Main window ---
    window = _load_ui("main_window.ui")
    controller = MainController(window, token, alias=alias, theme_mode=_current_theme)
    controller.setup()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
