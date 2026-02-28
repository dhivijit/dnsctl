"""dnsctl — Application-wide constants and path configuration."""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Runtime state directory  (~/.dnsctl/)
# ---------------------------------------------------------------------------
STATE_DIR = Path(os.environ.get("DNSCTL_STATE_DIR", Path.home() / ".dnsctl"))
ZONES_DIR = STATE_DIR / "zones"
LOGS_DIR = STATE_DIR / "logs"
LOG_FILE = LOGS_DIR / "dnsctl.log"
METADATA_FILE = STATE_DIR / "metadata.json"
CONFIG_FILE = STATE_DIR / "config.json"
SESSION_FILE = STATE_DIR / ".session"
GITIGNORE_FILE = STATE_DIR / ".gitignore"

# ---------------------------------------------------------------------------
# Cloudflare API
# ---------------------------------------------------------------------------
CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"

# ---------------------------------------------------------------------------
# Supported DNS record types
# ---------------------------------------------------------------------------
SUPPORTED_RECORD_TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "SRV")

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
KEYRING_SERVICE_ENCRYPTED = "dnsctl_encrypted_token"
KEYRING_SERVICE_SESSION = "dnsctl_session"
KEYRING_USERNAME = "dnsctl"
PBKDF2_ITERATIONS = 200_000
SESSION_TIMEOUT_SECONDS = 15 * 60  # 15 minutes

# ---------------------------------------------------------------------------
# System-level protected record types (cannot modify without --force)
# ---------------------------------------------------------------------------
SYSTEM_PROTECTED_TYPES = {"NS"}

# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------
GIT_AUTHOR_NAME = "dnsctl"
GIT_AUTHOR_EMAIL = "dnsctl@localhost"
