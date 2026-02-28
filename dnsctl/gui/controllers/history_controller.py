"""History dialog controller — browse commits, preview state, rollback."""

import json
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHeaderView,
    QMessageBox,
    QTableWidgetItem,
)

from dnsctl.core.git_manager import GitManager
from dnsctl.core.state_manager import list_synced_zones

logger = logging.getLogger(__name__)


class HistoryController:
    """Drives the history_dialog.ui — commit list, preview, rollback."""

    def __init__(self, dialog: QDialog) -> None:
        self._dialog = dialog
        self._git = GitManager()
        self._commits: list[dict] = []
        self.rolled_back = False  # True if a rollback was performed

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self) -> None:
        d = self._dialog

        # Signals
        d.closeButton.clicked.connect(d.accept)
        d.rollbackButton.clicked.connect(self._on_rollback)
        d.exportButton.clicked.connect(self._on_export)
        d.historyTable.itemSelectionChanged.connect(self._on_selection)

        # Load history
        self._git.auto_init()
        self._commits = self._git.log(max_count=100)
        self._populate_table()

    # ------------------------------------------------------------------
    # Populate commit table
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        table = self._dialog.historyTable
        table.setRowCount(len(self._commits))

        for row, entry in enumerate(self._commits):
            table.setItem(row, 0, QTableWidgetItem(entry["short_sha"]))
            table.setItem(row, 1, QTableWidgetItem(entry["date"][:19].replace("T", " ")))
            table.setItem(row, 2, QTableWidgetItem(entry["message"]))

        # Stretch the message column
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

    # ------------------------------------------------------------------
    # Selection changed — preview
    # ------------------------------------------------------------------

    def _selected_commit(self) -> dict | None:
        rows = self._dialog.historyTable.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._commits):
            return self._commits[row]
        return None

    def _on_selection(self) -> None:
        commit = self._selected_commit()
        has_sel = commit is not None
        self._dialog.rollbackButton.setEnabled(has_sel)
        self._dialog.exportButton.setEnabled(has_sel)

        if commit is None:
            self._dialog.previewBrowser.setHtml("")
            return

        # Build an HTML preview of zone files at this commit
        zones = list_synced_zones()
        html_parts = [f"<h3>Commit {commit['short_sha']}</h3>"]
        html_parts.append(f"<p><b>{commit['message']}</b><br>{commit['date'][:19]}</p>")

        found_any = False
        for zone_name in zones:
            rel = f"zones/{zone_name}.json"
            content = self._git.show_file_at(commit["sha"], rel)
            if content:
                found_any = True
                try:
                    data = json.loads(content)
                    n = len(data.get("records", []))
                    ts = data.get("last_synced_at", "?")[:19]
                    html_parts.append(
                        f"<p><b>{zone_name}</b> — {n} records "
                        f"(synced: {ts})</p>"
                    )
                except json.JSONDecodeError:
                    html_parts.append(f"<p><b>{zone_name}</b> — (parse error)</p>")

        if not found_any:
            html_parts.append("<p><i>No zone files found at this commit.</i></p>")

        self._dialog.previewBrowser.setHtml("\n".join(html_parts))

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def _on_rollback(self) -> None:
        commit = self._selected_commit()
        if commit is None:
            return

        answer = QMessageBox.warning(
            self._dialog,
            "Confirm Rollback",
            f"Roll back state to commit {commit['short_sha']}?\n\n"
            f"\"{commit['message']}\"\n\n"
            "A new commit will be created. No history is lost.\n"
            "Run Plan → Apply afterwards to push changes to Cloudflare.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            new_sha = self._git.rollback(commit["sha"])
            self.rolled_back = True
            QMessageBox.information(
                self._dialog,
                "Rollback Complete",
                f"Rolled back to {commit['short_sha']}.\n"
                f"New commit: {new_sha[:8]}\n\n"
                "Review with Plan, then Apply to update Cloudflare.",
            )
            # Refresh the history list
            self._commits = self._git.log(max_count=100)
            self._populate_table()
        except ValueError as exc:
            QMessageBox.critical(self._dialog, "Rollback Failed", str(exc))

    # ------------------------------------------------------------------
    # Export selected commit's state
    # ------------------------------------------------------------------

    def _on_export(self) -> None:
        commit = self._selected_commit()
        if commit is None:
            return

        zones = list_synced_zones()
        if not zones:
            QMessageBox.warning(self._dialog, "Export", "No zones synced.")
            return

        # For each zone, export the state at this commit
        dest, _ = QFileDialog.getSaveFileName(
            self._dialog,
            "Export State",
            f"dnsctl-{commit['short_sha']}.json",
            "JSON Files (*.json)",
        )
        if not dest:
            return

        export_data = {}
        for zone_name in zones:
            rel = f"zones/{zone_name}.json"
            content = self._git.show_file_at(commit["sha"], rel)
            if content:
                try:
                    export_data[zone_name] = json.loads(content)
                except json.JSONDecodeError:
                    pass

        if not export_data:
            QMessageBox.warning(
                self._dialog, "Export",
                "No zone data found at this commit.",
            )
            return

        Path(dest).write_text(
            json.dumps(export_data, indent=2), encoding="utf-8"
        )
        QMessageBox.information(
            self._dialog, "Export",
            f"Exported {len(export_data)} zone(s) to:\n{dest}",
        )
