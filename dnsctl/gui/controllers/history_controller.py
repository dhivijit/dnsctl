"""History dialog controller — browse commits, preview state, rollback."""

import json
import logging
from pathlib import Path

from dnsctl.config import LOG_FILE


def _log_path() -> str:
    return str(LOG_FILE)

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHeaderView,
    QMessageBox,
    QTableWidgetItem,
)

from dnsctl.config import ACCOUNTS_DIR
from dnsctl.core.git_manager import GitManager
from dnsctl.core.state_manager import list_synced_zones

logger = logging.getLogger(__name__)


class HistoryController:
    """Drives the history_dialog.ui — commit list, preview, rollback."""

    def __init__(self, dialog: QDialog, alias: str = "default") -> None:
        self._dialog = dialog
        self._alias = alias
        self._git = GitManager(ACCOUNTS_DIR / alias)
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

        # Icons and semantic styling for destructive action
        from dnsctl.gui.icons import get_icon
        from dnsctl.gui.theme import SEMANTIC_COLORS, load_theme_pref
        _colors = SEMANTIC_COLORS[load_theme_pref()]
        d.closeButton.setIcon(get_icon("close"))
        d.exportButton.setIcon(get_icon("export"))
        d.rollbackButton.setIcon(get_icon("rollback", color=_colors["danger"]))
        d.rollbackButton.setStyleSheet(f"color: {_colors['danger']}; font-weight: bold;")

        from dnsctl.gui.theme import ACCENT_COLOR
        from dnsctl.gui.hover_anim import install_hover_animation
        _accent = ACCENT_COLOR[load_theme_pref()]
        install_hover_animation(d.closeButton, color=_accent)
        install_hover_animation(d.exportButton, color=_accent)
        install_hover_animation(
            d.rollbackButton, color=_colors["danger"], blur_end=20
        )

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

        head_sha = self._git.repo.head.commit.hexsha if self._commits else None

        for row, entry in enumerate(self._commits):
            is_head = entry["sha"] == head_sha
            sha_text = entry["short_sha"] + (" [HEAD]" if is_head else "")
            msg_text = entry["message"] + (" ← current" if is_head else "")
            table.setItem(row, 0, QTableWidgetItem(sha_text))
            table.setItem(row, 1, QTableWidgetItem(entry["date"][:19].replace("T", " ")))
            table.setItem(row, 2, QTableWidgetItem(msg_text))

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
        zones = list_synced_zones(self._alias)
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

        # Guard: rolling back to the current HEAD is a no-op
        if commit["sha"] == self._git.repo.head.commit.hexsha:
            QMessageBox.information(
                self._dialog,
                "Already at this commit",
                f"Commit {commit['short_sha']} is the current state — there is nothing to roll back.\n\n"
                "Select an older commit from the list to restore an earlier state.",
            )
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
        except Exception as exc:
            logger.exception("Rollback failed for commit %s", commit["short_sha"])
            QMessageBox.critical(
                self._dialog,
                "Rollback Failed",
                f"{exc}\n\nCheck the log file for details:\n{_log_path()}",
            )
            return

        if new_sha == commit["sha"]:
            # rollback() returned the target SHA — already at that state
            QMessageBox.information(
                self._dialog,
                "Nothing to Roll Back",
                f"Local state is already identical to commit {commit['short_sha']}.\n"
                "No new commit was needed.",
            )
            return

        self.rolled_back = True
        logger.info("GUI rollback: new commit %s", new_sha[:8])
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

    # ------------------------------------------------------------------
    # Export selected commit's state
    # ------------------------------------------------------------------

    def _on_export(self) -> None:
        commit = self._selected_commit()
        if commit is None:
            return

        zones = list_synced_zones(self._alias)
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
