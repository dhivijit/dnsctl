"""Record editor screen — modal form for adding or editing a DNS record."""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Select, Static

from dnsctl.config import SUPPORTED_RECORD_TYPES

_PROXY_TYPES = {"A", "AAAA", "CNAME"}
_PRIORITY_TYPES = {"MX", "SRV"}

_CONTENT_HINTS = {
    "A": "IPv4 address (e.g. 1.2.3.4)",
    "AAAA": "IPv6 address (e.g. 2001:db8::1)",
    "CNAME": "Target hostname (e.g. other.example.com)",
    "MX": "Mail server hostname (e.g. mail.example.com)",
    "TXT": "Text value (e.g. v=spf1 include:...)",
    "SRV": "Target hostname (e.g. sip.example.com)",
}


class RecordEditorScreen(Screen):
    """Add or edit a DNS record.

    Dismisses with ``(record_dict, protect_changed)`` on save, or ``None`` on cancel.
    ``protect_changed`` is ``(was_protected, is_protected, reason)`` if the
    protected state changed (or if the record is currently protected), else ``None``.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, zone_name: str, existing: dict | None = None) -> None:
        super().__init__()
        self._zone_name = zone_name
        self._existing = existing
        self._was_protected = False

    # ------------------------------------------------------------------ compose

    def compose(self) -> ComposeResult:
        is_edit = self._existing is not None
        initial_type = self._existing.get("type", "A") if is_edit else "A"

        yield Header()
        with Container(id="editor-container"):
            with Vertical(id="editor-form"):
                yield Static(
                    "Edit Record" if is_edit else "Add Record",
                    id="editor-header",
                )

                yield Label("Type")
                yield Select(
                    [(t, t) for t in SUPPORTED_RECORD_TYPES],
                    value=initial_type,
                    id="type-select",
                    disabled=is_edit,
                )

                yield Label("Name")
                yield Input(
                    value=self._existing.get("name", "") if is_edit else "",
                    placeholder=f"subdomain or full name (e.g. www.{self._zone_name})",
                    id="name-input",
                )

                yield Label("Content")
                yield Input(
                    value=self._existing.get("content", "") if is_edit else "",
                    placeholder=_CONTENT_HINTS.get(initial_type, ""),
                    id="content-input",
                )

                yield Label("TTL  (1 = Auto)")
                yield Input(
                    value=str(self._existing.get("ttl", 1)) if is_edit else "1",
                    id="ttl-input",
                )

                yield Checkbox(
                    "Proxied (Cloudflare proxy)",
                    value=self._existing.get("proxied", False) if is_edit else False,
                    id="proxied-check",
                )

                yield Label("Priority", id="priority-label")
                yield Input(
                    value=str(self._existing.get("priority", 10)) if is_edit else "10",
                    id="priority-input",
                )

                yield Checkbox(
                    "Protected (require --force to modify)",
                    value=False,
                    id="protected-check",
                )
                yield Label("Protection reason", id="reason-label")
                yield Input(
                    placeholder="Why is this record protected?",
                    id="reason-input",
                )

                yield Label("", id="editor-error", classes="error")

                with Horizontal(id="editor-buttons"):
                    yield Button("Save", variant="primary", id="save-btn")
                    yield Button("Cancel", id="cancel-btn")
        yield Footer()

    # ------------------------------------------------------------------ mount

    def on_mount(self) -> None:
        rtype = self._existing.get("type", "A") if self._existing else "A"
        self._update_type_fields(rtype)

        if self._existing:
            from dnsctl.core.state_manager import load_protected_records
            protected = load_protected_records()
            rtype = self._existing.get("type", "")
            rname = self._existing.get("name", "")
            match = next(
                (p for p in protected if p.get("type") == rtype and p.get("name") == rname),
                None,
            )
            self._was_protected = match is not None
            self.query_one("#protected-check", Checkbox).value = self._was_protected
            if match:
                self.query_one("#reason-input", Input).value = match.get("reason", "")
        self._update_protected_fields(self.query_one("#protected-check", Checkbox).value)

    # ------------------------------------------------------------------ events

    @on(Select.Changed, "#type-select")
    def on_type_changed(self, event: Select.Changed) -> None:
        if event.value and event.value is not Select.BLANK:
            self._update_type_fields(str(event.value))

    @on(Checkbox.Changed, "#protected-check")
    def on_protected_changed(self, event: Checkbox.Changed) -> None:
        self._update_protected_fields(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            self._do_save()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._do_save()

    # ------------------------------------------------------------------ helpers

    def _update_type_fields(self, rtype: str) -> None:
        show_proxy = rtype in _PROXY_TYPES
        show_priority = rtype in _PRIORITY_TYPES

        proxied = self.query_one("#proxied-check", Checkbox)
        p_label = self.query_one("#priority-label", Label)
        p_input = self.query_one("#priority-input", Input)

        if show_proxy:
            proxied.remove_class("hidden")
        else:
            proxied.add_class("hidden")

        if show_priority:
            p_label.remove_class("hidden")
            p_input.remove_class("hidden")
        else:
            p_label.add_class("hidden")
            p_input.add_class("hidden")

        self.query_one("#content-input", Input).placeholder = _CONTENT_HINTS.get(rtype, "")

    def _update_protected_fields(self, is_protected: bool) -> None:
        r_label = self.query_one("#reason-label", Label)
        r_input = self.query_one("#reason-input", Input)
        if is_protected:
            r_label.remove_class("hidden")
            r_input.remove_class("hidden")
        else:
            r_label.add_class("hidden")
            r_input.add_class("hidden")

    # ------------------------------------------------------------------ save logic

    def _do_save(self) -> None:
        from dnsctl.core.validations import validate_record

        error = self.query_one("#editor-error", Label)
        error.update("")

        type_select = self.query_one("#type-select", Select)
        rtype = str(type_select.value) if type_select.value and type_select.value is not Select.BLANK else "A"
        name = self.query_one("#name-input", Input).value.strip()
        content = self.query_one("#content-input", Input).value.strip()
        ttl_raw = self.query_one("#ttl-input", Input).value.strip()

        if not name:
            error.update("Name is required.")
            return
        if not content:
            error.update("Content is required.")
            return

        # Auto-append zone name when the name is a bare subdomain label
        if name and not name.endswith(self._zone_name) and not name.endswith(".") and "." not in name:
            name = f"{name}.{self._zone_name}"

        try:
            ttl = int(ttl_raw) if ttl_raw else 1
        except ValueError:
            error.update("TTL must be an integer (use 1 for Auto).")
            return

        record: dict = {
            "type": rtype,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": (
                self.query_one("#proxied-check", Checkbox).value
                if rtype in _PROXY_TYPES
                else False
            ),
        }

        if rtype in _PRIORITY_TYPES:
            try:
                record["priority"] = int(self.query_one("#priority-input", Input).value or "10")
            except ValueError:
                error.update("Priority must be an integer.")
                return

        if self._existing and "id" in self._existing:
            record["id"] = self._existing["id"]

        validation_err = validate_record(record)
        if validation_err:
            error.update(validation_err)
            return

        is_protected = self.query_one("#protected-check", Checkbox).value
        reason = self.query_one("#reason-input", Input).value.strip()

        protect_changed: tuple | None = None
        if is_protected != self._was_protected:
            protect_changed = (self._was_protected, is_protected, reason)
        elif is_protected:
            # Record remains protected — pass along reason in case it changed
            protect_changed = (True, True, reason)

        self.dismiss((record, protect_changed))
