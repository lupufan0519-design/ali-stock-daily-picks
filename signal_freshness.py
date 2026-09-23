"""Fail-closed date checks for one-bar intraday indicator seeds.

An intraday seed describes appending exactly one bar, not an arbitrary later
quote.  A current quote cannot repair missing daily indicator history.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def valid_trade_date(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return ""
    return value if parsed.isoformat() == value else ""


def normalized_sessions(values: Iterable[object] | None) -> list[str]:
    if values is None or isinstance(values, (str, bytes, dict)):
        return []
    return sorted({day for value in values if (day := valid_trade_date(value))})


def session_distance(
    earlier: object, later: object, sessions: Iterable[object] | None = None,
) -> int | None:
    """Count real sessions when covered; otherwise conservatively count weekdays.

    Weekday fallback may reject a still-valid holiday-adjacent signal, but must
    never extend a signal's window.  Long-holiday seed reuse requires a real
    calendar through both dates (see ``seed_transition_allowed``).
    """
    start, end = valid_trade_date(earlier), valid_trade_date(later)
    if not start or not end or start > end:
        return None
    days = normalized_sessions(sessions)
    if days and days[0] <= start and days[-1] >= end:
        if start not in days or end not in days:
            return None
        return days.index(end) - days.index(start)
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.weekday() >= 5 or last.weekday() >= 5:
        return None
    count = 0
    cursor = first
    while cursor < last:
        cursor += timedelta(days=1)
        count += int(cursor.weekday() < 5)
    return count


def seed_transition_allowed(
    base_date: object, quote_date: object, sessions: Iterable[object] | None = None,
) -> bool:
    base, current = valid_trade_date(base_date), valid_trade_date(quote_date)
    if not base or not current or current < base:
        return False
    days = normalized_sessions(sessions)
    if days and days[0] <= base and days[-1] >= current:
        return session_distance(base, current, days) in (0, 1)
    # Without reference sessions, only the immediate next weekday is safe.
    # Missing holiday dates are never assumed to have been trading closures.
    return session_distance(base, current) in (0, 1)


def signal_within_window(
    signal_date: object, quote_date: object, lookback: int,
    sessions: Iterable[object] | None = None,
) -> bool:
    distance = session_distance(signal_date, quote_date, sessions)
    return distance is not None and 0 <= distance < max(0, int(lookback))
