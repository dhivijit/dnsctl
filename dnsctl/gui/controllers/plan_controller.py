"""Plan controller — generates and displays execution plans in the GUI."""

import html
import logging

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QPalette, QCursor
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from dnsctl.core.sync_engine import SyncEngine, Plan


class _PlanWorker(QThread):
    """Background thread that generates a Plan without blocking the UI."""

    finished = pyqtSignal(object, str)  # plan_or_none, error_str

    def __init__(self, engine: SyncEngine, zone_name: str, token: str) -> None:
        super().__init__()
        self._engine = engine
        self._zone_name = zone_name
        self._token = token

    def run(self) -> None:
        try:
            plan = self._engine.generate_plan(self._zone_name, self._token)
            self.finished.emit(plan, "")
        except Exception as exc:
            self.finished.emit(None, str(exc))


class _ApplyWorker(QThread):
    """Background thread that applies a Plan without blocking the UI."""

    finished = pyqtSignal(object, str)  # result_or_none, error_str

    def __init__(self, engine: SyncEngine, plan, token: str, force: bool) -> None:
        super().__init__()
        self._engine = engine
        self._plan = plan
        self._token = token
        self._force = force

    def run(self) -> None:
        try:
            result = self._engine.apply_plan(self._plan, self._token, force=self._force)
            self.finished.emit(result, "")
        except Exception as exc:
            self.finished.emit(None, str(exc))

logger = logging.getLogger(__name__)


class PlanController:
    """Drives the plan preview dialog.

    Call ``setup()`` after construction — it fetches remote state and
    populates the dialog.  After ``dialog.exec()``, check ``.applied``
    to see whether the user pressed Apply.
    """

    def __init__(self, dialog: QDialog, zone_name: str, token: str, alias: str = "default") -> None:
        self._dialog = dialog
        self._zone_name = zone_name
        self._token = token
        self._engine = SyncEngine(alias=alias)
        self._plan: Plan | None = None
        self._applied = False
        self._worker: _PlanWorker | None = None
        self._apply_worker: _ApplyWorker | None = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def setup(self) -> None:
        d = self._dialog
        d.closeButton.clicked.connect(d.reject)
        d.applyButton.clicked.connect(self._on_apply)
        d.forceApplyButton.clicked.connect(lambda: self._on_apply(force=True))
        d.forceApplyButton.hide()
        d.applyButton.setEnabled(False)

        # Icons and semantic styling
        from dnsctl.gui.icons import get_icon
        from dnsctl.gui.theme import SEMANTIC_COLORS, load_theme_pref
        _colors = SEMANTIC_COLORS[load_theme_pref()]
        d.applyButton.setIcon(get_icon("apply"))
        d.forceApplyButton.setIcon(get_icon("force_apply"))
        d.forceApplyButton.setStyleSheet(f"color: {_colors['danger']};")
        d.closeButton.setIcon(get_icon("close"))
        d.warningLabel.setStyleSheet(f"color: {_colors['warning']}; font-weight: bold;")

        from dnsctl.gui.theme import ACCENT_COLOR
        from dnsctl.gui.hover_anim import install_hover_animation
        _accent = ACCENT_COLOR[load_theme_pref()]
        for btn in (d.applyButton, d.forceApplyButton, d.closeButton):
            install_hover_animation(btn, color=_accent)

        self._start_plan_worker()

    @property
    def applied(self) -> bool:
        return self._applied

    # ------------------------------------------------------------------
    # Plan generation (async)
    # ------------------------------------------------------------------

    def _start_plan_worker(self) -> None:
        d = self._dialog
        d.zoneLabel.setText(f"Zone: {self._zone_name}")
        d.summaryLabel.setText("Fetching remote state…")

        self._worker = _PlanWorker(self._engine, self._zone_name, self._token)
        self._worker.finished.connect(self._on_plan_ready)
        self._worker.start()
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))

    def _on_plan_ready(self, plan, error: str) -> None:
        QApplication.restoreOverrideCursor()
        if error:
            self._dialog.summaryLabel.setText(f"Error: {error}")
            return

        self._plan = plan
        d = self._dialog

        # Summary
        if not plan.has_changes:
            msg = "No local changes to apply."
            if plan.drift and plan.drift.has_changes:
                msg += f"  Drift detected: {plan.drift.summary}"
            d.summaryLabel.setText(msg)
        else:
            d.summaryLabel.setText(f"Plan: {plan.summary}")
            d.applyButton.setEnabled(True)

        # Protected-record warning
        if plan.has_protected:
            n = sum(1 for a in plan.actions if a.protected)
            d.warningLabel.setText(
                f"\u26a0 {n} protected record(s) will be skipped. "
                "Use Force Apply to override."
            )
            d.forceApplyButton.show()
            d.forceApplyButton.setEnabled(True)

        d.planBrowser.setHtml(self._format_plan_html(plan))

    # ------------------------------------------------------------------
    # HTML formatting
    # ------------------------------------------------------------------

    def _is_dark_mode(self) -> bool:
        """Detect if the application is in dark mode."""
        palette = QApplication.palette()
        bg_color = palette.color(QPalette.ColorRole.Window)
        # If background is dark (luminance < 128), we're in dark mode
        return bg_color.lightness() < 128

    @staticmethod
    def _esc(text: str) -> str:
        return html.escape(str(text))

    def _format_plan_html(self, plan: Plan) -> str:
        lines: list[str] = []
        esc = self._esc
        is_dark = self._is_dark_mode()

        # Theme-aware colors from semantic palette
        from dnsctl.gui.theme import SEMANTIC_COLORS
        _colors = SEMANTIC_COLORS["dark" if is_dark else "light"]
        drift_added_color    = _colors["info"]
        drift_modified_color = _colors["warning"]
        drift_removed_color  = _colors["error"]
        action_create_color  = _colors["success"]
        action_update_color  = _colors["warning"]
        action_delete_color  = _colors["danger"]
        protected_color      = _colors["warning"]
        table_header_bg = "#2d2d2d" if is_dark else "#f0f0f0"
        table_row_bg = "transparent"

        # Drift section
        if plan.drift and plan.drift.has_changes:
            drift = plan.drift
            lines.append("<h3>Drift Detected (remote changes since last sync)</h3>")

            if drift.added:
                lines.append(f"<p style='color:{drift_added_color}'><b>Added remotely:</b></p><ul>")
                for r in drift.added:
                    lines.append(
                        f"<li>+ {esc(r.get('type',''))} {esc(r.get('name',''))} "
                        f"&rarr; {esc(r.get('content',''))}</li>"
                    )
                lines.append("</ul>")

            if drift.modified:
                lines.append(f"<p style='color:{drift_modified_color}'><b>Modified remotely:</b></p><ul>")
                for m in drift.modified:
                    b, a = m["before"], m["after"]
                    lines.append(
                        f"<li>~ {esc(b.get('type',''))} {esc(b.get('name',''))}: "
                        f"{esc(b.get('content',''))} &rarr; {esc(a.get('content',''))}</li>"
                    )
                lines.append("</ul>")

            if drift.removed:
                lines.append(f"<p style='color:{drift_removed_color}'><b>Removed remotely:</b></p><ul>")
                for r in drift.removed:
                    lines.append(
                        f"<li>- {esc(r.get('type',''))} {esc(r.get('name',''))} "
                        f"&rarr; {esc(r.get('content',''))}</li>"
                    )
                lines.append("</ul>")

        # Planned actions table
        if plan.actions:
            lines.append("<h3>Planned Actions</h3>")
            lines.append(
                "<table style='border-collapse:collapse;width:100%'>"
                f"<tr style='background:{table_header_bg}'>"
                "<th style='padding:4px 8px;text-align:left'>Action</th>"
                "<th style='padding:4px 8px;text-align:left'>Type</th>"
                "<th style='padding:4px 8px;text-align:left'>Name</th>"
                "<th style='padding:4px 8px;text-align:left'>Content</th>"
                "<th style='padding:4px 8px;text-align:left'>Protected</th>"
                "</tr>"
            )

            _action_colors = {
                "create": action_create_color,
                "update": action_update_color,
                "delete": action_delete_color,
            }
            _symbols = {"create": "+", "update": "~", "delete": "-"}

            for a in plan.actions:
                color = _action_colors.get(a.action, _colors["muted"])
                symbol = _symbols.get(a.action, "?")
                prot = "\u26a0 Yes" if a.protected else ""
                content = esc(a.record.get("content", ""))
                if a.action == "update" and a.before:
                    content = (
                        f"{esc(a.before.get('content', ''))} &rarr; "
                        f"{esc(a.record.get('content', ''))}"
                    )
                lines.append(
                    f"<tr style='background:{table_row_bg}'>"
                    f"<td style='padding:4px 8px;color:{color}'>"
                    f"<b>{symbol} {esc(a.action.upper())}</b></td>"
                    f"<td style='padding:4px 8px'>{esc(a.record.get('type',''))}</td>"
                    f"<td style='padding:4px 8px'>{esc(a.record.get('name',''))}</td>"
                    f"<td style='padding:4px 8px'>{content}</td>"
                    f"<td style='padding:4px 8px;color:{protected_color}'>{prot}</td>"
                    f"</tr>"
                )

            lines.append("</table>")
        elif not (plan.drift and plan.drift.has_changes):
            lines.append("<p><i>Everything is in sync. No actions needed.</i></p>")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Apply handler
    # ------------------------------------------------------------------

    def _on_apply(self, force: bool = False) -> None:
        if self._plan is None or not self._plan.has_changes:
            return

        answer = QMessageBox.question(
            self._dialog,
            "Confirm Apply",
            f"Apply {self._plan.summary} to {self._zone_name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        d = self._dialog
        d.applyButton.setEnabled(False)
        d.forceApplyButton.setEnabled(False)
        d.closeButton.setEnabled(False)
        d.summaryLabel.setText("Applying…")
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))

        self._apply_worker = _ApplyWorker(self._engine, self._plan, self._token, force)
        self._apply_worker.finished.connect(self._on_apply_finished)
        self._apply_worker.start()

    def _on_apply_finished(self, result, error: str) -> None:
        QApplication.restoreOverrideCursor()
        d = self._dialog
        d.closeButton.setEnabled(True)

        if error:
            QMessageBox.critical(d, "Apply Error", error)
            d.applyButton.setEnabled(True)
            d.forceApplyButton.setEnabled(True)
            d.summaryLabel.setText("Apply failed.")
            return

        self._applied = True

        sync_warning = (
            "\n\nWarning: local state could not be refreshed after apply.\n"
            "Run Sync to bring local state up to date."
            if result.sync_failed else ""
        )
        if result.all_succeeded:
            d.summaryLabel.setText(
                f"Applied {len(result.succeeded)} change(s) successfully."
            )
            QMessageBox.information(
                d, "Applied",
                f"All {len(result.succeeded)} change(s) applied successfully.{sync_warning}",
            )
        else:
            msg = (
                f"{len(result.succeeded)} succeeded, "
                f"{len(result.failed)} failed.\n\n"
            )
            for action, err in result.failed:
                msg += (
                    f"  {action.action} {action.record.get('type')} "
                    f"{action.record.get('name')}: {err}\n"
                )
            d.summaryLabel.setText(msg.split("\n")[0])
            QMessageBox.warning(d, "Partial Apply", msg)

        d.applyButton.setEnabled(False)
        d.forceApplyButton.setEnabled(False)
