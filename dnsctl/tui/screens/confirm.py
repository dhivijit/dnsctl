"""Shared confirmation modal screen."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static


class ConfirmScreen(Screen):
    """Small modal that asks the user to confirm an action.

    Dismisses with True (confirmed) or False (cancelled).
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Confirm", priority=True),
    ]

    def __init__(self, question: str, confirm_label: str = "Yes", confirm_variant: str = "error") -> None:
        super().__init__()
        self._question = question
        self._confirm_label = confirm_label
        self._confirm_variant = confirm_variant

    def compose(self) -> ComposeResult:
        with Container(id="confirm-container"):
            with Vertical(id="confirm-box"):
                yield Static(self._question, id="confirm-question")
                with Horizontal(id="confirm-buttons"):
                    yield Button(self._confirm_label, variant=self._confirm_variant, id="yes-btn")
                    yield Button("Cancel", variant="primary", id="no-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes-btn")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)
