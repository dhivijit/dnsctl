"""DNS record validation — shared by CLI and GUI."""

import ipaddress

from dnsctl.config import SUPPORTED_RECORD_TYPES


def validate_record(record: dict) -> str | None:
    """Validate a record dict. Returns an error message, or None if valid."""
    rtype = record.get("type", "")
    name = record.get("name", "").strip()
    content = record.get("content", "").strip()

    if not rtype:
        return "Record type is required."
    if rtype not in SUPPORTED_RECORD_TYPES:
        return f"Unsupported record type: {rtype}"
    if not name:
        return "Name is required."
    if not content:
        return "Content is required."

    if rtype == "A":
        try:
            addr = ipaddress.ip_address(content)
            if not isinstance(addr, ipaddress.IPv4Address):
                return "A record content must be a valid IPv4 address."
        except ValueError:
            return "A record content must be a valid IPv4 address."

    if rtype == "AAAA":
        try:
            addr = ipaddress.ip_address(content)
            if not isinstance(addr, ipaddress.IPv6Address):
                return "AAAA record content must be a valid IPv6 address."
        except ValueError:
            return "AAAA record content must be a valid IPv6 address."

    return None
