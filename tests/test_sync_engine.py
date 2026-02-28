"""Tests for core.sync_engine — plan generation and application."""

from unittest.mock import MagicMock, patch

import pytest

from dnsctl.core.sync_engine import SyncEngine, Plan, PlanAction, ApplyResult


def _sample_records():
    return [
        {"id": "r1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False},
        {"id": "r2", "type": "MX", "name": "x.com", "content": "mail.x.com", "ttl": 1, "priority": 10, "proxied": False},
    ]


# ------------------------------------------------------------------
# detect_drift
# ------------------------------------------------------------------

class TestDetectDrift:
    @patch("dnsctl.core.sync_engine.CloudflareClient")
    @patch("dnsctl.core.sync_engine.load_zone")
    def test_clean_no_drift(self, mock_load, mock_cf_cls):
        records = _sample_records()
        mock_load.return_value = {"zone_id": "z1", "records": records}
        mock_cf = MagicMock()
        mock_cf_cls.return_value = mock_cf
        mock_cf.list_records.return_value = list(records)

        engine = SyncEngine()
        drift = engine.detect_drift("x.com", "token")
        assert drift is not None
        assert not drift.has_changes

    @patch("dnsctl.core.sync_engine.CloudflareClient")
    @patch("dnsctl.core.sync_engine.load_zone")
    def test_drift_with_remote_addition(self, mock_load, mock_cf_cls):
        records = _sample_records()
        mock_load.return_value = {"zone_id": "z1", "records": records}

        remote = list(records) + [
            {"id": "r3", "type": "A", "name": "new.x.com", "content": "5.6.7.8", "ttl": 300, "proxied": False},
        ]
        mock_cf = MagicMock()
        mock_cf_cls.return_value = mock_cf
        mock_cf.list_records.return_value = remote

        engine = SyncEngine()
        drift = engine.detect_drift("x.com", "token")
        assert drift is not None
        assert drift.has_changes
        assert len(drift.added) == 1

    @patch("dnsctl.core.sync_engine.CloudflareClient")
    @patch("dnsctl.core.sync_engine.load_zone")
    def test_not_synced_returns_none(self, mock_load, mock_cf_cls):
        mock_load.return_value = None
        engine = SyncEngine()
        assert engine.detect_drift("x.com", "token") is None


# ------------------------------------------------------------------
# generate_plan
# ------------------------------------------------------------------

class TestGeneratePlan:
    @patch("dnsctl.core.sync_engine.CloudflareClient")
    @patch("dnsctl.core.sync_engine.load_zone")
    def test_no_changes_when_in_sync(self, mock_load, mock_cf_cls):
        records = _sample_records()
        mock_load.return_value = {"zone_id": "z1", "records": records}
        mock_cf = MagicMock()
        mock_cf_cls.return_value = mock_cf
        mock_cf.list_records.return_value = list(records)

        engine = SyncEngine()
        plan = engine.generate_plan("x.com", "token")
        assert not plan.has_changes

    @patch("dnsctl.core.sync_engine.CloudflareClient")
    @patch("dnsctl.core.sync_engine.load_zone")
    def test_plan_detects_delete_for_remote_addition(self, mock_load, mock_cf_cls):
        """Remote has extra record → plan includes DELETE to match local."""
        records = _sample_records()
        mock_load.return_value = {"zone_id": "z1", "records": records}

        remote = list(records) + [
            {"id": "r3", "type": "A", "name": "extra.x.com", "content": "9.9.9.9", "ttl": 300, "proxied": False},
        ]
        mock_cf = MagicMock()
        mock_cf_cls.return_value = mock_cf
        mock_cf.list_records.return_value = remote

        engine = SyncEngine()
        plan = engine.generate_plan("x.com", "token")
        assert plan.has_changes
        deletes = [a for a in plan.actions if a.action == "delete"]
        assert len(deletes) == 1
        assert deletes[0].record["name"] == "extra.x.com"

    @patch("dnsctl.core.sync_engine.CloudflareClient")
    @patch("dnsctl.core.sync_engine.load_zone")
    def test_not_synced_raises(self, mock_load, mock_cf_cls):
        mock_load.return_value = None
        engine = SyncEngine()
        with pytest.raises(ValueError, match="not synced"):
            engine.generate_plan("x.com", "token")


# ------------------------------------------------------------------
# apply_plan
# ------------------------------------------------------------------

class TestApplyPlan:
    @patch("dnsctl.core.sync_engine.GitManager")
    @patch("dnsctl.core.sync_engine.save_zone")
    @patch("dnsctl.core.sync_engine.CloudflareClient")
    def test_apply_create_calls_api(self, mock_cf_cls, mock_save, mock_git_cls):
        mock_cf = MagicMock()
        mock_cf_cls.return_value = mock_cf
        mock_cf.list_records.return_value = []
        mock_git = MagicMock()
        mock_git_cls.return_value = mock_git

        plan = Plan(
            zone_name="x.com", zone_id="z1",
            actions=[
                PlanAction(action="create", record={
                    "type": "A", "name": "new.x.com", "content": "1.2.3.4", "ttl": 300,
                }),
            ],
        )

        engine = SyncEngine()
        result = engine.apply_plan(plan, "token")
        assert result.all_succeeded
        assert len(result.succeeded) == 1
        mock_cf.create_record.assert_called_once()

    @patch("dnsctl.core.sync_engine.GitManager")
    @patch("dnsctl.core.sync_engine.save_zone")
    @patch("dnsctl.core.sync_engine.CloudflareClient")
    def test_apply_skips_protected(self, mock_cf_cls, mock_save, mock_git_cls):
        mock_cf = MagicMock()
        mock_cf_cls.return_value = mock_cf
        mock_cf.list_records.return_value = []
        mock_git = MagicMock()
        mock_git_cls.return_value = mock_git

        plan = Plan(
            zone_name="x.com", zone_id="z1",
            actions=[
                PlanAction(
                    action="delete",
                    record={"id": "r1", "type": "NS", "name": "x.com"},
                    protected=True,
                    protection_reason="system",
                ),
            ],
        )

        engine = SyncEngine()
        result = engine.apply_plan(plan, "token", force=False)
        assert not result.all_succeeded
        assert len(result.failed) == 1
        mock_cf.delete_record.assert_not_called()

    @patch("dnsctl.core.sync_engine.GitManager")
    @patch("dnsctl.core.sync_engine.save_zone")
    @patch("dnsctl.core.sync_engine.CloudflareClient")
    def test_apply_force_overrides_protection(self, mock_cf_cls, mock_save, mock_git_cls):
        mock_cf = MagicMock()
        mock_cf_cls.return_value = mock_cf
        mock_cf.list_records.return_value = []
        mock_git = MagicMock()
        mock_git_cls.return_value = mock_git

        plan = Plan(
            zone_name="x.com", zone_id="z1",
            actions=[
                PlanAction(
                    action="delete",
                    record={"id": "r1", "type": "NS", "name": "x.com"},
                    protected=True,
                    protection_reason="system",
                ),
            ],
        )

        engine = SyncEngine()
        result = engine.apply_plan(plan, "token", force=True)
        assert result.all_succeeded
        mock_cf.delete_record.assert_called_once()


# ------------------------------------------------------------------
# Plan data structure
# ------------------------------------------------------------------

class TestPlanDataStructure:
    def test_summary(self):
        plan = Plan(
            zone_name="x.com", zone_id="z1",
            actions=[
                PlanAction(action="create", record={"type": "A"}),
                PlanAction(action="update", record={"type": "A"}, before={"type": "A"}),
                PlanAction(action="delete", record={"type": "CNAME"}),
            ],
        )
        assert "+1 create" in plan.summary
        assert "~1 update" in plan.summary
        assert "-1 delete" in plan.summary

    def test_has_protected(self):
        plan = Plan(
            zone_name="x.com", zone_id="z1",
            actions=[
                PlanAction(action="delete", record={"type": "A"}, protected=True),
            ],
        )
        assert plan.has_protected

    def test_no_changes(self):
        plan = Plan(zone_name="x.com", zone_id="z1")
        assert not plan.has_changes
        assert plan.summary == "No changes"
