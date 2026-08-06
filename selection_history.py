from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from simple_strategy import FIRST_TIER, SECOND_TIER, STRATEGY_VERSION, THIRD_TIER


SCHEMA_VERSION = 1


def empty_history(started_on: str = "") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "started_on": started_on,
        "updated_at": "",
        "dates": [],
        "summary": summarize([]),
    }


def load_history(path: Path) -> dict:
    if not path.exists():
        return empty_history()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return empty_history()
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("strategy_version") != STRATEGY_VERSION
        or not isinstance(payload.get("dates"), list)
    ):
        return empty_history()
    return payload


def _price(row: Mapping[str, object]) -> float:
    for key in ("price", "close", "last_close"):
        try:
            value = float(row.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


def _pick(row: Mapping[str, object], trade_date: str, tier: str) -> dict:
    selected_price = _price(row)
    prior_gaps_raw = row.get("prior_three_gap_abs", [])
    prior_gaps = (
        [float(value) for value in prior_gaps_raw]
        if isinstance(prior_gaps_raw, (list, tuple))
        else []
    )
    return {
        "id": f"{trade_date}:{tier}:{row.get('code', '')}",
        "trade_date": trade_date,
        "tier": tier,
        "code": str(row.get("code", "")),
        "name": str(row.get("name", "")),
        "market": int(row.get("market", 0) or 0),
        "selected_price": selected_price,
        "current_price": selected_price,
        "current_date": trade_date,
        "return_pct": 0.0,
        "status": "待产生后续行情",
        "bottom_date": str(row.get("bottom_date", "")),
        "bottom_price": float(row.get("bottom_price", 0.0) or 0.0),
        "bottom_price_gap_abs": float(
            row.get("bottom_price_gap_abs", 0.0) or 0.0
        ),
        "dragon_value": float(row.get("dragon_value", 0.0) or 0.0),
        "tiger_value": float(row.get("tiger_value", 0.0) or 0.0),
        "yellow_line_value": float(row.get("yellow_line_value", 0.0) or 0.0),
        "line_gap_abs": float(row.get("line_gap_abs", 0.0) or 0.0),
        "prior_three_gap_abs": prior_gaps,
        "prior_three_gap_max": float(row.get("prior_three_gap_max", 0.0) or 0.0),
    }


def _all_records(dates: Iterable[Mapping[str, object]]) -> list[dict]:
    records: list[dict] = []
    for day in dates:
        for key in (FIRST_TIER, SECOND_TIER, THIRD_TIER):
            values = day.get(key, [])
            if isinstance(values, list):
                records.extend(item for item in values if isinstance(item, dict))
    return records


def summarize(dates: Iterable[Mapping[str, object]]) -> dict:
    records = _all_records(dates)
    settled = [
        item
        for item in records
        if str(item.get("current_date", "")) > str(item.get("trade_date", ""))
        and float(item.get("selected_price", 0.0) or 0.0) > 0
        and float(item.get("current_price", 0.0) or 0.0) > 0
    ]
    successful = [item for item in settled if float(item.get("return_pct", 0.0)) > 0]
    average = (
        sum(float(item.get("return_pct", 0.0)) for item in settled) / len(settled)
        if settled
        else None
    )
    return {
        "selection_count": len(records),
        "first_tier_count": sum(item.get("tier") == FIRST_TIER for item in records),
        "second_tier_count": sum(item.get("tier") == SECOND_TIER for item in records),
        "third_tier_count": sum(item.get("tier") == THIRD_TIER for item in records),
        "evaluated_count": len(settled),
        "success_count": len(successful),
        "success_rate_pct": len(successful) / len(settled) * 100.0 if settled else None,
        "average_return_pct": average,
    }


def refresh_history(
    history: Mapping[str, object],
    prices: Mapping[str, Mapping[str, object]],
    current_date: str,
    generated_at: str = "",
) -> dict:
    updated = copy.deepcopy(dict(history))
    dates = updated.get("dates", [])
    if not isinstance(dates, list):
        dates = []
        updated["dates"] = dates
    for record in _all_records(dates):
        quote = prices.get(str(record.get("code", "")))
        if not quote:
            continue
        current_price = _price(quote)
        if current_price <= 0:
            continue
        selected_price = float(record.get("selected_price", 0.0) or 0.0)
        record["current_price"] = current_price
        record["current_date"] = current_date or str(record.get("current_date", ""))
        record["return_pct"] = (
            (current_price / selected_price - 1.0) * 100.0
            if selected_price > 0
            else 0.0
        )
        if str(record.get("current_date", "")) <= str(record.get("trade_date", "")):
            record["status"] = "待产生后续行情"
        elif float(record["return_pct"]) > 0:
            record["status"] = "上涨"
        else:
            record["status"] = "暂未上涨"
    updated["updated_at"] = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    updated["summary"] = summarize(dates)
    return updated


def record_close(
    history: Mapping[str, object],
    trade_date: str,
    tiers: Mapping[str, list[dict]],
    all_rows: Iterable[Mapping[str, object]],
    generated_at: str = "",
) -> dict:
    if history.get("strategy_version") != STRATEGY_VERSION:
        working = empty_history(trade_date)
    else:
        working = copy.deepcopy(dict(history))
    if not working.get("started_on"):
        working["started_on"] = trade_date

    day = {
        "trade_date": trade_date,
        FIRST_TIER: [_pick(item, trade_date, FIRST_TIER) for item in tiers.get(FIRST_TIER, [])],
        SECOND_TIER: [_pick(item, trade_date, SECOND_TIER) for item in tiers.get(SECOND_TIER, [])],
        THIRD_TIER: [_pick(item, trade_date, THIRD_TIER) for item in tiers.get(THIRD_TIER, [])],
    }
    dates = [
        item
        for item in working.get("dates", [])
        if isinstance(item, dict) and str(item.get("trade_date", "")) != trade_date
    ]
    dates.append(day)
    dates.sort(key=lambda item: str(item.get("trade_date", "")))
    working["dates"] = dates

    prices = {
        str(item.get("code", "")): item
        for item in all_rows
        if item.get("code")
    }
    return refresh_history(working, prices, trade_date, generated_at)


def write_history(path: Path, history: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
