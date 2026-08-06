from __future__ import annotations

from typing import Iterable, Mapping


STRATEGY_VERSION = "two_tier_confirmed_bottom_yellow_v3"
FIRST_TIER = "first"
SECOND_TIER = "second"


def _number(row: Mapping[str, object], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 0.0


def _eligible(row: Mapping[str, object]) -> bool:
    name = str(row.get("name", "")).upper()
    return bool(row.get("eligible", True)) and "ST" not in name


def classify_tier(row: Mapping[str, object], cfg: Mapping[str, object]) -> str:
    """Classify one quote under the current, mutually exclusive two-tier rule."""
    if not _eligible(row) or not bool(row.get("bottom_ok")):
        return ""

    dragon = _number(row, "dragon_value", "dragon")
    tiger = _number(row, "tiger_value", "tiger")
    yellow = _number(row, "yellow_line_value", "yellow_line")
    price = _number(row, "price", "close", "last_close")
    max_gap = float(cfg.get("line_gap_max_abs", 0.5) or 0.5)
    prior_gaps = row.get("prior_three_gap_abs", [])
    if (
        isinstance(prior_gaps, (list, tuple))
        and len(prior_gaps) >= 3
        and all(float(value) <= max_gap + 1e-8 for value in prior_gaps[-3:])
    ):
        return FIRST_TIER

    if (
        price > 0
        and yellow > 0
        and price <= yellow + 1e-8
    ):
        return SECOND_TIER
    return ""


def decorate_row(row: Mapping[str, object], cfg: Mapping[str, object]) -> dict:
    decorated = dict(row)
    dragon = _number(row, "dragon_value", "dragon")
    tiger = _number(row, "tiger_value", "tiger")
    yellow = _number(row, "yellow_line_value", "yellow_line")
    price = _number(row, "price", "close", "last_close")
    prior_gaps_raw = row.get("prior_three_gap_abs", [])
    prior_gaps = (
        [float(value) for value in prior_gaps_raw[-3:]]
        if isinstance(prior_gaps_raw, (list, tuple))
        else []
    )
    tier = classify_tier(row, cfg)
    ceiling = yellow if yellow > 0 else 0.0
    decorated.update(
        {
            "strategy_version": STRATEGY_VERSION,
            "tier": tier,
            "first_tier": tier == FIRST_TIER,
            "second_tier": tier == SECOND_TIER,
            "line_gap_abs": abs(dragon - tiger) if dragon and tiger else None,
            "prior_three_gap_abs": prior_gaps,
            "prior_three_gap_max": max(prior_gaps) if len(prior_gaps) == 3 else None,
            "line_ceiling": ceiling or None,
            "line_distance_pct": (
                (ceiling / price - 1.0) * 100.0
                if ceiling > 0 and price > 0
                else None
            ),
        }
    )
    return decorated


def split_tiers(
    rows: Iterable[Mapping[str, object]],
    cfg: Mapping[str, object],
) -> dict[str, list[dict]]:
    first: list[dict] = []
    second: list[dict] = []
    for row in rows:
        decorated = decorate_row(row, cfg)
        if decorated["tier"] == FIRST_TIER:
            first.append(decorated)
        elif decorated["tier"] == SECOND_TIER:
            second.append(decorated)

    first.sort(
        key=lambda item: (
            float(item.get("prior_three_gap_max") or 999999.0),
            str(item.get("code", "")),
        )
    )
    second.sort(
        key=lambda item: (
            -float(item.get("line_distance_pct") or 0.0),
            str(item.get("code", "")),
        )
    )
    return {FIRST_TIER: first, SECOND_TIER: second}


def tier_counts(tiers: Mapping[str, list[dict]]) -> dict[str, int]:
    first = len(tiers.get(FIRST_TIER, []))
    second = len(tiers.get(SECOND_TIER, []))
    return {FIRST_TIER: first, SECOND_TIER: second, "total": first + second}
