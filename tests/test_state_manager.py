"""Tests for core.state_manager — state directory init, zone save/load, hashing."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from dnsctl.core import state_manager


@pytest.fixture
def tmp_state(tmp_path):
    """Patch all state directory paths to a temp dir for isolation."""
    zones = tmp_path / "zones"
    logs = tmp_path / "logs"
    metadata = tmp_path / "metadata.json"
    config = tmp_path / "config.json"
    gitignore = tmp_path / ".gitignore"

    patches = {
        "core.state_manager.STATE_DIR": tmp_path,
        "core.state_manager.ZONES_DIR": zones,
        "core.state_manager.LOGS_DIR": logs,
        "core.state_manager.METADATA_FILE": metadata,
        "core.state_manager.CONFIG_FILE": config,
        "core.state_manager.GITIGNORE_FILE": gitignore,
    }
    with patch.multiple("dnsctl.core.state_manager", **{k.split(".")[-1]: v for k, v in patches.items()}):
        yield tmp_path


class TestInitStateDir:
    def test_creates_directories_and_files(self, tmp_state):
        state_manager.init_state_dir()
        assert (tmp_state / "zones").is_dir()
        assert (tmp_state / "logs").is_dir()
        assert (tmp_state / "metadata.json").exists()
        assert (tmp_state / "config.json").exists()
        assert (tmp_state / ".gitignore").exists()

    def test_idempotent(self, tmp_state):
        state_manager.init_state_dir()
        state_manager.init_state_dir()
        assert (tmp_state / "zones").is_dir()


class TestZonePersistence:
    def test_save_and_load(self, tmp_state):
        state_manager.init_state_dir()
        records = [
            {"id": "r1", "type": "A", "name": "example.com", "content": "1.2.3.4", "ttl": 300, "proxied": False}
        ]
        state = state_manager.save_zone("z1", "example.com", records)
        assert state["zone_id"] == "z1"
        assert state["zone_name"] == "example.com"
        assert len(state["records"]) == 1
        assert state["state_hash"]

        loaded = state_manager.load_zone("example.com")
        assert loaded is not None
        assert loaded["zone_id"] == "z1"
        assert loaded["records"] == records

    def test_load_nonexistent_returns_none(self, tmp_state):
        state_manager.init_state_dir()
        assert state_manager.load_zone("nosuchzone.com") is None

    def test_list_synced_zones(self, tmp_state):
        state_manager.init_state_dir()
        state_manager.save_zone("z1", "alpha.com", [])
        state_manager.save_zone("z2", "beta.com", [])
        zones = state_manager.list_synced_zones()
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
