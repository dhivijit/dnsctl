"""Shared single-line input modal screen."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label


class InputScreen(Screen):
    """Small modal that asks the user to type a value.

    Dismisses with the entered string, or ``None`` if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        prompt: str,
        placeholder: str = "",
        confirm_label: str = "OK",
    ) -> None:
        super().__init__()
        self._prompt = prompt
        self._placeholder = placeholder
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Container(id="input-modal-container"):
            with Vertical(id="input-modal-box"):
                yield Label(self._prompt, id="input-modal-prompt")
                yield Input(placeholder=self._placeholder, id="input-modal-field")
                with Horizontal(id="input-modal-buttons"):
                    yield Button(self._confirm_label, variant="primary", id="input-ok-btn")
                    yield Button("Cancel", variant="default", id="input-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "input-ok-btn":
            self._submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        value = self.query_one("#input-modal-field", Input).value.strip()
        self.dismiss(value if value else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
