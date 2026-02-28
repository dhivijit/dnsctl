"""Tests for Phase 4 — git rollback, export/import."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core import state_manager
from core.git_manager import GitManager


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def tmp_state(tmp_path):
    """Patch all state directory paths to a temp dir for isolation."""
    zones = tmp_path / "zones"
    logs = tmp_path / "logs"
    metadata = tmp_path / "metadata.json"
    config = tmp_path / "config.json"
    gitignore = tmp_path / ".gitignore"

    patches = {
        "STATE_DIR": tmp_path,
        "ZONES_DIR": zones,
        "LOGS_DIR": logs,
        "METADATA_FILE": metadata,
        "CONFIG_FILE": config,
        "GITIGNORE_FILE": gitignore,
    }
    with patch.multiple("core.state_manager", **patches):
        yield tmp_path


@pytest.fixture
def git_repo(tmp_path):
    """Create a GitManager with a real git repo in a temp dir."""
    gm = GitManager(state_dir=tmp_path)
    # Create .gitignore so auto_init can commit
    (tmp_path / ".gitignore").write_text(".session\nlogs/\n")
    gm.auto_init()
    return gm


# ------------------------------------------------------------------
# GitManager.rollback
# ------------------------------------------------------------------

class TestGitRollback:
    def test_rollback_restores_file(self, git_repo, tmp_path):
        # Commit v1
        (tmp_path / "data.txt").write_text("version1")
        sha1 = git_repo.commit("v1")
        assert sha1 is not None

        # Commit v2
        (tmp_path / "data.txt").write_text("version2")
        sha2 = git_repo.commit("v2")
        assert sha2 is not None

        # Rollback to v1
        new_sha = git_repo.rollback(sha1)
        assert (tmp_path / "data.txt").read_text() == "version1"
        assert new_sha is not None

    def test_rollback_creates_new_commit(self, git_repo, tmp_path):
        (tmp_path / "data.txt").write_text("v1")
        sha1 = git_repo.commit("v1")

        (tmp_path / "data.txt").write_text("v2")
        git_repo.commit("v2")

        before_count = len(git_repo.log())
        git_repo.rollback(sha1)
        after_count = len(git_repo.log())

        # Should have created one more commit
        assert after_count == before_count + 1

    def test_rollback_invalid_commit_raises(self, git_repo):
        with pytest.raises(ValueError, match="Cannot resolve"):
            git_repo.rollback("nonexistent_sha_000000")

    def test_rollback_to_current_is_noop(self, git_repo, tmp_path):
        (tmp_path / "data.txt").write_text("v1")
        sha1 = git_repo.commit("v1")

        # Rolling back to current state — no new commit needed
        result = git_repo.rollback(sha1)
        assert result == sha1

    def test_rollback_with_short_sha(self, git_repo, tmp_path):
        (tmp_path / "data.txt").write_text("v1")
        sha1 = git_repo.commit("v1")

        (tmp_path / "data.txt").write_text("v2")
        git_repo.commit("v2")

        # Use short SHA (first 8 chars)
        git_repo.rollback(sha1[:8])
        assert (tmp_path / "data.txt").read_text() == "v1"


# ------------------------------------------------------------------
# GitManager.show_file_at
# ------------------------------------------------------------------

class TestShowFileAt:
    def test_show_existing_file(self, git_repo, tmp_path):
        (tmp_path / "data.txt").write_text("hello")
        sha = git_repo.commit("add data")

        content = git_repo.show_file_at(sha, "data.txt")
        assert content == "hello"

    def test_show_nonexistent_file_returns_none(self, git_repo, tmp_path):
        (tmp_path / "data.txt").write_text("hello")
        sha = git_repo.commit("add data")

        assert git_repo.show_file_at(sha, "missing.txt") is None

    def test_show_file_at_older_commit(self, git_repo, tmp_path):
        (tmp_path / "data.txt").write_text("old")
        sha1 = git_repo.commit("v1")

        (tmp_path / "data.txt").write_text("new")
        git_repo.commit("v2")

        assert git_repo.show_file_at(sha1, "data.txt") == "old"


# ------------------------------------------------------------------
# Export / Import
# ------------------------------------------------------------------

class TestExport:
    def test_export_zone(self, tmp_state):
        state_manager.init_state_dir()
        records = [{"type": "A", "name": "x.com", "content": "1.2.3.4"}]
        state_manager.save_zone("z1", "x.com", records)

        dest = tmp_state / "export.json"
        state_manager.export_zone("x.com", dest)

        assert dest.exists()
        data = json.loads(dest.read_text())
        assert data["zone_name"] == "x.com"
        assert data["zone_id"] == "z1"
        assert len(data["records"]) == 1

    def test_export_nonexistent_zone_raises(self, tmp_state):
        state_manager.init_state_dir()
        with pytest.raises(FileNotFoundError, match="not been synced"):
            state_manager.export_zone("missing.com", tmp_state / "out.json")


class TestImport:
    def test_import_valid_file(self, tmp_state):
        state_manager.init_state_dir()
        src = tmp_state / "import.json"
        src.write_text(json.dumps({
            "zone_id": "z99",
            "zone_name": "imported.com",
            "records": [{"type": "TXT", "name": "imported.com", "content": "hello"}],
            "last_synced_at": "2025-01-01T00:00:00Z",
            "state_hash": "abc123",
        }))

        state = state_manager.import_zone(src)
        assert state["zone_name"] == "imported.com"
        assert len(state["records"]) == 1

        # Verify it was saved
        loaded = state_manager.load_zone("imported.com")
        assert loaded is not None
        assert loaded["zone_id"] == "z99"

    def test_import_missing_fields_raises(self, tmp_state):
        state_manager.init_state_dir()
        src = tmp_state / "bad.json"
        src.write_text(json.dumps({"zone_id": "z1"}))

        with pytest.raises(ValueError, match="must contain"):
            state_manager.import_zone(src)

    def test_import_invalid_json_raises(self, tmp_state):
        state_manager.init_state_dir()
        src = tmp_state / "bad.json"
        src.write_text("not json {{{")

        with pytest.raises(ValueError, match="Cannot read"):
            state_manager.import_zone(src)

    def test_import_records_not_list_raises(self, tmp_state):
        state_manager.init_state_dir()
        src = tmp_state / "bad.json"
        src.write_text(json.dumps({
            "zone_id": "z1",
            "zone_name": "x.com",
            "records": "not a list",
        }))

        with pytest.raises(ValueError, match="must be a list"):
            state_manager.import_zone(src)

    def test_roundtrip_export_import(self, tmp_state):
        state_manager.init_state_dir()
        records = [
            {"type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300},
            {"type": "CNAME", "name": "www.x.com", "content": "x.com", "ttl": 1},
        ]
        state_manager.save_zone("z1", "x.com", records)

        export_path = tmp_state / "roundtrip.json"
        state_manager.export_zone("x.com", export_path)

        # Clear the zone
        (tmp_state / "zones" / "x.com.json").unlink()
        assert state_manager.load_zone("x.com") is None

        # Re-import
        state = state_manager.import_zone(export_path)
        assert state["zone_name"] == "x.com"
        assert len(state["records"]) == 2
