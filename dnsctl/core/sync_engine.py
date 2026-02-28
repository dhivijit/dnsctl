"""Sync engine — orchestrate plan generation and application."""

import logging
from dataclasses import dataclass, field

from dnsctl.core.cloudflare_client import CloudflareClient, CloudflareAPIError
from dnsctl.core.diff_engine import DiffResult, compute_diff, is_protected
from dnsctl.core.git_manager import GitManager
from dnsctl.core.state_manager import load_protected_records, load_zone, save_zone

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass
class PlanAction:
    """A single action in an execution plan."""

    action: str  # "create" | "update" | "delete"
    record: dict
    before: dict | None = None  # for updates: current remote state
    protected: bool = False
    protection_reason: str = ""


@dataclass
class Plan:
    """Execution plan for a single zone."""

    zone_name: str
    zone_id: str
    actions: list[PlanAction] = field(default_factory=list)
    drift: DiffResult | None = None

    @property
    def has_changes(self) -> bool:
        return bool(self.actions)

    @property
    def has_protected(self) -> bool:
        return any(a.protected for a in self.actions)

    @property
    def summary(self) -> str:
        creates = sum(1 for a in self.actions if a.action == "create")
        updates = sum(1 for a in self.actions if a.action == "update")
        deletes = sum(1 for a in self.actions if a.action == "delete")
        parts = []
        if creates:
            parts.append(f"+{creates} create")
        if updates:
            parts.append(f"~{updates} update")
        if deletes:
            parts.append(f"-{deletes} delete")
        return ", ".join(parts) if parts else "No changes"


@dataclass
class ApplyResult:
    """Result of applying a plan."""

    succeeded: list[PlanAction] = field(default_factory=list)
    failed: list[tuple[PlanAction, str]] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return len(self.failed) == 0



# ------------------------------------------------------------------
# Engine
# ------------------------------------------------------------------

class SyncEngine:
    """Orchestrates drift detection, plan generation, and plan application."""

    def __init__(self) -> None:
        self._cf = CloudflareClient()
        self._git = GitManager()

    # ------------------------------------------------------------------
    # Drift detection
    # ------------------------------------------------------------------

    def detect_drift(self, zone_name: str, token: str) -> DiffResult | None:
        """Compare last-synced state with current remote for a zone.

        Returns a ``DiffResult`` describing what changed on Cloudflare
        since the last sync, or ``None`` if the zone hasn't been synced.
        """
        local_state = load_zone(zone_name)
        if local_state is None:
            return None

        zone_id = local_state["zone_id"]
        local_records = local_state["records"]
        remote_records = self._cf.list_records(token, zone_id)

        # base=local (last sync), target=remote (current) → shows remote changes
        return compute_diff(local_records, remote_records)

    # ------------------------------------------------------------------
    # Plan generation
    # ------------------------------------------------------------------

    def generate_plan(self, zone_name: str, token: str) -> Plan:
        """Generate an execution plan for a zone.

        Compares local desired state against current remote state and
        produces a list of actions to apply **to Cloudflare** so that
        remote matches local.
        """
        local_state = load_zone(zone_name)
        if local_state is None:
            raise ValueError(f"Zone '{zone_name}' not synced. Run sync first.")

        zone_id = local_state["zone_id"]
        local_records = local_state["records"]
        remote_records = self._cf.list_records(token, zone_id)

        # Drift: what changed on remote since our last sync
        drift = compute_diff(local_records, remote_records)

        # Plan diff: base=remote, target=local
        #   added   → in local, not remote → CREATE
        #   removed → in remote, not local → DELETE
        #   modified → both have it, before=remote, after=local → UPDATE
        diff = compute_diff(remote_records, local_records)

        user_protected = load_protected_records()
        actions: list[PlanAction] = []

        for rec in diff.added:
            prot, reason = is_protected(rec, user_protected)
            actions.append(PlanAction(
                action="create", record=rec,
                protected=prot, protection_reason=reason,
            ))

        for rec in diff.removed:
            prot, reason = is_protected(rec, user_protected)
            actions.append(PlanAction(
                action="delete", record=rec,
                protected=prot, protection_reason=reason,
            ))

        for mod in diff.modified:
            rec = mod["after"]      # local (desired) version
            before = mod["before"]  # current remote version
            prot, reason = is_protected(rec, user_protected)
            actions.append(PlanAction(
                action="update", record=rec, before=before,
                protected=prot, protection_reason=reason,
            ))

        return Plan(
            zone_name=zone_name,
            zone_id=zone_id,
            actions=actions,
            drift=drift,
        )

    # ------------------------------------------------------------------
    # Plan application
    # ------------------------------------------------------------------

    def apply_plan(
        self, plan: Plan, token: str, *, force: bool = False,
    ) -> ApplyResult:
        """Execute a plan against the Cloudflare API.

        Protected records are skipped unless *force* is ``True``.
        After application, re-syncs state from remote and commits to git.
        """
        result = ApplyResult()

        for action in plan.actions:
            if action.protected and not force:
                result.failed.append((
                    action,
                    f"Protected ({action.protection_reason}). Use --force to override.",
                ))
                continue

            try:
                if action.action == "create":
                    self._cf.create_record(token, plan.zone_id, action.record)
                    result.succeeded.append(action)

                elif action.action == "update":
                    record_id = (action.before or action.record).get("id")
                    if not record_id:
                        result.failed.append((action, "No record ID for update"))
                        continue
                    self._cf.update_record(
                        token, plan.zone_id, record_id, action.record,
                    )
                    result.succeeded.append(action)

                elif action.action == "delete":
                    record_id = action.record.get("id")
                    if not record_id:
                        result.failed.append((action, "No record ID for delete"))
                        continue
                    self._cf.delete_record(token, plan.zone_id, record_id)
                    result.succeeded.append(action)

            except CloudflareAPIError as exc:
                logger.error("Failed to %s record: %s", action.action, exc)
                result.failed.append((action, str(exc)))
            except Exception as exc:
                logger.error("Unexpected error during %s: %s", action.action, exc)
                result.failed.append((action, str(exc)))

        # Re-sync: fetch fresh remote state and save locally
        try:
            remote_records = self._cf.list_records(token, plan.zone_id)
            save_zone(plan.zone_id, plan.zone_name, remote_records)

            self._git.auto_init()
            self._git.commit(
                f"Applied changes to {plan.zone_name} ({plan.summary})"
            )
        except Exception as exc:
            logger.error("Post-apply sync failed: %s", exc)

        return result
