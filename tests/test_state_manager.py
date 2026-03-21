"""Tests for core.state_manager — state directory init, zone save/load, hashing."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from dnsctl.core import state_manager

_ALIAS = "test"


@pytest.fixture
def tmp_state(tmp_path):
    """Patch all state directory paths to a temp dir for isolation."""
    accounts_dir = tmp_path / "accounts"
    accounts_file = tmp_path / "accounts.json"
    logs = tmp_path / "logs"
    metadata = tmp_path / "metadata.json"
    config = tmp_path / "config.json"

    with patch.multiple(
        "dnsctl.core.state_manager",
        STATE_DIR=tmp_path,
        ACCOUNTS_DIR=accounts_dir,
        ACCOUNTS_FILE=accounts_file,
        LOGS_DIR=logs,
        METADATA_FILE=metadata,
        CONFIG_FILE=config,
        _LEGACY_ZONES_DIR=tmp_path / "zones",
    ):
        yield tmp_path


class TestInitStateDir:
    def test_creates_directories_and_files(self, tmp_state):
        # Prevent migration from hitting real keyring
        with patch("dnsctl.core.state_manager._migrate_legacy"):
            state_manager.init_state_dir()
        assert (tmp_state / "accounts").is_dir()
        assert (tmp_state / "logs").is_dir()
        assert (tmp_state / "metadata.json").exists()
        assert (tmp_state / "config.json").exists()

    def test_idempotent(self, tmp_state):
        with patch("dnsctl.core.state_manager._migrate_legacy"):
            state_manager.init_state_dir()
            state_manager.init_state_dir()
        assert (tmp_state / "accounts").is_dir()


class TestZonePersistence:
    def test_save_and_load(self, tmp_state):
        with patch("dnsctl.core.state_manager._migrate_legacy"):
            state_manager.init_state_dir()
        records = [
            {"id": "r1", "type": "A", "name": "example.com", "content": "1.2.3.4", "ttl": 300, "proxied": False}
        ]
        state = state_manager.save_zone("z1", "example.com", records, _ALIAS)
        assert state["zone_id"] == "z1"
        assert state["zone_name"] == "example.com"
        assert len(state["records"]) == 1
        assert state["state_hash"]

        loaded = state_manager.load_zone("example.com", _ALIAS)
        assert loaded is not None
        assert loaded["zone_id"] == "z1"
        assert loaded["records"] == records

    def test_load_nonexistent_returns_none(self, tmp_state):
        with patch("dnsctl.core.state_manager._migrate_legacy"):
            state_manager.init_state_dir()
        assert state_manager.load_zone("nosuchzone.com", _ALIAS) is None

    def test_list_synced_zones(self, tmp_state):
        with patch("dnsctl.core.state_manager._migrate_legacy"):
            state_manager.init_state_dir()
        state_manager.save_zone("z1", "alpha.com", [], _ALIAS)
        state_manager.save_zone("z2", "beta.com", [], _ALIAS)
        zones = state_manager.list_synced_zones(_ALIAS)
        assert zones == ["alpha.com", "beta.com"]


class TestHash:
    def test_deterministic(self):
        records = [{"type": "A", "name": "x.com", "content": "1.2.3.4"}]
        h1 = state_manager._compute_hash(records)
        h2 = state_manager._compute_hash(records)
        assert h1 == h2

    def test_differs_on_change(self):
        r1 = [{"type": "A", "name": "x.com", "content": "1.2.3.4"}]
        r2 = [{"type": "A", "name": "x.com", "content": "5.6.7.8"}]
        assert state_manager._compute_hash(r1) != state_manager._compute_hash(r2)
