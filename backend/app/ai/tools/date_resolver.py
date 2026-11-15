"""Deterministic relative period resolution in the user's profile timezone."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ResolvedPeriodWindow:
    label: str
    timezone: str
    start_local: date
    end_local: date
    start_utc: datetime
    end_exclusive_utc: datetime


def resolve_relative_period(
    period: str | None,
    reference_now_utc: datetime,
    tz_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ResolvedPeriodWindow:
    tz = ZoneInfo(tz_name)
    local_now = reference_now_utc.astimezone(tz)
    today = local_now.date()

    if start_date and end_date:
        s_date = date.fromisoformat(start_date[:10])
        e_date = date.fromisoformat(end_date[:10])
        label = f"{s_date.isoformat()}..{e_date.isoformat()}"
    else:
        token = (period or "this_month").strip().lower().replace(" ", "_")
        if token in ("this_month", "current_month"):
            last_day = calendar.monthrange(today.year, today.month)[1]
            s_date = date(today.year, today.month, 1)
            e_date = date(today.year, today.month, last_day)
            label = "this_month"
        elif token in ("last_month", "previous_month"):
            y, m = today.year, today.month - 1
            if m == 0:
                m = 12
                y -= 1
            last_day = calendar.monthrange(y, m)[1]
            s_date = date(y, m, 1)
            e_date = date(y, m, last_day)
            label = "last_month"
        elif token in ("last_3_months", "last_three_months"):
            y, m = today.year, today.month - 2
            while m <= 0:
                m += 12
                y -= 1
            last_day = calendar.monthrange(today.year, today.month)[1]
            s_date = date(y, m, 1)
            e_date = date(today.year, today.month, last_day)
            label = "last_3_months"
        elif token == "last_30_days":
            s_date = today - timedelta(days=29)
            e_date = today
            label = "last_30_days"
        elif token in ("this_year", "current_year"):
            s_date = date(today.year, 1, 1)
            e_date = date(today.year, 12, 31)
            label = "this_year"
        else:
            last_day = calendar.monthrange(today.year, today.month)[1]
            s_date = date(today.year, today.month, 1)
            e_date = date(today.year, today.month, last_day)
            label = "this_month"

    start_utc = datetime.combine(s_date, time.min, tzinfo=tz).astimezone(UTC)
    end_excl_utc = datetime.combine(e_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return ResolvedPeriodWindow(
        label=label,
        timezone=tz_name,
        start_local=s_date,
        end_local=e_date,
        start_utc=start_utc,
        end_exclusive_utc=end_excl_utc,
    )
