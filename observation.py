from __future__ import annotations

from typing import Any, Sequence


OBSERVATION_LIMIT = 30


def _value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def _observation_value(item: Any, field: str, fallback: str, default: Any) -> Any:
    value = _value(item, field, None)
    return _value(item, fallback, default) if value is None else value


def observation_sort_key(item: Any) -> tuple:
    """Return the single ordering contract used by the page and live quotes."""
    return (
        bool(_value(item, "cross_ok", False)),
        bool(_value(item, "bottom_ok", False)),
        bool(
            _observation_value(
                item, "observation_yellow_ok", "yellow_ok", False
            )
        ),
        bool(_value(item, "limit_up_ok", False)),
        str(_value(item, "cross_date", "")),
        str(_value(item, "bottom_date", "")),
        str(_value(item, "code", "")),
    )


def visible_observations(
    rows: Sequence[Any],
    minimum: int,
    limit: int | None = OBSERVATION_LIMIT,
) -> list[Any]:
    candidates = [
        item
        for item in rows
        if bool(_value(item, "eligible", False))
        and not bool(_value(item, "selected", False))
        and int(
            _observation_value(
                item, "observation_matched_count", "matched_count", 0
            )
        ) >= minimum
        and "ST" not in str(_value(item, "name", "")).upper()
    ]
    candidates.sort(key=observation_sort_key, reverse=True)
    return candidates if limit is None else candidates[:limit]
