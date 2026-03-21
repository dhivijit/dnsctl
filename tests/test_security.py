"""Tests for core.security — encryption roundtrip and session management."""

import time
from unittest.mock import MagicMock, patch

import pytest

from dnsctl.core.security import (
    _decrypt_token,
    _encrypt_token,
    get_token,
    is_logged_in,
    lock,
    login,
    logout,
    unlock,
)

_ALIAS = "test_acct"


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
    @patch("dnsctl.core.security.keyring")
    def test_login_stores_blob(self, mock_kr):
        # _clear_session tries to delete session keyring entry — let it fail silently
        mock_kr.errors = MagicMock()
        mock_kr.errors.PasswordDeleteError = Exception
        login("tok123", "password", _ALIAS)
        mock_kr.set_password.assert_called_once()
        service, user, blob = mock_kr.set_password.call_args[0]
        assert service == "dnsctl_encrypted_token"
        assert user == _ALIAS
        assert len(blob) > 0

    @patch("dnsctl.core.security.keyring")
    def test_is_logged_in_true(self, mock_kr):
        mock_kr.get_password.return_value = "something"
        assert is_logged_in(_ALIAS) is True

    @patch("dnsctl.core.security.keyring")
    def test_is_logged_in_false(self, mock_kr):
        mock_kr.get_password.return_value = None
        assert is_logged_in(_ALIAS) is False


class TestSession:
    @patch("dnsctl.core.security.keyring")
    def test_get_token_returns_none_when_no_session_file(self, mock_kr, tmp_path):
        with patch("dnsctl.core.security._account_session_file",
                   return_value=tmp_path / "nonexistent.session"):
            assert get_token(_ALIAS) is None

    @patch("dnsctl.core.security.keyring")
    def test_lock_clears_session(self, mock_kr, tmp_path):
        mock_kr.errors = MagicMock()
        mock_kr.errors.PasswordDeleteError = Exception
        session_file = tmp_path / ".session"
        session_file.touch()
        with patch("dnsctl.core.security._account_session_file",
                   return_value=session_file):
            lock(_ALIAS)
        assert not session_file.exists()
