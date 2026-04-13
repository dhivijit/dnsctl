"""Shared commit message builders — used by CLI, GUI, and TUI.

Every function returns a string in standard git format:
    <subject line>

    <detail body>

Old commits that pre-date this module only have a subject line, so all
callers that read ``log()`` must handle a body-less message gracefully.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_ttl(ttl) -> str:
    return "Auto" if ttl == 1 else str(ttl)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def sync_message(zone_counts: list[tuple[str, int]]) -> str:
    """Commit message for a sync operation.

    *zone_counts* is a list of ``(zone_name, record_count)`` tuples.
    """
    total = sum(n for _, n in zone_counts)
    now = _now_utc()

    if len(zone_counts) == 1:
        zone_name, n = zone_counts[0]
        subject = f"Sync {zone_name} ({n} records)"
        body = f"synced {n} records from Cloudflare at {now}"
    else:
        subject = f"Sync {len(zone_counts)} zone(s) ({total} records)"
        body_lines = [f"synced from Cloudflare at {now}"]
        for zname, n in zone_counts:
            body_lines.append(f"  {zname}: {n} records")
        body = "\n".join(body_lines)

    return f"{subject}\n\n{body}"


# ---------------------------------------------------------------------------
# Record CRUD
# ---------------------------------------------------------------------------

def add_record_message(record: dict, zone_name: str) -> str:
    """Commit message for adding a record to local state."""
    rtype = record.get("type", "")
    name = record.get("name", "")
    content = record.get("content", "")
    ttl = _fmt_ttl(record.get("ttl", 1))
    extras: list[str] = []
    if record.get("proxied"):
        extras.append("proxied=yes")
    if record.get("priority") is not None:
        extras.append(f"priority={record['priority']}")

    subject = f"Add {rtype} {name} in {zone_name}"
    body = f"+ {rtype}  {name}  {content}  ttl={ttl}"
    if extras:
        body += "  " + "  ".join(extras)
    return f"{subject}\n\n{body}"


def edit_record_message(old: dict, new: dict, zone_name: str) -> str:
    """Commit message for editing a record — shows only changed fields."""
    rtype = new.get("type", "")
    name = new.get("name", "")
    subject = f"Edit {rtype} {name} in {zone_name}"

    lines: list[str] = []
    for field, label in [
        ("name", "name"),
        ("content", "content"),
        ("ttl", "ttl"),
        ("proxied", "proxied"),
        ("priority", "priority"),
    ]:
        old_val = old.get(field)
        new_val = new.get(field)
        if old_val != new_val:
            if field == "ttl":
                old_val = _fmt_ttl(old_val)
                new_val = _fmt_ttl(new_val)
            lines.append(f"  {label}: {old_val} → {new_val}")

    if not lines:
        lines = ["  (no field changes — metadata only)"]

    return f"{subject}\n\n" + "\n".join(lines)


def delete_record_message(record: dict, zone_name: str) -> str:
    """Commit message for deleting a record from local state."""
    rtype = record.get("type", "")
    name = record.get("name", "")
    content = record.get("content", "")
    ttl = _fmt_ttl(record.get("ttl", 1))
    subject = f"Delete {rtype} {name} in {zone_name}"
    body = f"- {rtype}  {name}  {content}  ttl={ttl}"
    return f"{subject}\n\n{body}"


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_message(zone_name: str, n_records: int) -> str:
    """Commit message for importing a zone state from a file."""
    subject = f"Import {zone_name} ({n_records} records)"
    body = f"imported {n_records} records from file at {_now_utc()}"
    return f"{subject}\n\n{body}"
