"""Client for acquiring the upstream device-account identity.

The upstream service has returned both ``data`` and ``data.user`` wrappers in
different deployments, so parsing is deliberately tolerant while remaining
strict about the identity fields we need for authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import requests


@dataclass(frozen=True)
class UpstreamIdentity:
    username: str
    is_super: bool
    access_token: str | None = None
    expires_in: int | None = None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_identity(payload: Any) -> UpstreamIdentity:
    """Parse a successful upstream login payload or raise ``ValueError``."""
    root = _mapping(payload)
    if str(root.get("code", "200")) not in {"200", "0"}:
        raise ValueError(str(root.get("msg") or "upstream login failed"))
    data = _mapping(root.get("data"))
    # Some deployments put account fields directly in data, others under user.
    user = _mapping(data.get("user")) or _mapping(root.get("user")) or data
    username = str(user.get("user_name") or user.get("username") or root.get("user_name") or "").strip()
    if not username:
        raise ValueError("upstream login response did not contain a username")
    token = data.get("access_token") or root.get("access_token")
    raw_super = user.get("is_super", data.get("is_super", root.get("is_super", 0)))
    is_super = raw_super is True or str(raw_super).lower() in {"1", "true", "yes"}
    try:
        expires = int(data.get("expires_in", root.get("expires_in")))
    except (TypeError, ValueError):
        expires = None
    return UpstreamIdentity(username, is_super, str(token) if token else None, expires)


def acquire_identity(base_url: str, username: str, password: str, *, timeout: float = 15.0) -> UpstreamIdentity:
    """Authenticate against the documented ``deviceLogin`` endpoint."""
    url = base_url.rstrip("/") + "/prod-api/auth/deviceLogin"
    response = requests.post(url, json={"username": username, "password": password}, timeout=timeout)
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"upstream returned non-JSON HTTP {response.status_code}") from exc
    if response.status_code >= 400:
        raise ValueError(f"upstream HTTP {response.status_code}: {payload}")
    return parse_identity(payload)
