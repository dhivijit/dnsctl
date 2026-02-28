"""dnscli-g — PyQt6 GUI entry point."""

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from PyQt6 import uic

from config import LOG_FILE
from core.security import get_token, is_logged_in
from core.state_manager import init_state_dir
from gui.controllers.main_controller import MainController

UI_DIR = Path(__file__).parent / "ui"


def _load_ui(name: str):
    """Load a .ui file from the gui/ui/ directory and return the widget."""
    path = UI_DIR / name
    return uic.loadUi(str(path))


def _show_login_dialog(app: QApplication) -> bool:
    """Show the login dialog.  Returns True if login succeeded."""
    from core.security import login
    from core.cloudflare_client import CloudflareClient, sanitize_token

    dialog = _load_ui("login_dialog.ui")

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
        raw_token = dialog.tokenEdit.text().strip()
        password = dialog.passwordEdit.text()
        confirm = dialog.confirmEdit.text()

        if not raw_token:
            dialog.errorLabel.setText("API token is required.")
            return

        # Sanitize the pasted token (strip curl commands, Bearer prefix, etc.)
        try:
            token = sanitize_token(raw_token)
        except ValueError as exc:
            dialog.errorLabel.setText(str(exc))
            return

        if len(password) < 8:
            dialog.errorLabel.setText("Password must be at least 8 characters.")
            return
        if password != confirm:
            dialog.errorLabel.setText("Passwords do not match.")
            return

        # Verify the token against Cloudflare
        dialog.errorLabel.setText("Verifying token with Cloudflare…")
        dialog.errorLabel.setStyleSheet("color: gray;")
        dialog.loginButton.setEnabled(False)
        QApplication.processEvents()

        try:
            cf = CloudflareClient()
            cf.verify_token(token)
        except Exception as exc:
            dialog.errorLabel.setStyleSheet("color: red;")
            dialog.errorLabel.setText(f"Token verification failed: {exc}")
            dialog.loginButton.setEnabled(True)
            return

        try:
            login(token, password)
            dialog.accept()
        except Exception as exc:
            dialog.errorLabel.setStyleSheet("color: red;")
            dialog.errorLabel.setText(f"Login failed: {exc}")
            dialog.loginButton.setEnabled(True)

    dialog.loginButton.clicked.connect(on_login)
    dialog.cancelButton.clicked.connect(dialog.reject)
    return dialog.exec() == 1  # QDialog.DialogCode.Accepted


_FORGOT_PASSWORD = "__forgot__"


def _show_unlock_dialog(app: QApplication) -> str | None:
    """Show the unlock dialog.  Returns the token, or None on cancel.

    If the user clicks Forgot Password, stored credentials are wiped and
    the sentinel ``_FORGOT_PASSWORD`` is returned so the caller can show
    the login dialog again.
    """
    from core.security import unlock, logout
    from PyQt6.QtWidgets import QMessageBox

    dialog = _load_ui("unlock_dialog.ui")
    result = {"token": None}

    def on_unlock():
        password = dialog.passwordEdit.text()
        if not password:
            dialog.errorLabel.setText("Password is required.")
            return
        try:
            result["token"] = unlock(password)
            dialog.accept()
        except Exception:
            dialog.errorLabel.setText("Wrong password.")

    def on_forgot():
        confirm = QMessageBox.warning(
            dialog,
            "Forgot Password",
            "This will delete all stored credentials.\n"
            "You will need to re-enter your Cloudflare API token.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            logout()
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

    app = QApplication(sys.argv)
    app.setApplicationName("DNSCTL")

    # --- Authentication flow ---
    if not is_logged_in():
        if not _show_login_dialog(app):
            sys.exit(0)

    # After login or if already logged in, check session
    token = get_token()
    if token is None:
        token = _show_unlock_dialog(app)
        if token is None:
            sys.exit(0)
        if token == _FORGOT_PASSWORD:
            # Credentials wiped — restart with login dialog
            if not _show_login_dialog(app):
                sys.exit(0)
            token = get_token()
            if token is None:
                token = _show_unlock_dialog(app)
                if token is None or token == _FORGOT_PASSWORD:
                    sys.exit(0)

    # --- Main window ---
    window = _load_ui("main_window.ui")
    controller = MainController(window, token)
    controller.setup()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
