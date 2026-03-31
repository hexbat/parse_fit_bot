from __future__ import annotations

from datetime import datetime
from typing import Optional


def get_record_timestamp(rec: dict) -> Optional[datetime]:
    ts = rec.get("timestamp")
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None
    return None


def get_record_int(rec: dict, field: str) -> Optional[int]:
    value = rec.get(field)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_record_hr(rec: dict) -> Optional[int]:
    return get_record_int(rec, "heart_rate")


def get_record_cadence(rec: dict) -> Optional[int]:
    return get_record_int(rec, "cadence")

