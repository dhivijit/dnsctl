"""Plan controller — generates and displays execution plans in the GUI."""

import html
import logging

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from dnsctl.core.sync_engine import SyncEngine, Plan

logger = logging.getLogger(__name__)


class PlanController:
    """Drives the plan preview dialog.

    Call ``setup()`` after construction — it fetches remote state and
    populates the dialog.  After ``dialog.exec()``, check ``.applied``
    to see whether the user pressed Apply.
    """

    def __init__(self, dialog: QDialog, zone_name: str, token: str) -> None:
        self._dialog = dialog
        self._zone_name = zone_name
        self._token = token
        self._engine = SyncEngine()
        self._plan: Plan | None = None
        self._applied = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def setup(self) -> None:
        d = self._dialog
        d.closeButton.clicked.connect(d.reject)
        d.applyButton.clicked.connect(self._on_apply)
        d.forceApplyButton.clicked.connect(lambda: self._on_apply(force=True))
        d.forceApplyButton.hide()

        self._generate_plan()

    @property
    def applied(self) -> bool:
        return self._applied

    # ------------------------------------------------------------------
    # Plan generation
    # ------------------------------------------------------------------

    def _generate_plan(self) -> None:
        d = self._dialog
        d.zoneLabel.setText(f"Zone: {self._zone_name}")
        d.summaryLabel.setText("Fetching remote state…")
        QApplication.processEvents()

        try:
            self._plan = self._engine.generate_plan(self._zone_name, self._token)
        except Exception as exc:
            d.summaryLabel.setText(f"Error: {exc}")
            return

        plan = self._plan

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

    @staticmethod
    def _esc(text: str) -> str:
        return html.escape(str(text))

    def _format_plan_html(self, plan: Plan) -> str:
        lines: list[str] = []
        esc = self._esc

        # Drift section
        if plan.drift and plan.drift.has_changes:
            drift = plan.drift
            lines.append("<h3>Drift Detected (remote changes since last sync)</h3>")

            if drift.added:
                lines.append("<p style='color:#2196F3'><b>Added remotely:</b></p><ul>")
                for r in drift.added:
                    lines.append(
                        f"<li>+ {esc(r.get('type',''))} {esc(r.get('name',''))} "
                        f"&rarr; {esc(r.get('content',''))}</li>"
                    )
                lines.append("</ul>")

            if drift.modified:
                lines.append("<p style='color:#FF9800'><b>Modified remotely:</b></p><ul>")
                for m in drift.modified:
                    b, a = m["before"], m["after"]
                    lines.append(
                        f"<li>~ {esc(b.get('type',''))} {esc(b.get('name',''))}: "
                        f"{esc(b.get('content',''))} &rarr; {esc(a.get('content',''))}</li>"
                    )
                lines.append("</ul>")

            if drift.removed:
                lines.append("<p style='color:#F44336'><b>Removed remotely:</b></p><ul>")
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
                "<tr style='background:#f0f0f0'>"
                "<th style='padding:4px 8px;text-align:left'>Action</th>"
                "<th style='padding:4px 8px;text-align:left'>Type</th>"
                "<th style='padding:4px 8px;text-align:left'>Name</th>"
                "<th style='padding:4px 8px;text-align:left'>Content</th>"
                "<th style='padding:4px 8px;text-align:left'>Protected</th>"
                "</tr>"
            )

            _colors = {"create": "#4CAF50", "update": "#FF9800", "delete": "#F44336"}
            _symbols = {"create": "+", "update": "~", "delete": "-"}

            for a in plan.actions:
                color = _colors.get(a.action, "#000")
                symbol = _symbols.get(a.action, "?")
                prot = "\u26a0 Yes" if a.protected else ""
                content = esc(a.record.get("content", ""))
                if a.action == "update" and a.before:
                    content = (
                        f"{esc(a.before.get('content', ''))} &rarr; "
                        f"{esc(a.record.get('content', ''))}"
                    )
                lines.append(
                    f"<tr>"
                    f"<td style='padding:4px 8px;color:{color}'>"
                    f"<b>{symbol} {esc(a.action.upper())}</b></td>"
                    f"<td style='padding:4px 8px'>{esc(a.record.get('type',''))}</td>"
                    f"<td style='padding:4px 8px'>{esc(a.record.get('name',''))}</td>"
                    f"<td style='padding:4px 8px'>{content}</td>"
                    f"<td style='padding:4px 8px;color:orange'>{prot}</td>"
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
        d.summaryLabel.setText("Applying…")
        QApplication.processEvents()

        try:
            result = self._engine.apply_plan(self._plan, self._token, force=force)
        except Exception as exc:
            QMessageBox.critical(d, "Apply Error", str(exc))
            d.applyButton.setEnabled(True)
            d.forceApplyButton.setEnabled(True)
            return

        self._applied = True

        if result.all_succeeded:
            d.summaryLabel.setText(
                f"Applied {len(result.succeeded)} change(s) successfully."
            )
            QMessageBox.information(
                d, "Applied",
                f"All {len(result.succeeded)} change(s) applied successfully.",
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
