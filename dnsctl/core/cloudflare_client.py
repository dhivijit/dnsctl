"""Cloudflare API client — zone and DNS record operations."""

import logging
import re
import time
from typing import Any

import requests

from dnsctl.config import CLOUDFLARE_API_BASE, SUPPORTED_RECORD_TYPES

logger = logging.getLogger(__name__)

# Maximum retries on 429 (rate-limited) responses
_MAX_RETRIES = 5
_BACKOFF_BASE = 1.0  # seconds

# Cloudflare API tokens are 40-char alphanumeric strings with hyphens/underscores
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{20,}$")


class CloudflareAPIError(Exception):
    """Raised when a Cloudflare API call fails."""

    def __init__(self, status_code: int, errors: list[dict]):
        self.status_code = status_code
        self.errors = errors
        messages = "; ".join(e.get("message", str(e)) for e in errors)
        super().__init__(f"Cloudflare API error ({status_code}): {messages}")


def sanitize_token(raw: str) -> str:
    """Extract a clean API token from user input.

    Users sometimes paste the full curl command or a ``Bearer <token>`` string.
    This helper strips common prefixes/wrapping and validates the result.

    Raises ``ValueError`` if the cleaned value doesn't look like a CF API token.
    """
    cleaned = raw.strip()

    # Strip surrounding quotes
    if (cleaned.startswith('"') and cleaned.endswith('"')) or \
       (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1].strip()

    # If it looks like a curl command or "Bearer ..." header value, extract token
    if "Bearer" in cleaned:
        # Take the part after the last "Bearer "
        idx = cleaned.rfind("Bearer ")
        cleaned = cleaned[idx + len("Bearer "):].strip()
    elif cleaned.lower().startswith("curl "):
        # Reject — user pasted a curl command
        raise ValueError(
            "It looks like you pasted a curl command.\n"
            "Please paste only the API token value (the 40-character string)."
        )

    # Remove any trailing quotes, backslashes, or whitespace
    cleaned = cleaned.strip().strip('"').strip("'").strip()

    # Final validation
    if not cleaned:
        raise ValueError("Token is empty.")
    if not _TOKEN_PATTERN.match(cleaned):
        raise ValueError(
            "Invalid API token format.\n"
            "A Cloudflare API token should be an alphanumeric string "
            "(typically 40 characters).\n"
            "Do not paste the full curl command or Bearer header."
        )
    return cleaned


class CloudflareClient:
    """Thin wrapper around the Cloudflare v4 REST API.

    The *token* is accepted per-method call so it never needs to be stored
    as instance state.
    """

    def __init__(self) -> None:
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        """Execute an API call with retry + exponential backoff on 429."""
        url = f"{CLOUDFLARE_API_BASE}{path}"
        headers = self._headers(token)

        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._session.request(
                    method, url, headers=headers, params=params, json=json_body, timeout=30
                )
            except requests.ConnectionError as exc:
                if attempt < _MAX_RETRIES - 1:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning("Connection error, retrying in %.1fs: %s", wait, exc)
                    time.sleep(wait)
                    continue
                raise CloudflareAPIError(0, [{"message": f"Connection failed: {exc}"}]) from exc
            except requests.Timeout as exc:
                if attempt < _MAX_RETRIES - 1:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning("Request timed out, retrying in %.1fs: %s", wait, exc)
                    time.sleep(wait)
                    continue
                raise CloudflareAPIError(0, [{"message": f"Request timed out: {exc}"}]) from exc

            if resp.status_code == 429:
                wait = _BACKOFF_BASE * (2 ** attempt)
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after))
                    except ValueError:
                        pass
                logger.warning("Rate-limited by Cloudflare, retrying in %.1fs", wait)
                time.sleep(wait)
                continue

            data = resp.json()
            if not data.get("success", False):
                raise CloudflareAPIError(resp.status_code, data.get("errors", []))
            return data

        # Exhausted retries
        raise CloudflareAPIError(429, [{"message": "Rate-limit retries exhausted"}])

    # ------------------------------------------------------------------
    # Token verification
    # ------------------------------------------------------------------

    def verify_token(self, token: str) -> bool:
        """Verify *token* against ``/user/tokens/verify``.

        Returns ``True`` if the token is valid and active.
        Raises ``CloudflareAPIError`` on auth failure.
        """
        data = self._request("GET", "/user/tokens/verify", token)
        status = data.get("result", {}).get("status", "")
        return status == "active"

    # ------------------------------------------------------------------
    # Zones
    # ------------------------------------------------------------------

    def list_zones(self, token: str) -> list[dict]:
        """Return all zones accessible with *token*.

        Each dict contains at least ``id`` and ``name``.
        """
        zones: list[dict] = []
        page = 1
        while True:
            data = self._request(
                "GET", "/zones", token, params={"page": page, "per_page": 50}
            )
            for z in data["result"]:
                zones.append({"id": z["id"], "name": z["name"], "status": z["status"]})
            info = data.get("result_info", {})
            if page >= info.get("total_pages", 1):
                break
            page += 1
        return zones

    # ------------------------------------------------------------------
    # DNS Records
    # ------------------------------------------------------------------

    def list_records(self, token: str, zone_id: str) -> list[dict]:
        """Return all supported DNS records for *zone_id*."""
        records: list[dict] = []
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/zones/{zone_id}/dns_records",
                token,
                params={"page": page, "per_page": 100},
            )
            for r in data["result"]:
                if r["type"] in SUPPORTED_RECORD_TYPES:
                    records.append(_normalize_record(r))
            info = data.get("result_info", {})
            if page >= info.get("total_pages", 1):
                break
            page += 1
        return records

    def create_record(self, token: str, zone_id: str, record: dict) -> dict:
        """Create a DNS record and return the normalized result."""
        body = _to_api_payload(record)
        data = self._request(
            "POST", f"/zones/{zone_id}/dns_records", token, json_body=body
        )
        return _normalize_record(data["result"])

    def update_record(
        self, token: str, zone_id: str, record_id: str, record: dict
    ) -> dict:
        """Update an existing DNS record by *record_id*."""
        body = _to_api_payload(record)
        data = self._request(
            "PUT",
            f"/zones/{zone_id}/dns_records/{record_id}",
            token,
            json_body=body,
        )
        return _normalize_record(data["result"])

    def delete_record(self, token: str, zone_id: str, record_id: str) -> None:
        """Delete a DNS record."""
        self._request(
            "DELETE", f"/zones/{zone_id}/dns_records/{record_id}", token
        )


# ------------------------------------------------------------------
# Record normalisation helpers
# ------------------------------------------------------------------

def _normalize_record(raw: dict) -> dict:
    """Transform a Cloudflare API record into a consistent internal format."""
    rec: dict[str, Any] = {
        "id": raw["id"],
        "type": raw["type"],
        "name": raw["name"],
        "content": raw["content"],
        "ttl": raw.get("ttl", 1),
        "proxied": raw.get("proxied", False),
    }
    if raw["type"] == "MX":
        rec["priority"] = raw.get("priority", 0)
    elif raw["type"] == "SRV":
        rec["priority"] = raw.get("priority", 0)
        data = raw.get("data", {})
        rec["data"] = {
            "weight": data.get("weight", 0),
            "port": data.get("port", 0),
            "target": data.get("target", ""),
            "service": data.get("service", ""),
            "proto": data.get("proto", ""),
            "name": data.get("name", ""),
            "priority": data.get("priority", rec["priority"]),
        }
    return rec


def _to_api_payload(record: dict) -> dict:
    """Convert an internal record dict to a Cloudflare API write payload."""
    payload: dict[str, Any] = {
        "type": record["type"],
        "name": record["name"],
        "content": record["content"],
        "ttl": record.get("ttl", 1),
    }
    if record["type"] in ("A", "AAAA", "CNAME"):
        payload["proxied"] = record.get("proxied", False)
    if record["type"] == "MX":
        payload["priority"] = record.get("priority", 10)
    elif record["type"] == "SRV":
        payload["data"] = record.get("data", {})
    return payload
