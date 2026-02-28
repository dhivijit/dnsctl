"""Tests for core.cloudflare_client — API interactions with mocked responses."""

from unittest.mock import MagicMock, patch

import pytest

from core.cloudflare_client import CloudflareClient, CloudflareAPIError, _normalize_record


class TestNormalizeRecord:
    def test_a_record(self):
        raw = {
            "id": "r1", "type": "A", "name": "example.com",
            "content": "1.2.3.4", "ttl": 300, "proxied": True,
        }
        rec = _normalize_record(raw)
        assert rec["id"] == "r1"
        assert rec["type"] == "A"
        assert rec["proxied"] is True
        assert "priority" not in rec

    def test_mx_record_includes_priority(self):
        raw = {
            "id": "r2", "type": "MX", "name": "example.com",
            "content": "mail.example.com", "ttl": 1, "priority": 10,
        }
        rec = _normalize_record(raw)
        assert rec["priority"] == 10

    def test_srv_record_includes_data(self):
        raw = {
            "id": "r3", "type": "SRV", "name": "_sip._tcp.example.com",
            "content": "0 5060 sip.example.com", "ttl": 1,
            "priority": 0,
            "data": {"weight": 10, "port": 5060, "target": "sip.example.com",
                     "service": "_sip", "proto": "_tcp", "name": "example.com", "priority": 0},
        }
        rec = _normalize_record(raw)
        assert rec["data"]["port"] == 5060
        assert rec["data"]["target"] == "sip.example.com"


class TestCloudflareClient:
    def _mock_response(self, json_data, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.headers = {}
        return resp

    @patch("core.cloudflare_client.requests.Session")
    def test_list_zones(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_session.request.return_value = self._mock_response({
            "success": True,
            "result": [
                {"id": "z1", "name": "example.com", "status": "active"},
                {"id": "z2", "name": "test.dev", "status": "active"},
            ],
            "result_info": {"total_pages": 1},
        })

        client = CloudflareClient()
        zones = client.list_zones("fake-token")
        assert len(zones) == 2
        assert zones[0]["name"] == "example.com"

    @patch("core.cloudflare_client.requests.Session")
    def test_list_records_filters_unsupported(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_session.request.return_value = self._mock_response({
            "success": True,
            "result": [
                {"id": "r1", "type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 1},
                {"id": "r2", "type": "NS", "name": "x.com", "content": "ns1.x.com", "ttl": 1},
            ],
            "result_info": {"total_pages": 1},
        })

        client = CloudflareClient()
        records = client.list_records("fake-token", "z1")
        # NS should be filtered out
        assert len(records) == 1
        assert records[0]["type"] == "A"

    @patch("core.cloudflare_client.requests.Session")
    def test_api_error_raised(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_session.request.return_value = self._mock_response(
            {"success": False, "errors": [{"message": "Invalid token"}]},
            status_code=403,
        )

        client = CloudflareClient()
        with pytest.raises(CloudflareAPIError, match="Invalid token"):
            client.list_zones("bad-token")
