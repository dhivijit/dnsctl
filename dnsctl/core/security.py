"""Secure token storage — AES-256-GCM + PBKDF2 + OS keyring.

All public functions accept an *alias* parameter identifying which
Cloudflare account the credential belongs to.  Account credentials are
stored in the OS keyring under ``<alias>`` as the username, and the
per-account session file lives at ``~/.dnsctl/accounts/<alias>/.session``.
"""

import base64
import json
import os
import time
from pathlib import Path

import keyring
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from dnsctl.config import (
    ACCOUNTS_DIR,
    KEYRING_SERVICE_ENCRYPTED,
    KEYRING_SERVICE_SESSION,
    PBKDF2_ITERATIONS,
    SESSION_TIMEOUT_SECONDS,
)

# ---------------------------------------------------------------------------
# In-memory password cache (cleared on lock/logout, never written to disk)
# ---------------------------------------------------------------------------
_session_passwords: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit key from *password* and *salt* using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


# ---------------------------------------------------------------------------
# Encrypt / Decrypt
# ---------------------------------------------------------------------------

def _encrypt_token(token: str, password: str) -> str:
    """Encrypt *token* with AES-256-GCM.  Returns a base64-encoded JSON blob
    containing salt, nonce, and ciphertext."""
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, token.encode("utf-8"), None)
    blob = {
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ciphertext).decode(),
    }
    return base64.b64encode(json.dumps(blob).encode()).decode()


def _decrypt_token(encoded_blob: str, password: str) -> str:
    """Decrypt *encoded_blob* with *password*.  Raises on wrong password."""
    blob = json.loads(base64.b64decode(encoded_blob))
    salt = base64.b64decode(blob["salt"])
    nonce = base64.b64decode(blob["nonce"])
    ct = base64.b64decode(blob["ct"])
    key = _derive_key(password, salt)
    plaintext = AESGCM(key).decrypt(nonce, ct, None)
    return plaintext.decode("utf-8")


# ---------------------------------------------------------------------------
# Per-account session file helper
# ---------------------------------------------------------------------------

def _account_session_file(alias: str) -> Path:
    """Return the path to the session timestamp file for *alias*."""
    return ACCOUNTS_DIR / alias / ".session"


def get_cached_password(alias: str) -> str | None:
    """Return the in-memory cached master password for *alias*, if available.

    The password is cached after a successful ``login()`` or ``unlock()`` call
    and is cleared when the session is locked or the credentials are removed.
    It is never persisted to disk.
    """
    return _session_passwords.get(alias)


# ---------------------------------------------------------------------------
# Login — store encrypted token in keyring
# ---------------------------------------------------------------------------

def login(token: str, password: str, alias: str) -> None:
    """Encrypt *token* and persist the blob in the OS keyring for *alias*."""
    blob = _encrypt_token(token, password)
    keyring.set_password(KEYRING_SERVICE_ENCRYPTED, alias, blob)
    _session_passwords[alias] = password
    # Clear any stale session for this account
    _clear_session(alias)


def is_logged_in(alias: str) -> bool:
    """Return True if an encrypted token blob exists in the keyring for *alias*."""
    return keyring.get_password(KEYRING_SERVICE_ENCRYPTED, alias) is not None


# ---------------------------------------------------------------------------
# Unlock — decrypt and cache token for SESSION_TIMEOUT_SECONDS
# ---------------------------------------------------------------------------

def unlock(password: str, alias: str) -> str:
    """Decrypt the stored token for *alias* and cache it for the session.

    Returns the plaintext token.  Raises ``ValueError`` if not logged in,
    or ``cryptography`` exceptions on wrong password.
    """
    blob = keyring.get_password(KEYRING_SERVICE_ENCRYPTED, alias)
    if blob is None:
        raise ValueError(f"Not logged in for account '{alias}'. Run 'dnsctl login' first.")

    token = _decrypt_token(blob, password)

    # Cache the token in a separate session keyring entry
    keyring.set_password(KEYRING_SERVICE_SESSION, alias, token)
    _session_passwords[alias] = password
    _touch_session(alias)
    return token


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _touch_session(alias: str) -> None:
    """Write current Unix timestamp to the session file for *alias*."""
    f = _account_session_file(alias)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(str(time.time()))


def _clear_session(alias: str) -> None:
    """Remove session token from keyring and delete session file for *alias*."""
    try:
        keyring.delete_password(KEYRING_SERVICE_SESSION, alias)
    except keyring.errors.PasswordDeleteError:
        pass
    f = _account_session_file(alias)
    if f.exists():
        f.unlink()


def get_token(alias: str) -> str | None:
    """Return the cached plaintext token for *alias* if the session is still
    valid, otherwise clear the session and return ``None``."""
    f = _account_session_file(alias)
    if not f.exists():
        return None
    try:
        ts = float(f.read_text().strip())
    except (ValueError, OSError):
        _clear_session(alias)
        return None

    if time.time() - ts > SESSION_TIMEOUT_SECONDS:
        _clear_session(alias)
        return None

    token = keyring.get_password(KEYRING_SERVICE_SESSION, alias)
    if token is None:
        _clear_session(alias)
        return None

    # Refresh the timestamp on each successful access
    _touch_session(alias)
    return token


def unlock_all(password: str, aliases: list[str]) -> list[str]:
    """Unlock every alias in *aliases* using *password*.

    Silently skips any account where the password doesn't work (e.g. a
    different password was used when that account was created).  Returns
    the list of aliases that were successfully unlocked.
    """
    succeeded: list[str] = []
    for alias in aliases:
        try:
            unlock(password, alias)
            succeeded.append(alias)
        except Exception:
            pass
    return succeeded


def lock(alias: str) -> None:
    """Explicitly lock the session for *alias*."""
    _session_passwords.pop(alias, None)
    _clear_session(alias)


def logout(alias: str) -> None:
    """Remove all stored credentials for *alias*."""
    _session_passwords.pop(alias, None)
    _clear_session(alias)
    try:
        keyring.delete_password(KEYRING_SERVICE_ENCRYPTED, alias)
    except keyring.errors.PasswordDeleteError:
        pass
