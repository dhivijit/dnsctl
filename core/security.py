"""Secure token storage — AES-256-GCM + PBKDF2 + OS keyring."""

import base64
import json
import os
import time

import keyring
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from config import (
    KEYRING_SERVICE_ENCRYPTED,
    KEYRING_SERVICE_SESSION,
    KEYRING_USERNAME,
    PBKDF2_ITERATIONS,
    SESSION_FILE,
    SESSION_TIMEOUT_SECONDS,
)


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
# Login — store encrypted token in keyring
# ---------------------------------------------------------------------------

def login(token: str, password: str) -> None:
    """Encrypt *token* and persist the blob in the OS keyring."""
    blob = _encrypt_token(token, password)
    keyring.set_password(KEYRING_SERVICE_ENCRYPTED, KEYRING_USERNAME, blob)
    # Clear any stale session
    _clear_session()


def is_logged_in() -> bool:
    """Return True if an encrypted token blob exists in the keyring."""
    return keyring.get_password(KEYRING_SERVICE_ENCRYPTED, KEYRING_USERNAME) is not None


# ---------------------------------------------------------------------------
# Unlock — decrypt and cache token for SESSION_TIMEOUT_SECONDS
# ---------------------------------------------------------------------------

def unlock(password: str) -> str:
    """Decrypt the stored token and cache it in the session keyring entry.

    Returns the plaintext token.  Raises ``ValueError`` if not logged in,
    or ``cryptography`` exceptions on wrong password.
    """
    blob = keyring.get_password(KEYRING_SERVICE_ENCRYPTED, KEYRING_USERNAME)
    if blob is None:
        raise ValueError("Not logged in. Run 'dnscli login' first.")

    token = _decrypt_token(blob, password)

    # Cache the token in a separate session keyring entry
    keyring.set_password(KEYRING_SERVICE_SESSION, KEYRING_USERNAME, token)
    _touch_session()
    return token


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _touch_session() -> None:
    """Write current Unix timestamp to the session file."""
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(str(time.time()))


def _clear_session() -> None:
    """Remove session token from keyring and delete session file."""
    try:
        keyring.delete_password(KEYRING_SERVICE_SESSION, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def get_token() -> str | None:
    """Return the cached plaintext token if the session is still valid,
    otherwise clear the session and return ``None``."""
    if not SESSION_FILE.exists():
        return None
    try:
        ts = float(SESSION_FILE.read_text().strip())
    except (ValueError, OSError):
        _clear_session()
        return None

    if time.time() - ts > SESSION_TIMEOUT_SECONDS:
        _clear_session()
        return None

    token = keyring.get_password(KEYRING_SERVICE_SESSION, KEYRING_USERNAME)
    if token is None:
        _clear_session()
        return None

    # Refresh the timestamp on each successful access
    _touch_session()
    return token


def lock() -> None:
    """Explicitly lock the session."""
    _clear_session()


def logout() -> None:
    """Remove all stored credentials."""
    _clear_session()
    try:
        keyring.delete_password(KEYRING_SERVICE_ENCRYPTED, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
