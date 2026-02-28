"""Tests for record editor validation and CLI record CRUD."""

import pytest

from gui.controllers.record_editor_controller import validate_record


class TestValidateRecord:
    def test_valid_a_record(self):
        rec = {"type": "A", "name": "x.com", "content": "1.2.3.4", "ttl": 300}
        assert validate_record(rec) is None

    def test_valid_aaaa_record(self):
        rec = {"type": "AAAA", "name": "x.com", "content": "2001:db8::1", "ttl": 1}
        assert validate_record(rec) is None

    def test_valid_cname_record(self):
        rec = {"type": "CNAME", "name": "www.x.com", "content": "x.com", "ttl": 1}
        assert validate_record(rec) is None

    def test_valid_mx_record(self):
        rec = {"type": "MX", "name": "x.com", "content": "mail.x.com", "ttl": 1, "priority": 10}
        assert validate_record(rec) is None

    def test_valid_txt_record(self):
        rec = {"type": "TXT", "name": "x.com", "content": "v=spf1 include:_spf.google.com ~all", "ttl": 1}
        assert validate_record(rec) is None

    def test_missing_type(self):
        rec = {"type": "", "name": "x.com", "content": "1.2.3.4"}
        assert validate_record(rec) is not None

    def test_missing_name(self):
        rec = {"type": "A", "name": "", "content": "1.2.3.4"}
        assert validate_record(rec) is not None

    def test_missing_content(self):
        rec = {"type": "A", "name": "x.com", "content": ""}
        assert validate_record(rec) is not None

    def test_invalid_a_content(self):
        rec = {"type": "A", "name": "x.com", "content": "not-an-ip"}
        err = validate_record(rec)
        assert err is not None
        assert "IPv4" in err

    def test_invalid_aaaa_content(self):
        rec = {"type": "AAAA", "name": "x.com", "content": "1.2.3.4"}
        err = validate_record(rec)
        assert err is not None
        assert "IPv6" in err

    def test_unsupported_type(self):
        rec = {"type": "NS", "name": "x.com", "content": "ns1.x.com"}
        err = validate_record(rec)
        assert err is not None
        assert "Unsupported" in err

    def test_valid_srv_record(self):
        rec = {"type": "SRV", "name": "_sip._tcp.x.com", "content": "sip.x.com", "priority": 0}
        assert validate_record(rec) is None
