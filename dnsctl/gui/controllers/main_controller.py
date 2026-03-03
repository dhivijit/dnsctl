"""Main window controller — zone switching, sync, plan/apply, session expiry."""

import logging
from pathlib import Path

from PyQt6.QtCore import QTimer, QThread, pyqtSignal, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QProgressBar

from dnsctl.config import SESSION_TIMEOUT_SECONDS
from dnsctl.core.cloudflare_client import CloudflareClient, CloudflareAPIError
from dnsctl.core.git_manager import GitManager
from dnsctl.core.security import get_token, lock
from dnsctl.core.sync_engine import SyncEngine
from dnsctl.core.state_manager import (
    init_state_dir,
    list_synced_zones,
    load_zone,
    save_zone,
    set_config,
    get_config,
    add_protected_record,
    remove_protected_record,
)
from dnsctl.gui.controllers.plan_controller import PlanController
from dnsctl.gui.controllers.record_controller import RecordController
from dnsctl.gui.controllers.record_editor_controller import RecordEditorController
from dnsctl.gui.controllers.history_controller import HistoryController
from dnsctl.gui import theme as _theme
from dnsctl.gui import icons as _icons

logger = logging.getLogger(__name__)


class SyncWorker(QThread):
    """Background worker for syncing zones from Cloudflare."""
    
    finished = pyqtSignal(bool, str, int)  # success, message, zone_count
    
    def __init__(self, token: str, cf: CloudflareClient, git: GitManager):
        super().__init__()
        self._token = token
        self._cf = cf
        self._git = git
    
    def run(self):
        """Run the sync in a background thread."""
        try:
            zones = self._cf.list_zones(self._token)
            if not zones:
                self.finished.emit(False, "No zones found for this API token.", 0)
                return

            init_state_dir()
            self._git.auto_init()

            for z in zones:
                records = self._cf.list_records(self._token, z["id"])
                save_zone(z["id"], z["name"], records)

            self._git.commit(f"Sync with remote ({len(zones)} zone(s))")

            # Set default zone if not yet set
            cfg = get_config()
            if cfg.get("default_zone") is None:
                set_config("default_zone", zones[0]["name"])

            self.finished.emit(True, f"Synced {len(zones)} zone(s)", len(zones))
        except CloudflareAPIError as exc:
            self.finished.emit(False, f"Sync Error: {exc}", 0)
        except Exception as exc:
            self.finished.emit(False, f"Error: {exc}", 0)


class MainController:
    """Wires the main window widgets to core engine operations."""

    def __init__(self, window: QMainWindow, token: str, theme_mode: str = "dark") -> None:
        self._window = window
        self._token = token
        self._theme_mode = theme_mode
        self._drift_state: str = "unknown"
        self._drift_text: str = "● …"
        self._cf = CloudflareClient()
        self._git = GitManager()
        self._engine = SyncEngine()
        self._record_ctrl: RecordController | None = None
        self._sync_worker: SyncWorker | None = None

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
        w.planButton.clicked.connect(self._on_plan)
        w.historyButton.clicked.connect(self._on_history)
        w.lockButton.clicked.connect(self._on_lock)
        w.addRecordButton.clicked.connect(self._on_add_record)
        w.editRecordButton.clicked.connect(self._on_edit_record)
        w.deleteRecordButton.clicked.connect(self._on_delete_record)
        w.importButton.clicked.connect(self._on_import)
        w.exportButton.clicked.connect(self._on_export)
        w.themeToggleButton.clicked.connect(self._on_toggle_theme)

        # Zone selector
        w.zoneComboBox.currentIndexChanged.connect(self._on_zone_changed)

        # Apply icons to all buttons for the current theme
        self._setup_button_icons()

        # Record controller (read-only table population)
        self._record_ctrl = RecordController(w)

        # Enable edit/delete buttons when a row is selected
        self._record_ctrl.connect_selection_changed(self._on_selection_changed)

        # Double-click a record to open the editor
        self._record_ctrl.connect_double_click(self._on_edit_record)

        # Load cached zones into combo box
        self._populate_zone_combo()

        # Load records for default/first zone
        self._load_current_zone()

        # Start session timer
        self._session_timer.start()

        # Indeterminate progress bar pinned to the right of the status bar
        self._progress = QProgressBar()
        self._progress.setMaximum(0)   # 0 = indeterminate pulsing animation
        self._progress.setFixedWidth(150)
        self._progress.setFixedHeight(16)
        self._progress.setTextVisible(False)
        self._progress.hide()
        w.statusbar.addPermanentWidget(self._progress)

        # Auto-sync on startup (async) - show "Syncing..." status
        w.statusbar.showMessage("Syncing...")
        self._set_drift_badge("unknown", "● …")
        QTimer.singleShot(100, self._on_sync)  # Defer to allow window to show first


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
            self._window.statusbar.showMessage(
                f"{zone_name} — {len(state.get('records', []))} records — last sync: {ts}")

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def _on_sync(self) -> None:
        """Start async sync operation."""
        token = self._ensure_token()
        if token is None:
            return

        # Don't start a new sync if one is already running
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return

        w = self._window
        w.statusbar.showMessage("Syncing…")
        w.syncButton.setEnabled(False)
        self._progress.show()
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))

        # Start background sync
        self._sync_worker = SyncWorker(token, self._cf, self._git)
        self._sync_worker.finished.connect(self._on_sync_finished)
        self._sync_worker.start()

    def _on_sync_finished(self, success: bool, message: str, zone_count: int) -> None:
        """Handle sync completion."""
        w = self._window
        w.syncButton.setEnabled(True)
        self._progress.hide()
        QApplication.restoreOverrideCursor()

        if success:
            self._populate_zone_combo()
            self._load_current_zone()
            w.statusbar.showMessage(f"Ready — {message}")

            # Update drift badge (should be clean right after sync)
            zone_name = w.zoneComboBox.currentText()
            if zone_name:
                self._set_drift_badge("clean", "● Clean")
        else:
            if "No zones found" in message:
                QMessageBox.warning(w, "Sync", message)
            else:
                QMessageBox.critical(w, "Sync Failed", message)
            w.statusbar.showMessage("Ready — Sync failed")

    # ------------------------------------------------------------------
    # Record CRUD
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        has_sel = self._record_ctrl and self._record_ctrl.get_selected_record() is not None
        self._window.editRecordButton.setEnabled(has_sel)
        self._window.deleteRecordButton.setEnabled(has_sel)

    def _current_zone_info(self) -> tuple[str, str] | None:
        """Return (zone_name, zone_id) or None."""
        zone_name = self._window.zoneComboBox.currentText()
        if not zone_name:
            QMessageBox.warning(self._window, "No Zone",
                                "No zone selected. Sync first.")
            return None
        state = load_zone(zone_name)
        if state is None:
            QMessageBox.warning(self._window, "No Zone",
                                "Zone not synced. Sync first.")
            return None
        return zone_name, state["zone_id"]

    def _open_record_editor(self, existing: dict | None = None) -> tuple[dict | None, tuple | None]:
        """Open the record editor dialog. Returns (record, protect_changed) or (None, None)."""
        info = self._current_zone_info()
        if info is None:
            return None, None
        zone_name, _ = info

        from PyQt6 import uic
        dialog = uic.loadUi(
            str(Path(__file__).parent.parent / "ui" / "record_editor.ui"))
        ctrl = RecordEditorController(dialog, zone_name, existing)
        ctrl.setup()
        dialog.exec()
        return ctrl.result, ctrl.protect_changed

    def _on_add_record(self) -> None:
        record, protect_info = self._open_record_editor()
        if record is None:
            return
        self._record_ctrl.add_record(record)
        self._save_current_records()
        self._apply_protect_change(record, protect_info)
        self._window.statusbar.showMessage(
            f"Added {record['type']} {record['name']}")

    def _on_edit_record(self) -> None:
        old = self._record_ctrl.get_selected_record()
        if old is None:
            return
        updated, protect_info = self._open_record_editor(existing=old)
        if updated is None:
            return
        self._record_ctrl.update_record(old, updated)
        self._save_current_records()
        self._apply_protect_change(updated, protect_info)
        self._window.statusbar.showMessage(
            f"Updated {updated['type']} {updated['name']}")

    def _on_delete_record(self) -> None:
        rec = self._record_ctrl.get_selected_record()
        if rec is None:
            return
        answer = QMessageBox.question(
            self._window, "Delete Record",
            f"Delete {rec.get('type')} {rec.get('name')} → {rec.get('content')}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._record_ctrl.delete_record(rec)
        self._save_current_records()
        self._window.editRecordButton.setEnabled(False)
        self._window.deleteRecordButton.setEnabled(False)
        self._window.statusbar.showMessage(
            f"Deleted {rec.get('type')} {rec.get('name')}")

    def _save_current_records(self) -> None:
        """Persist the current in-memory records back to the local zone JSON."""
        info = self._current_zone_info()
        if info is None:
            return
        zone_name, zone_id = info
        records = self._record_ctrl.records
        save_zone(zone_id, zone_name, records)
        self._git.auto_init()
        self._git.commit(f"Local record edit in {zone_name}")
        self._set_drift_badge("local", "● Local changes")

    def _apply_protect_change(self, record: dict, protect_info: tuple | None) -> None:
        """Apply protection state change if the user toggled it in the editor."""
        if protect_info is None:
            return
        was_protected, is_protected, reason = protect_info
        rtype = record.get("type", "")
        rname = record.get("name", "")
        if is_protected and not was_protected:
            add_protected_record(rtype, rname, reason)
            logger.info("Protected %s %s", rtype, rname)
        elif not is_protected and was_protected:
            remove_protected_record(rtype, rname)
            logger.info("Unprotected %s %s", rtype, rname)
        elif is_protected and was_protected:
            # Update reason — remove then re-add
            remove_protected_record(rtype, rname)
            add_protected_record(rtype, rname, reason)
        # Refresh the Protected column in the table
        if self._record_ctrl:
            self._record_ctrl.refresh_protected()

    # ------------------------------------------------------------------
    # Plan / Apply
    # ------------------------------------------------------------------

    def _on_plan(self) -> None:
        """Open the plan preview dialog for the current zone."""
        zone_name = self._window.zoneComboBox.currentText()
        if not zone_name:
            QMessageBox.warning(self._window, "Plan",
                                "No zone selected. Sync first.")
            return

        token = self._ensure_token()
        if token is None:
            return

        from PyQt6 import uic
        dialog = uic.loadUi(
            str(Path(__file__).parent.parent / "ui" / "plan_dialog.ui"))
        ctrl = PlanController(dialog, zone_name, token)
        ctrl.setup()
        dialog.exec()

        # Refresh drift badge + records after dialog closes
        if ctrl.applied:
            self._load_current_zone()
        self._update_drift_badge(zone_name, token)

    def _update_drift_badge(self, zone_name: str, token: str) -> None:
        """Check drift and update the toolbar badge."""
        try:
            drift = self._engine.detect_drift(zone_name, token)
            if drift is None:
                self._set_drift_badge("unknown", "● Unknown")
            elif drift.has_changes:
                self._set_drift_badge("drift", f"● Drift ({drift.summary})")
            else:
                self._set_drift_badge("clean", "● Clean")
        except Exception:
            pass  # don't break UI on drift-check failure

    # ------------------------------------------------------------------
    # History / Rollback
    # ------------------------------------------------------------------

    def _on_history(self) -> None:
        """Open the history/rollback dialog."""
        from PyQt6 import uic
        dialog = uic.loadUi(
            str(Path(__file__).parent.parent / "ui" / "history_dialog.ui"))
        ctrl = HistoryController(dialog)
        ctrl.setup()
        dialog.exec()

        # If a rollback was performed, refresh zone data
        if ctrl.rolled_back:
            self._populate_zone_combo()
            self._load_current_zone()
            self._set_drift_badge("local", "● Local changes")
            self._window.statusbar.showMessage(
                "Rolled back — review with Plan")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _on_export(self) -> None:
        """Export the current zone state to a JSON file."""
        from PyQt6.QtWidgets import QFileDialog
        from dnsctl.core.state_manager import export_zone

        zone_name = self._window.zoneComboBox.currentText()
        if not zone_name:
            QMessageBox.warning(self._window, "Export",
                                "No zone selected. Sync first.")
            return

        dest, _ = QFileDialog.getSaveFileName(
            self._window, "Export Zone State",
            f"{zone_name}.export.json",
            "JSON Files (*.json)",
        )
        if not dest:
            return

        try:
            export_zone(zone_name, Path(dest))
            self._window.statusbar.showMessage(
                f"Exported {zone_name} \u2192 {dest}")
        except FileNotFoundError as exc:
            QMessageBox.critical(self._window, "Export Error", str(exc))

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def _on_import(self) -> None:
        """Import zone state from a JSON file."""
        from PyQt6.QtWidgets import QFileDialog
        from dnsctl.core.state_manager import import_zone

        path, _ = QFileDialog.getOpenFileName(
            self._window, "Import Zone State", "", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            state = import_zone(Path(path))
            zone_name = state["zone_name"]
            n = len(state.get("records", []))
            self._git.auto_init()
            self._git.commit(f"Imported state for {zone_name}")
            self._populate_zone_combo()
            self._window.zoneComboBox.setCurrentText(zone_name)
            self._load_current_zone()
            self._set_drift_badge("local", "● Local changes")
            self._window.statusbar.showMessage(
                f"Imported {zone_name} ({n} records)")
        except ValueError as exc:
            QMessageBox.critical(self._window, "Import Error", str(exc))

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _setup_button_icons(self) -> None:
        """Set icons on all toolbar and CRUD buttons.

        Called once during setup and again after each theme toggle so icons
        re-render with the updated palette colors.
        """
        w = self._window
        colors = _theme.SEMANTIC_COLORS[self._theme_mode]
        accent = _theme.ACCENT_COLOR[self._theme_mode]
        from dnsctl.gui.hover_anim import install_hover_animation
        w.syncButton.setIcon(_icons.get_icon("sync"))
        w.planButton.setIcon(_icons.get_icon("plan"))
        w.historyButton.setIcon(_icons.get_icon("history"))
        w.lockButton.setIcon(_icons.get_icon("lock"))
        w.addRecordButton.setIcon(_icons.get_icon("add"))
        w.editRecordButton.setIcon(_icons.get_icon("edit"))
        w.deleteRecordButton.setIcon(_icons.get_icon("delete", color=colors["danger"]))
        w.importButton.setIcon(_icons.get_icon("import_"))
        w.exportButton.setIcon(_icons.get_icon("export"))
        icon_name = "theme_light" if self._theme_mode == "dark" else "theme_dark"
        w.themeToggleButton.setIcon(_icons.get_icon(icon_name))
        w.themeToggleButton.setToolTip(
            "Switch to light theme" if self._theme_mode == "dark"
            else "Switch to dark theme"
        )
        # Hover glow on all buttons — updates color if already installed
        for btn in (
            w.syncButton, w.planButton, w.historyButton, w.lockButton,
            w.themeToggleButton, w.addRecordButton, w.editRecordButton,
            w.deleteRecordButton, w.importButton, w.exportButton,
        ):
            install_hover_animation(btn, color=accent)

    def _set_drift_badge(self, state: str, text: str) -> None:
        """Set drift badge text and colour using the current theme's semantic tokens.

        Parameters
        ----------
        state:
            One of ``"clean"``, ``"drift"``, ``"local"``, ``"unknown"``.
        text:
            The string displayed in the badge label.
        """
        self._drift_state = state
        self._drift_text = text
        colors = _theme.SEMANTIC_COLORS[self._theme_mode]
        color_map = {
            "clean":   colors["success"],
            "drift":   colors["warning"],
            "local":   colors["info"],
            "unknown": colors["muted"],
        }
        color = color_map.get(state, colors["muted"])
        self._window.driftBadge.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._window.driftBadge.setText(text)

    def _on_toggle_theme(self) -> None:
        """Toggle between dark and light mode, re-render icons and drift badge."""
        app = QApplication.instance()
        self._theme_mode = _theme.toggle_theme(app, self._theme_mode)
        self._setup_button_icons()
        self._set_drift_badge(self._drift_state, self._drift_text)

    # ------------------------------------------------------------------
    # Lock
    # ------------------------------------------------------------------

    def _on_lock(self) -> None:
        lock()
        self._token = ""
        QMessageBox.information(
            self._window, "Locked", "Session locked.  Restart the application to unlock.")
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
