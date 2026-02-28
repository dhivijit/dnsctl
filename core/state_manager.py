"""State manager — initialise state directory, load/save zone JSON, export/import."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    GITIGNORE_FILE,
    LOGS_DIR,
    METADATA_FILE,
    CONFIG_FILE,
    STATE_DIR,
    ZONES_DIR,
)


# ------------------------------------------------------------------
# Initialisation
# ------------------------------------------------------------------

def init_state_dir() -> Path:
    """Create the ``~/.dnsctl/`` directory tree.  Idempotent.

    Returns the state directory path.
    """
    ZONES_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Ensure metadata.json exists
    if not METADATA_FILE.exists():
        METADATA_FILE.write_text(json.dumps({"protected_records": []}, indent=2))

    # Ensure config.json exists
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps({"default_zone": None}, indent=2))

    # .gitignore — keep session file and logs out of version control
    if not GITIGNORE_FILE.exists():
        GITIGNORE_FILE.write_text(
            "# dnsctl — files excluded from git tracking\n"
            ".session\n"
            "logs/\n"
        )

    return STATE_DIR


# ------------------------------------------------------------------
# Zone state persistence
# ------------------------------------------------------------------

def _zone_path(zone_name: str) -> Path:
    return ZONES_DIR / f"{zone_name}.json"


def load_zone(zone_name: str) -> dict | None:
    """Load zone state from disk.  Returns ``None`` if not synced yet."""
    path = _zone_path(zone_name)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_zone(zone_id: str, zone_name: str, records: list[dict]) -> dict:
    """Persist zone state to ``~/.dnsctl/zones/<zone_name>.json``.

    If the records haven't changed since the last save (same hash),
    the file is **not** rewritten so git sees no diff.

    Returns the saved state dict (including computed hash).
    """
    new_hash = _compute_hash(records)

    # Skip rewrite if records are identical (avoids timestamp-only diffs)
    existing = load_zone(zone_name)
    if existing and existing.get("state_hash") == new_hash:
        return existing

    state = {
        "zone_id": zone_id,
        "zone_name": zone_name,
        "records": records,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
        "state_hash": _compute_hash(records),
    }
    path = _zone_path(zone_name)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def list_synced_zones() -> list[str]:
    """Return a list of zone names that have been synced locally."""
    if not ZONES_DIR.exists():
        return []
    return sorted(p.stem for p in ZONES_DIR.glob("*.json"))


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
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------
# Export / Import
# ------------------------------------------------------------------

def export_zone(zone_name: str, dest: Path) -> Path:
    """Export a zone's state to *dest* as a standalone JSON file.

    Raises ``FileNotFoundError`` if the zone hasn't been synced.
    Returns the written path.
    """
    state = load_zone(zone_name)
    if state is None:
        raise FileNotFoundError(f"Zone '{zone_name}' has not been synced yet.")
    dest.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return dest


def import_zone(src: Path) -> dict:
    """Import zone state from a JSON file and save it into the state directory.

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

    return save_zone(zone_id, zone_name, records)
