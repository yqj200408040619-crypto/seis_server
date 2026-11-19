from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime, timezone

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_name(value: str, fallback: str = "unknown") -> str:
    value = value.strip() if value else fallback
    value = _SAFE.sub("_", value)
    value = value.strip("._-")
    return value or fallback


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def quarantine_path(base_dir: Path, prefix: str = "bad") -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{prefix}_{utc_date()}.bin"
