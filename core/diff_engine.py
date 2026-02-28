"""Diff engine — compare DNS record sets and detect changes."""

from dataclasses import dataclass, field

from config import SYSTEM_PROTECTED_TYPES


@dataclass
class DiffResult:
    """Result of comparing two record sets (base → target).

    - ``added``:   records present in *target* but not in *base*
    - ``removed``: records present in *base* but not in *target*
    - ``modified``: records in both but with different content
    - ``unchanged``: records that are identical
    """

    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    modified: list[dict] = field(default_factory=list)  # [{"before": …, "after": …}]
    unchanged: list[dict] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    @property
    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"+{len(self.added)} added")
        if self.removed:
            parts.append(f"-{len(self.removed)} removed")
        if self.modified:
            parts.append(f"~{len(self.modified)} modified")
        return ", ".join(parts) if parts else "No changes"


# ------------------------------------------------------------------
# Record identity & comparison helpers
# ------------------------------------------------------------------

def record_key(record: dict) -> tuple:
    """Composite identity key for a DNS record.

    Used as fallback when Cloudflare record IDs are not available
    (e.g. locally-created records that haven't been pushed yet).
    """
    rtype = record["type"]
    name = record["name"]
    content = record.get("content", "")
    if rtype == "MX":
        return (rtype, name, content, record.get("priority", 0))
    if rtype == "SRV":
        data = record.get("data", {})
        return (rtype, name, record.get("priority", 0),
                data.get("port", 0), data.get("target", ""))
    return (rtype, name, content)


def _comparable(record: dict) -> dict:
    """Extract the fields that matter for equality comparison."""
    result = {
        "type": record["type"],
        "name": record["name"],
        "content": record.get("content", ""),
        "ttl": record.get("ttl", 1),
        "proxied": record.get("proxied", False),
    }
    if record["type"] == "MX":
        result["priority"] = record.get("priority", 0)
    elif record["type"] == "SRV":
        result["priority"] = record.get("priority", 0)
        result["data"] = record.get("data", {})
    return result


def records_equal(a: dict, b: dict) -> bool:
    """Check if two records are semantically equal (ignoring ``id``)."""
    return _comparable(a) == _comparable(b)


# ------------------------------------------------------------------
# Core diff
# ------------------------------------------------------------------

def compute_diff(base: list[dict], target: list[dict]) -> DiffResult:
    """Compute the difference from *base* to *target*.

    Returns:
        A ``DiffResult`` describing what changed *from base to target*:

        - **added** — records in *target* not present in *base*
        - **removed** — records in *base* not present in *target*
        - **modified** — records in both, matched by ``id``, with
          ``before`` = base version, ``after`` = target version
        - **unchanged** — records that are identical

    Matching strategy:
        1. Match by Cloudflare record ``id`` when present.
        2. Fall back to composite key for records without IDs.
    """
    result = DiffResult()

    # Partition by ID availability
    base_by_id: dict[str, dict] = {}
    base_no_id: list[dict] = []
    for r in base:
        rid = r.get("id")
        if rid:
            base_by_id[rid] = r
        else:
            base_no_id.append(r)

    target_by_id: dict[str, dict] = {}
    target_no_id: list[dict] = []
    for r in target:
        rid = r.get("id")
        if rid:
            target_by_id[rid] = r
        else:
            target_no_id.append(r)

    # --- ID-matched records ---
    for rid, base_rec in base_by_id.items():
        if rid in target_by_id:
            target_rec = target_by_id[rid]
            if records_equal(base_rec, target_rec):
                result.unchanged.append(base_rec)
            else:
                result.modified.append({"before": base_rec, "after": target_rec})
        else:
            result.removed.append(base_rec)

    for rid, target_rec in target_by_id.items():
        if rid not in base_by_id:
            result.added.append(target_rec)

    # --- Records without IDs (composite-key matching) ---
    base_key_map = {record_key(r): r for r in base_no_id}
    target_key_map = {record_key(r): r for r in target_no_id}

    for key, rec in target_key_map.items():
        if key not in base_key_map:
            result.added.append(rec)

    for key, rec in base_key_map.items():
        if key not in target_key_map:
            result.removed.append(rec)

    return result


# ------------------------------------------------------------------
# Protection helpers
# ------------------------------------------------------------------

def is_protected(
    record: dict,
    user_protected: list[dict] | None = None,
) -> tuple[bool, str]:
    """Check if a record is protected from modification.

    Returns ``(is_protected, reason)``.
    """
    if record.get("type") in SYSTEM_PROTECTED_TYPES:
        return True, f"System-protected type: {record['type']}"

    if user_protected:
        for p in user_protected:
            if (p.get("type") == record.get("type")
                    and p.get("name") == record.get("name")):
                return True, f"User-protected: {p.get('reason', 'no reason given')}"

    return False, ""
