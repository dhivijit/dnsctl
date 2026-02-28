"""Tests for core.security — encryption roundtrip and session management."""

import time
from unittest.mock import MagicMock, patch

import pytest

from core.security import (
    _decrypt_token,
    _encrypt_token,
    get_token,
    is_logged_in,
    lock,
    login,
    logout,
    unlock,
)


class TestEncryptionRoundtrip:
    def test_roundtrip_succeeds(self):
        token = "my-secret-cloudflare-token"
        password = "strongpassword"
        blob = _encrypt_token(token, password)
        assert _decrypt_token(blob, password) == token

    def test_wrong_password_fails(self):
        token = "my-secret-cloudflare-token"
        blob = _encrypt_token(token, "correct-password")
        with pytest.raises(Exception):
            _decrypt_token(blob, "wrong-password")

    def test_different_passwords_produce_different_blobs(self):
        token = "token123"
        b1 = _encrypt_token(token, "pass1___")
        b2 = _encrypt_token(token, "pass2___")
        assert b1 != b2


class TestLoginUnlock:
    @patch("core.security.keyring")
    def test_login_stores_blob(self, mock_kr):
        login("tok123", "password")
        mock_kr.set_password.assert_called_once()
        service, user, blob = mock_kr.set_password.call_args[0]
        assert service == "dnsctl_encrypted_token"
        assert user == "dnsctl"
        assert len(blob) > 0

    @patch("core.security.keyring")
    def test_is_logged_in_true(self, mock_kr):
        mock_kr.get_password.return_value = "something"
        assert is_logged_in() is True

    @patch("core.security.keyring")
    def test_is_logged_in_false(self, mock_kr):
        mock_kr.get_password.return_value = None
        assert is_logged_in() is False


class TestSession:
    @patch("core.security.keyring")
    @patch("core.security.SESSION_FILE")
    def test_get_token_returns_none_when_no_session_file(self, mock_sf, mock_kr):
        mock_sf.exists.return_value = False
        assert get_token() is None

    @patch("core.security.keyring")
    @patch("core.security.SESSION_FILE")
    def test_lock_clears_session(self, mock_sf, mock_kr):
        mock_sf.exists.return_value = True
        lock()
        mock_sf.unlink.assert_called_once()
