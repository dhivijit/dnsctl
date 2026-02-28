"""Tests for Phase 5 — protected records management, error handling."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests

from core import state_manager
from core.cloudflare_client import CloudflareClient, CloudflareAPIError


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


# ------------------------------------------------------------------
# Protected records management
# ------------------------------------------------------------------

class TestProtectedRecords:
    def test_load_empty(self, tmp_state):
        state_manager.init_state_dir()
        protected = state_manager.load_protected_records()
        assert protected == []

    def test_add_protected_record(self, tmp_state):
        state_manager.init_state_dir()
        result = state_manager.add_protected_record("A", "example.com", "Production")
        assert len(result) == 1
        assert result[0]["type"] == "A"
        assert result[0]["name"] == "example.com"
        assert result[0]["reason"] == "Production"

    def test_add_duplicate_is_noop(self, tmp_state):
        state_manager.init_state_dir()
        state_manager.add_protected_record("A", "example.com", "Prod")
        result = state_manager.add_protected_record("A", "example.com", "Different reason")
        assert len(result) == 1  # still just one

    def test_remove_protected_record(self, tmp_state):
        state_manager.init_state_dir()
        state_manager.add_protected_record("A", "example.com", "Prod")
        state_manager.add_protected_record("MX", "example.com", "Mail")
        result = state_manager.remove_protected_record("A", "example.com")
        assert len(result) == 1
        assert result[0]["type"] == "MX"

    def test_remove_nonexistent_is_noop(self, tmp_state):
        state_manager.init_state_dir()
        state_manager.add_protected_record("A", "example.com", "Prod")
        result = state_manager.remove_protected_record("CNAME", "www.example.com")
        assert len(result) == 1  # unchanged

    def test_persistence(self, tmp_state):
        state_manager.init_state_dir()
        state_manager.add_protected_record("A", "example.com", "Prod")
        # Re-read from disk
        loaded = state_manager.load_protected_records()
        assert len(loaded) == 1
        assert loaded[0]["type"] == "A"

    def test_load_corrupted_metadata_returns_empty(self, tmp_state):
        state_manager.init_state_dir()
        (tmp_state / "metadata.json").write_text("not json {{{")
        assert state_manager.load_protected_records() == []

    def test_metadata_preserves_other_fields(self, tmp_state):
        state_manager.init_state_dir()
        # Add a custom field to metadata
        meta = json.loads((tmp_state / "metadata.json").read_text())
        meta["custom_field"] = "preserved"
        (tmp_state / "metadata.json").write_text(json.dumps(meta))

        state_manager.add_protected_record("A", "example.com", "test")
        meta2 = json.loads((tmp_state / "metadata.json").read_text())
        assert meta2["custom_field"] == "preserved"
        assert len(meta2["protected_records"]) == 1


# ------------------------------------------------------------------
# Connection error handling
# ------------------------------------------------------------------

class TestConnectionErrorHandling:
    def test_connection_error_retries_then_raises(self):
        client = CloudflareClient()
        with patch.object(client._session, "request",
                          side_effect=requests.ConnectionError("network down")):
            with patch("core.cloudflare_client.time.sleep"):
                with pytest.raises(CloudflareAPIError, match="Connection failed"):
                    client._request("GET", "/test", "fake-token")

    def test_timeout_error_retries_then_raises(self):
        client = CloudflareClient()
        with patch.object(client._session, "request",
                          side_effect=requests.Timeout("timed out")):
            with patch("core.cloudflare_client.time.sleep"):
                with pytest.raises(CloudflareAPIError, match="timed out"):
                    client._request("GET", "/test", "fake-token")

    def test_connection_error_recovers_on_retry(self):
        client = CloudflareClient()
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"success": True, "result": []}

        with patch.object(
            client._session, "request",
            side_effect=[requests.ConnectionError("down"), ok_resp]
        ):
            with patch("core.cloudflare_client.time.sleep"):
                result = client._request("GET", "/test", "fake-token")
                assert result["success"] is True
