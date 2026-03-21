"""Plan screen — show pending changes and apply them."""

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Label, Static


class PlanScreen(Screen):
    """Shows the diff between local state and Cloudflare, and allows applying."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("ctrl+q", "app.quit", "Quit"),
    ]

    def __init__(self, zone_name: str, alias: str, token: str) -> None:
        super().__init__()
        self._zone_name = zone_name
        self._alias = alias
        self._token = token
        self._plan = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" Plan for: {self._zone_name}", id="plan-zone-bar")
        yield Label("Generating plan…", id="plan-status")
        table = DataTable(id="plan-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Action", "Type", "Name", "Content", "Notes")
        yield table
        with Horizontal(id="plan-buttons"):
            yield Button("Apply", variant="success", id="apply-btn", disabled=True)
            yield Button("Back", id="back-btn")
        yield Label("", id="apply-status")
        yield Footer()

    def on_mount(self) -> None:
        self._generate_plan()

    # ------------------------------------------------------------------ plan generation

    @work(thread=True)
    def _generate_plan(self) -> None:
        try:
            from dnsctl.core.sync_engine import SyncEngine

            engine = SyncEngine(alias=self._alias)
            plan = engine.generate_plan(self._zone_name, self._token)
        except Exception as exc:
            self.app.call_from_thread(self._show_error, f"Failed to generate plan: {exc}")
            return
        self.app.call_from_thread(self._populate_plan, plan)

    def _populate_plan(self, plan) -> None:
        self._plan = plan
        table = self.query_one("#plan-table", DataTable)
        status = self.query_one("#plan-status", Label)
        apply_btn = self.query_one("#apply-btn", Button)
        table.clear()

        if not plan.has_changes:
            msg = "No changes to apply."
            if plan.drift and plan.drift.has_changes:
                msg += f"  Drift detected ({plan.drift.summary}) — sync first."
            status.update(msg)
            return

        action_styles = {"create": "green", "update": "yellow", "delete": "red"}
        for action in plan.actions:
            colour = action_styles.get(action.action, "white")
            verb = action.action.upper()
            rec = action.record
            before_content = (action.before or {}).get("content", "")
            content_display = (
                f"{before_content} → {rec.get('content', '')}"
                if action.action == "update"
                else rec.get("content", "")
            )
            notes = "[PROTECTED]" if action.protected else ""
            table.add_row(
                f"[{colour}]{verb}[/{colour}]",
                rec.get("type", ""),
                rec.get("name", ""),
                content_display,
                notes,
            )

        n_protected = sum(1 for a in plan.actions if a.protected)
        summary = plan.summary
        if n_protected:
            summary += f"  ({n_protected} protected — skipped without --force)"
        status.update(summary)
        apply_btn.disabled = False

    def _show_error(self, msg: str) -> None:
        self.query_one("#plan-status", Label).update(f"[red]{msg}[/red]")

    # ------------------------------------------------------------------ apply

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "apply-btn":
            self._do_apply()

    @work(thread=True)
    def _do_apply(self) -> None:
        self.app.call_from_thread(self._set_applying, True)
        try:
            from dnsctl.core.sync_engine import SyncEngine

            engine = SyncEngine(alias=self._alias)
            result = engine.apply_plan(self._plan, self._token)
        except Exception as exc:
            self.app.call_from_thread(self._set_applying, False)
            self.app.call_from_thread(
                self.query_one("#apply-status", Label).update,
                f"[red]Apply failed: {exc}[/red]",
            )
            return
        self.app.call_from_thread(self._show_apply_result, result)

    def _set_applying(self, applying: bool) -> None:
        btn = self.query_one("#apply-btn", Button)
        btn.disabled = applying
        btn.label = "Applying…" if applying else "Apply"

    def _show_apply_result(self, result) -> None:
        self._set_applying(False)
        status = self.query_one("#apply-status", Label)
        if result.all_succeeded:
            status.update(f"[green]Applied {len(result.succeeded)} change(s) successfully.[/green]")
        else:
            status.update(
                f"[yellow]{len(result.succeeded)} succeeded, "
                f"{len(result.failed)} failed.[/yellow]"
            )
        if result.sync_failed:
            status.update(
                status.renderable
                + "  [yellow]Post-apply sync failed — run sync to refresh.[/yellow]"
            )
        # Refresh the plan table
        self._plan = None
        self.query_one("#plan-table", DataTable).clear()
        self._generate_plan()

    # ------------------------------------------------------------------ actions

    def action_go_back(self) -> None:
        self.app.pop_screen()
