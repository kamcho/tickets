"""Exact anniversary billing periods (second-precision)."""
from __future__ import annotations

import calendar
from datetime import datetime


def add_one_billing_month(dt: datetime) -> datetime:
    """
    Advance by one calendar month, keeping hour/minute/second/microsecond.

    Example: 2026-07-14 10:55:12 → 2026-08-14 10:55:12

    If the day does not exist in the target month (e.g. Jan 31 → Feb),
    clamp to the last valid day of that month (same clock time).
    """
    year = dt.year
    month = dt.month + 1
    if month > 12:
        month = 1
        year += 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)
