"""Timezone auto-detection and IANA validation helpers."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tzlocal


def validate_timezone(tz_name: str) -> str:
    """Validate and return canonical IANA timezone string."""
    cleaned = tz_name.strip()
    if not cleaned:
        raise ValueError("Invalid IANA timezone: empty string")
    try:
        tz = ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
        raise ValueError(f"Invalid IANA timezone: {tz_name!r}") from exc
    return tz.key


def detect_local_timezone(fallback: str = "UTC") -> str:
    """Auto-detect the host operating system's IANA timezone on startup."""
    try:
        detected = tzlocal.get_localzone_name()
        if detected:
            return validate_timezone(detected)
    except Exception:
        pass
    return validate_timezone(fallback)
