"""Tests for core.diff_engine — record comparison and diff computation."""

import pytest

from core.diff_engine import (
    DiffResult,
    compute_diff,
    is_protected,
    record_key,
    records_equal,
)


# ------------------------------------------------------------------
# record_key
# ------------------------------------------------------------------

class TestRecordKey:
    def test_a_record(self):
        rec = {"type": "A", "name": "x.com", "content": "1.2.3.4"}
        assert record_key(rec) == ("A", "x.com", "1.2.3.4")

    def test_mx_includes_priority(self):
        rec = {"type": "MX", "name": "x.com", "content": "mail.x.com", "priority": 10}
        assert record_key(rec) == ("MX", "x.com", "mail.x.com", 10)

    def test_srv_includes_port_and_target(self):
        rec = {
            "type": "SRV", "name": "_sip._tcp.x.com", "content": "sip.x.com",
            "priority": 0, "data": {"port": 5060, "target": "sip.x.com"},
        }
        assert record_key(rec) == ("SRV", "_sip._tcp.x.com", 0, 5060, "sip.x.com")

    def test_cname_record(self):
        rec = {"type": "CNAME", "name": "www.x.com", "content": "x.com"}
        assert record_key(rec) == ("CNAME", "www.x.com", "x.com")


# ------------------------------------------------------------------
# records_equal
# ------------------------------------------------------------------

class TestRecordsEqual:
    def test_equal_a_records(self):
        a = {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False}
        b = {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False}
        assert records_equal(a, b)

    def test_ignores_id_difference(self):
        a = {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False}
        b = {"id": "999", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False}
        assert records_equal(a, b)

    def test_different_content(self):
        a = {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False}
        b = {"id": "1", "type": "A", "name": "x.com", "content": "5.6.7.8", "ttl": 300, "proxied": False}
        assert not records_equal(a, b)

    def test_different_ttl(self):
        a = {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False}
        b = {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 3600, "proxied": False}
        assert not records_equal(a, b)

    def test_different_proxied(self):
        a = {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 1, "proxied": False}
        b = {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 1, "proxied": True}
        assert not records_equal(a, b)

    def test_mx_priority_matters(self):
        a = {"id": "1", "type": "MX", "name": "x.com", "content": "mx.x.com", "ttl": 1, "proxied": False, "priority": 10}
        b = {"id": "1", "type": "MX", "name": "x.com", "content": "mx.x.com", "ttl": 1, "proxied": False, "priority": 20}
        assert not records_equal(a, b)


# ------------------------------------------------------------------
# compute_diff
# ------------------------------------------------------------------

class TestComputeDiff:
    def test_identical_records(self):
        records = [
            {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False},
        ]
        diff = compute_diff(list(records), list(records))
        assert not diff.has_changes
        assert len(diff.unchanged) == 1

    def test_added_in_target(self):
        base = [
            {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False},
        ]
        target = list(base) + [
            {"id": "2", "type": "A", "name": "new.x.com", "content": "5.6.7.8", "ttl": 300, "proxied": False},
        ]
        diff = compute_diff(base, target)
        assert len(diff.added) == 1
        assert diff.added[0]["name"] == "new.x.com"

    def test_removed_from_target(self):
        base = [
            {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False},
            {"id": "2", "type": "A", "name": "old.x.com", "content": "5.6.7.8", "ttl": 300, "proxied": False},
        ]
        target = [base[0]]
        diff = compute_diff(base, target)
        assert len(diff.removed) == 1
        assert diff.removed[0]["name"] == "old.x.com"

    def test_modified_record(self):
        base = [
            {"id": "1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False},
        ]
        target = [
            {"id": "1", "type": "A", "name": "x.com", "content": "5.6.7.8", "ttl": 300, "proxied": False},
        ]
        diff = compute_diff(base, target)
        assert len(diff.modified) == 1
        assert diff.modified[0]["before"]["content"] == "1.2.3.4"
        assert diff.modified[0]["after"]["content"] == "5.6.7.8"

    def test_mixed_changes(self):
        base = [
            {"id": "1", "type": "A", "name": "keep.x.com", "content": "1.1.1.1", "ttl": 300, "proxied": False},
            {"id": "2", "type": "A", "name": "modify.x.com", "content": "2.2.2.2", "ttl": 300, "proxied": False},
            {"id": "3", "type": "A", "name": "remove.x.com", "content": "3.3.3.3", "ttl": 300, "proxied": False},
        ]
        target = [
            {"id": "1", "type": "A", "name": "keep.x.com", "content": "1.1.1.1", "ttl": 300, "proxied": False},
            {"id": "2", "type": "A", "name": "modify.x.com", "content": "9.9.9.9", "ttl": 300, "proxied": False},
            {"id": "4", "type": "A", "name": "add.x.com", "content": "4.4.4.4", "ttl": 300, "proxied": False},
        ]
        diff = compute_diff(base, target)
        assert len(diff.unchanged) == 1
        assert len(diff.modified) == 1
        assert len(diff.removed) == 1
        assert len(diff.added) == 1

    def test_records_without_id_use_composite_key(self):
        base = [
            {"type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300, "proxied": False},
        ]
        target = [
            {"type": "A", "name": "new.x.com", "content": "5.6.7.8", "ttl": 300, "proxied": False},
        ]
        diff = compute_diff(base, target)
        assert len(diff.added) == 1
        assert len(diff.removed) == 1

    def test_empty_sets(self):
        diff = compute_diff([], [])
        assert not diff.has_changes


# ------------------------------------------------------------------
# DiffResult.summary
# ------------------------------------------------------------------

class TestDiffResultSummary:
    def test_summary_with_changes(self):
        diff = DiffResult(
            added=[{"type": "A"}],
            removed=[{"type": "A"}, {"type": "A"}],
            modified=[{"before": {}, "after": {}}],
        )
        assert "+1 added" in diff.summary
        assert "-2 removed" in diff.summary
        assert "~1 modified" in diff.summary

    def test_summary_no_changes(self):
        diff = DiffResult()
        assert diff.summary == "No changes"


# ------------------------------------------------------------------
# is_protected
# ------------------------------------------------------------------

class TestIsProtected:
    def test_ns_is_system_protected(self):
        rec = {"type": "NS", "name": "x.com"}
        prot, reason = is_protected(rec)
        assert prot
        assert "NS" in reason

    def test_a_record_not_protected(self):
        rec = {"type": "A", "name": "x.com"}
        prot, _ = is_protected(rec)
        assert not prot

    def test_user_protected_record(self):
        rec = {"type": "A", "name": "critical.x.com"}
        user_prot = [{"type": "A", "name": "critical.x.com", "reason": "do not touch"}]
        prot, reason = is_protected(rec, user_prot)
        assert prot
        assert "do not touch" in reason

    def test_user_protected_no_match(self):
        rec = {"type": "A", "name": "other.x.com"}
        user_prot = [{"type": "A", "name": "critical.x.com", "reason": "do not touch"}]
        prot, _ = is_protected(rec, user_prot)
        assert not prot
