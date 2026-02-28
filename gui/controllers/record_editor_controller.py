"""Record editor controller — drives the Add/Edit record dialog."""

import logging
import re

from PyQt6.QtWidgets import QDialog

from config import SUPPORTED_RECORD_TYPES

logger = logging.getLogger(__name__)

# Types that support the Proxied toggle
_PROXY_TYPES = {"A", "AAAA", "CNAME"}
# Types that use the Priority field
_PRIORITY_TYPES = {"MX", "SRV"}

_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)
_IPV6_RE = re.compile(r"^[0-9a-fA-F:]+$")


def validate_record(record: dict) -> str | None:
    """Validate a record dict. Returns an error message, or None if valid."""
    rtype = record.get("type", "")
    name = record.get("name", "").strip()
    content = record.get("content", "").strip()

    if not rtype:
        return "Record type is required."
    if rtype not in SUPPORTED_RECORD_TYPES:
        return f"Unsupported record type: {rtype}"
    if not name:
        return "Name is required."
    if not content:
        return "Content is required."

    if rtype == "A" and not _IPV4_RE.match(content):
        return "A record content must be a valid IPv4 address."
    if rtype == "AAAA" and not _IPV6_RE.match(content):
        return "AAAA record content must be a valid IPv6 address."

    return None


class RecordEditorController:
    """Drives the record editor dialog for add / edit.

    After dialog.exec(), check ``.result`` for the record dict, or
    ``None`` if cancelled.
    """

    def __init__(self, dialog: QDialog, zone_name: str,
                 existing: dict | None = None) -> None:
        self._dialog = dialog
        self._zone_name = zone_name
        self._existing = existing  # None = add, dict = edit
        self._result: dict | None = None

    @property
    def result(self) -> dict | None:
        return self._result

    def setup(self) -> None:
        d = self._dialog

        if self._existing:
            d.setWindowTitle("Edit DNS Record")
        else:
            d.setWindowTitle("Add DNS Record")

        # Wire type-change to show/hide contextual fields
        d.typeCombo.currentTextChanged.connect(self._on_type_changed)
        d.saveButton.clicked.connect(self._on_save)
        d.cancelButton.clicked.connect(d.reject)

        # Pre-populate for edit mode
        if self._existing:
            self._populate_from_record(self._existing)
            # Don't allow changing type when editing
            d.typeCombo.setEnabled(False)
        else:
            self._on_type_changed(d.typeCombo.currentText())

    def _on_type_changed(self, rtype: str) -> None:
        d = self._dialog
        show_proxy = rtype in _PROXY_TYPES
        show_priority = rtype in _PRIORITY_TYPES

        d.proxiedLabel.setVisible(show_proxy)
        d.proxiedCheck.setVisible(show_proxy)
        d.priorityLabel.setVisible(show_priority)
        d.prioritySpin.setVisible(show_priority)

        # Update placeholder hints
        hints = {
            "A": "IPv4 address (e.g. 1.2.3.4)",
            "AAAA": "IPv6 address (e.g. 2001:db8::1)",
            "CNAME": "Target hostname (e.g. other.example.com)",
            "MX": "Mail server (e.g. mail.example.com)",
            "TXT": "Text value (e.g. v=spf1 include:...)",
            "SRV": "Target (e.g. sip.example.com)",
        }
        d.contentEdit.setPlaceholderText(hints.get(rtype, ""))

    def _populate_from_record(self, rec: dict) -> None:
        d = self._dialog
        # Type
        idx = d.typeCombo.findText(rec.get("type", "A"))
        if idx >= 0:
            d.typeCombo.setCurrentIndex(idx)
        self._on_type_changed(rec.get("type", "A"))

        d.nameEdit.setText(rec.get("name", ""))
        d.contentEdit.setText(rec.get("content", ""))
        d.ttlSpin.setValue(rec.get("ttl", 1))
        d.proxiedCheck.setChecked(rec.get("proxied", False))
        d.prioritySpin.setValue(rec.get("priority", 10))

    def _on_save(self) -> None:
        d = self._dialog
        d.errorLabel.setText("")

        rtype = d.typeCombo.currentText()
        name = d.nameEdit.text().strip()
        content = d.contentEdit.text().strip()

        # Auto-append zone name if bare subdomain given
        if name and not name.endswith(self._zone_name):
            if "." not in name or not name.endswith("."):
                name = f"{name}.{self._zone_name}"

        record: dict = {
            "type": rtype,
            "name": name,
            "content": content,
            "ttl": d.ttlSpin.value(),
            "proxied": d.proxiedCheck.isChecked() if rtype in _PROXY_TYPES else False,
        }

        if rtype in _PRIORITY_TYPES:
            record["priority"] = d.prioritySpin.value()

        # Carry forward the Cloudflare record ID for edits
        if self._existing and "id" in self._existing:
            record["id"] = self._existing["id"]

        err = validate_record(record)
        if err:
            d.errorLabel.setText(err)
            return

        self._result = record
        d.accept()
