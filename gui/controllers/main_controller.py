"""Main window controller — zone switching, sync, session expiry."""

import logging
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMainWindow, QMessageBox

from config import SESSION_TIMEOUT_SECONDS
from core.cloudflare_client import CloudflareClient, CloudflareAPIError
from core.git_manager import GitManager
from core.security import get_token, lock
from core.state_manager import (
    init_state_dir,
    list_synced_zones,
    load_zone,
    save_zone,
    set_config,
    get_config,
)
from gui.controllers.record_controller import RecordController

logger = logging.getLogger(__name__)


class MainController:
    """Wires the main window widgets to core engine operations."""

    def __init__(self, window: QMainWindow, token: str) -> None:
        self._window = window
        self._token = token
        self._cf = CloudflareClient()
        self._git = GitManager()
        self._record_ctrl: RecordController | None = None

        # Session expiry timer — check every 60 seconds
        self._session_timer = QTimer()
        self._session_timer.setInterval(60_000)
        self._session_timer.timeout.connect(self._check_session)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Connect signals and populate initial data."""
        w = self._window

        # Buttons
        w.syncButton.clicked.connect(self._on_sync)
        w.lockButton.clicked.connect(self._on_lock)

        # Zone selector
        w.zoneComboBox.currentIndexChanged.connect(self._on_zone_changed)

        # Record controller (read-only table population)
        self._record_ctrl = RecordController(w)

        # Load cached zones into combo box
        self._populate_zone_combo()

        # Load records for default/first zone
        self._load_current_zone()

        # Start session timer
        self._session_timer.start()

        w.statusbar.showMessage("Ready")

    # ------------------------------------------------------------------
    # Zone combo population
    # ------------------------------------------------------------------

    def _populate_zone_combo(self) -> None:
        w = self._window
        w.zoneComboBox.blockSignals(True)
        w.zoneComboBox.clear()

        synced = list_synced_zones()
        for name in synced:
            w.zoneComboBox.addItem(name)

        # Select default zone if configured
        cfg = get_config()
        default = cfg.get("default_zone")
        if default and default in synced:
            w.zoneComboBox.setCurrentText(default)

        w.zoneComboBox.blockSignals(False)

    # ------------------------------------------------------------------
    # Zone switching
    # ------------------------------------------------------------------

    def _on_zone_changed(self, index: int) -> None:
        if index < 0:
            return
        self._load_current_zone()

    def _load_current_zone(self) -> None:
        zone_name = self._window.zoneComboBox.currentText()
        if not zone_name:
            return
        state = load_zone(zone_name)
        if state and self._record_ctrl:
            self._record_ctrl.populate(state.get("records", []))
            ts = state.get("last_synced_at", "never")
            self._window.statusbar.showMessage(f"{zone_name} — {len(state.get('records', []))} records — last sync: {ts}")

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def _on_sync(self) -> None:
        token = self._ensure_token()
        if token is None:
            return

        w = self._window
        w.statusbar.showMessage("Syncing…")
        w.syncButton.setEnabled(False)

        try:
            zones = self._cf.list_zones(token)
            if not zones:
                QMessageBox.warning(w, "Sync", "No zones found for this API token.")
                return

            init_state_dir()
            self._git.auto_init()

            for z in zones:
                records = self._cf.list_records(token, z["id"])
                save_zone(z["id"], z["name"], records)

            self._git.commit(f"Sync with remote ({len(zones)} zone(s))")

            # Set default zone if not yet set
            cfg = get_config()
            if cfg.get("default_zone") is None:
                set_config("default_zone", zones[0]["name"])

            self._populate_zone_combo()
            self._load_current_zone()
            w.statusbar.showMessage(f"Synced {len(zones)} zone(s)")

        except CloudflareAPIError as exc:
            QMessageBox.critical(w, "Sync Error", str(exc))
            w.statusbar.showMessage("Sync failed")
        except Exception as exc:
            QMessageBox.critical(w, "Error", str(exc))
            w.statusbar.showMessage("Sync failed")
        finally:
            w.syncButton.setEnabled(True)

    # ------------------------------------------------------------------
    # Lock
    # ------------------------------------------------------------------

    def _on_lock(self) -> None:
        lock()
        self._token = ""
        QMessageBox.information(self._window, "Locked", "Session locked.  Restart the application to unlock.")
        self._window.close()

    # ------------------------------------------------------------------
    # Session check
    # ------------------------------------------------------------------

    def _check_session(self) -> None:
        if get_token() is None:
            self._session_timer.stop()
            QMessageBox.warning(
                self._window,
                "Session Expired",
                "Your session has expired.  Restart the application to unlock.",
            )
            self._window.close()

    def _ensure_token(self) -> str | None:
        """Return the current token if the session is valid, else show a warning."""
        token = get_token()
        if token is None:
            QMessageBox.warning(
                self._window,
                "Session Expired",
                "Your session has expired.  Restart the application to unlock.",
            )
            return None
        self._token = token
        return token
