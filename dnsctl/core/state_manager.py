"""State manager — initialise state directory, load/save zone JSON, export/import.

Multi-account layout (v2):
  ~/.dnsctl/
    accounts.json                  list of {alias, label}
    config.json                    {default_account, default_zone_<alias>, ...}
    accounts/
      <alias>/
        zones/  <name>.json
        .gitignore
        .session                   (per-account, excluded from git)
    metadata.json                  (shared protected records)
    logs/
"""

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dnsctl.config import (
    ACCOUNTS_DIR,
    ACCOUNTS_FILE,
    LOGS_DIR,
    METADATA_FILE,
    CONFIG_FILE,
    STATE_DIR,
    _LEGACY_ZONES_DIR,
    KEYRING_SERVICE_ENCRYPTED,
    KEYRING_SERVICE_SESSION,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def slugify(label: str) -> str:
    """Convert a display label into a filesystem-safe alias.

    Examples: ``'My Work Account'`` → ``'my_work_account'``
    """
    slug = re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')
    return slug or "account"


# ------------------------------------------------------------------
# Initialisation
# ------------------------------------------------------------------

def init_state_dir() -> Path:
    """Create the ``~/.dnsctl/`` directory tree and run migration.  Idempotent.

    Returns the state directory path.
    """
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Ensure metadata.json exists
    if not METADATA_FILE.exists():
        METADATA_FILE.write_text(json.dumps({"protected_records": []}, indent=2))

    # Ensure config.json exists
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps({}, indent=2))

    # Migrate from legacy single-account layout (idempotent)
    _migrate_legacy()

    return STATE_DIR


def _migrate_legacy() -> None:
    """Migrate from the legacy single-account layout to the multi-account layout.

    Idempotent: if ``accounts.json`` already exists, this is a no-op.

    What it does:
    * Moves ``~/.dnsctl/zones/*.json`` → ``accounts/default/zones/``
    * Copies the keyring blob from username ``"dnsctl"`` to ``"default"``
    * Moves ``.session`` → ``accounts/default/.session``
    * Writes ``accounts.json``
    * Updates ``config.json`` (renames ``default_zone`` key)
    """
    if ACCOUNTS_FILE.exists():
        return  # already migrated

    import keyring as _keyring

    default_dir = ACCOUNTS_DIR / "default"
    default_zones_dir = default_dir / "zones"
    default_zones_dir.mkdir(parents=True, exist_ok=True)

    # Move legacy zone files
    has_zone_files = False
    if _LEGACY_ZONES_DIR.exists():
        for zone_file in list(_LEGACY_ZONES_DIR.glob("*.json")):
            shutil.move(str(zone_file), str(default_zones_dir / zone_file.name))
            has_zone_files = True
        try:
            _LEGACY_ZONES_DIR.rmdir()  # only removes if now empty
        except OSError:
            pass

    # Copy keyring blob from old "dnsctl" username to "default"
    old_blob = _keyring.get_password(KEYRING_SERVICE_ENCRYPTED, "dnsctl")
    if old_blob:
        _keyring.set_password(KEYRING_SERVICE_ENCRYPTED, "default", old_blob)
        try:
            _keyring.delete_password(KEYRING_SERVICE_ENCRYPTED, "dnsctl")
        except Exception:
            pass

    # Copy legacy session from old location
    legacy_session_file = STATE_DIR / ".session"
    new_session_file = default_dir / ".session"
    if legacy_session_file.exists():
        shutil.copy2(str(legacy_session_file), str(new_session_file))
        legacy_session_file.unlink()
    # Copy session keyring blob
    old_session_token = _keyring.get_password(KEYRING_SERVICE_SESSION, "dnsctl")
    if old_session_token:
        _keyring.set_password(KEYRING_SERVICE_SESSION, "default", old_session_token)
        try:
            _keyring.delete_password(KEYRING_SERVICE_SESSION, "dnsctl")
        except Exception:
            pass

    # Write per-account .gitignore
    gitignore = default_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# dnsctl \u2014 per-account files excluded\n.session\nlogs/\n")

    # Determine whether a default account should be registered
    has_credentials = old_blob is not None
    has_data = has_zone_files or has_credentials
    accounts: list[dict] = []
    if has_data:
        accounts = [{"alias": "default", "label": "Default"}]

    ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2), encoding="utf-8")

    # Update config.json: rename default_zone → default_zone_default, set default_account
    cfg = get_config()
    new_cfg: dict[str, Any] = {}
    for k, v in cfg.items():
        if k == "default_zone":
            new_cfg["default_zone_default"] = v
        else:
            new_cfg[k] = v
    if has_data:
        new_cfg["default_account"] = "default"
    CONFIG_FILE.write_text(json.dumps(new_cfg, indent=2), encoding="utf-8")


# ------------------------------------------------------------------
# Account management
# ------------------------------------------------------------------

def list_accounts() -> list[dict]:
    """Return the list of registered accounts from ``accounts.json``.

    Each entry is ``{"alias": str, "label": str}``.
    """
    if not ACCOUNTS_FILE.exists():
        return []
    try:
        return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def add_account(alias: str, label: str) -> dict:
    """Register a new account and create its directory structure.

    Returns the new account dict ``{"alias": alias, "label": label}``.
    Does **not** store credentials — call ``security.login()`` afterwards.
    """
    account_dir = ACCOUNTS_DIR / alias
    (account_dir / "zones").mkdir(parents=True, exist_ok=True)

    # Per-account .gitignore (excludes the session timestamp file)
    gitignore = account_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# dnsctl \u2014 per-account files excluded\n.session\n")

    accounts = list_accounts()
    if not any(a["alias"] == alias for a in accounts):
        accounts.append({"alias": alias, "label": label})
        ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2), encoding="utf-8")

    return {"alias": alias, "label": label}


def remove_account(alias: str) -> None:
    """Delete an account's directory and remove it from ``accounts.json``.

    Does **not** clear credentials from the keyring — call
    ``security.logout()`` before calling this.
    """
    def _force_remove(func, path, _exc):
        # Git marks object files read-only on Windows; clear the bit and retry.
        import stat
        os.chmod(path, stat.S_IWRITE)
        func(path)

    account_dir = ACCOUNTS_DIR / alias
    if account_dir.exists():
        shutil.rmtree(account_dir, onexc=_force_remove)

    accounts = [a for a in list_accounts() if a["alias"] != alias]
    ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2), encoding="utf-8")

    # Clean up per-account config keys
    cfg = get_config()
    keys_to_remove = [k for k in cfg if k.endswith(f"_{alias}")]
    for k in keys_to_remove:
        del cfg[k]
    if cfg.get("default_account") == alias:
        del cfg["default_account"]
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_current_account() -> str | None:
    """Return the alias of the currently-selected account, or ``None``."""
    return get_config().get("default_account")


def set_current_account(alias: str) -> None:
    """Set the currently-selected account by alias."""
    set_config("default_account", alias)


def get_account_dir(alias: str) -> Path:
    """Return the directory path for *alias*."""
    return ACCOUNTS_DIR / alias


def get_account_zones_dir(alias: str) -> Path:
    """Return the zones directory path for *alias*."""
    return ACCOUNTS_DIR / alias / "zones"


# ------------------------------------------------------------------
# Zone state persistence
# ------------------------------------------------------------------

def _zone_path(zone_name: str, alias: str) -> Path:
    return get_account_zones_dir(alias) / f"{zone_name}.json"


def load_zone(zone_name: str, alias: str) -> dict | None:
    """Load zone state from disk for *alias*.  Returns ``None`` if not synced yet."""
    path = _zone_path(zone_name, alias)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_zone(zone_id: str, zone_name: str, records: list[dict], alias: str) -> dict:
    """Persist zone state to ``~/.dnsctl/accounts/<alias>/zones/<name>.json``.

    If the records haven't changed since the last save (same hash),
    the file is **not** rewritten so git sees no diff.

    Returns the saved state dict (including computed hash).
    """
    new_hash = _compute_hash(records)

    # Skip rewrite if records are identical (avoids timestamp-only diffs)
    existing = load_zone(zone_name, alias)
    if existing and existing.get("state_hash") == new_hash:
        return existing

    state = {
        "zone_id": zone_id,
        "zone_name": zone_name,
        "records": records,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
        "state_hash": _compute_hash(records),
    }
    path = _zone_path(zone_name, alias)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def list_synced_zones(alias: str) -> list[str]:
    """Return a list of zone names synced locally for *alias*."""
    zones_dir = get_account_zones_dir(alias)
    if not zones_dir.exists():
        return []
    return sorted(p.stem for p in zones_dir.glob("*.json"))


# ------------------------------------------------------------------
# Config helpers
# ------------------------------------------------------------------

def get_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def set_config(key: str, value: Any) -> None:
    cfg = get_config()
    cfg[key] = value
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ------------------------------------------------------------------
# Hashing
# ------------------------------------------------------------------

def _compute_hash(records: list[dict]) -> str:
    """Deterministic SHA-256 hash of the records list."""
    sorted_records = sorted(records, key=lambda r: (r.get("type", ""), r.get("name", ""), r.get("content", "")))
    canonical = json.dumps(sorted_records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------
# Export / Import
# ------------------------------------------------------------------

def export_zone(zone_name: str, dest: Path, alias: str) -> Path:
    """Export a zone's state for *alias* to *dest* as a standalone JSON file.

    Raises ``FileNotFoundError`` if the zone hasn't been synced.
    Returns the written path.
    """
    state = load_zone(zone_name, alias)
    if state is None:
        raise FileNotFoundError(f"Zone '{zone_name}' has not been synced yet.")
    dest.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return dest


def import_zone(src: Path, alias: str) -> dict:
    """Import zone state from a JSON file and save it into *alias*'s directory.

    The file must contain ``zone_id``, ``zone_name``, and ``records``.
    Returns the saved state dict.

    Raises ``ValueError`` for invalid files.
    """
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Cannot read import file: {exc}") from exc

    zone_id = data.get("zone_id")
    zone_name = data.get("zone_name")
    records = data.get("records")

    if not zone_id or not zone_name or records is None:
        raise ValueError(
            "Import file must contain 'zone_id', 'zone_name', and 'records'."
        )
    if not isinstance(records, list):
        raise ValueError("'records' must be a list.")

    return save_zone(zone_id, zone_name, records, alias)


# ------------------------------------------------------------------
# Protected records management
# ------------------------------------------------------------------

def load_protected_records() -> list[dict]:
    """Return the list of user-defined protected records from metadata.json."""
    if not METADATA_FILE.exists():
        return []
    try:
        data = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        return data.get("protected_records", [])
    except (json.JSONDecodeError, OSError):
        return []


def add_protected_record(rtype: str, name: str, reason: str = "") -> list[dict]:
    """Add a record to the protected list. Returns the updated list."""
    protected = load_protected_records()
    # Don't add duplicates
    for p in protected:
        if p.get("type") == rtype and p.get("name") == name:
            return protected
    protected.append({"type": rtype, "name": name, "reason": reason})
    _save_metadata(protected)
    return protected


def remove_protected_record(rtype: str, name: str) -> list[dict]:
    """Remove a record from the protected list. Returns the updated list."""
    protected = load_protected_records()
    protected = [p for p in protected
                 if not (p.get("type") == rtype and p.get("name") == name)]
    _save_metadata(protected)
    return protected


def _save_metadata(protected: list[dict]) -> None:
    """Write the protected records list back to metadata.json."""
    data: dict = {}
    if METADATA_FILE.exists():
        try:
            data = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data["protected_records"] = protected
    METADATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
