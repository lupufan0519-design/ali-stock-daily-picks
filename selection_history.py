from __future__ import annotations

import copy
import json
from datetime import date, datetime
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from simple_strategy import FIRST_TIER, SECOND_TIER, STRATEGY_VERSION, THIRD_TIER


SCHEMA_VERSION = 1
VISIBLE_BOTTOM_MIGRATION_VERSION = 1
SIGNAL_INTEGRITY_VERSION = 1


def _iso_date(value: object) -> str:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _valid_record(item: Mapping[str, object]) -> bool:
    return not item.get("invalid_signal") and item.get("performance_eligible") is not False


def _finite_number(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not str(value).strip():
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _settled_record(item: Mapping[str, object]) -> bool:
    selected = _finite_number(item.get("selected_price"))
    current = _finite_number(item.get("current_price"))
    return bool(
        _valid_record(item)
        and str(item.get("current_date", "")) > str(item.get("trade_date", ""))
        and selected is not None and selected > 0
        and current is not None and current > 0
        and _finite_number(item.get("return_pct")) is not None
    )


def _signal_issue(signal_date: str, base_date: str, selected_date: str,
                  sessions: Sequence[str], recent_days: int) -> tuple[str, str]:
    later = [value for value in sessions if signal_date < value <= selected_date]
    base_later = [value for value in sessions if base_date < value <= selected_date]
    if signal_date and selected_date and signal_date > selected_date:
        return "invalid_signal_date", "信号日期晚于入选日期"
    if signal_date and signal_date == selected_date:
        return "unformed_signal", "可能见底信号当日尚未形成"
    if signal_date and len(later) >= recent_days:
        return "outside_signal_window", f"见底日期 {signal_date} 已超出入选时近 {recent_days} 个交易日"
    if base_date and (base_date > selected_date or len(base_later) > 1):
        return "stale_signal_base", f"策略基准 {base_date} 过期或与入选日不一致，无法核验当时信号"
    return "", ""


def audit_history_signals(
    history: Mapping[str, object],
    trading_dates: Iterable[str] = (),
    signal_base_dates: Mapping[str, str] | None = None,
    generated_at: str = "",
    recent_days: int = 4,
) -> tuple[dict, dict]:
    """Quarantine provably invalid recommendations without rewriting the past.

    ``trading_dates`` must be actual exchange sessions, never guessed weekdays.
    Existing ledger dates are a conservative lower bound: four known sessions
    after the signal prove expiry even if the ledger has gaps. Unknown dates
    alone never prove validity. Provenance mappings are supplied only when a
    historical run/snapshot establishes the base used for that selection date.
    """
    working = copy.deepcopy(dict(history))
    dates = working.get("dates", [])
    if not isinstance(dates, list):
        dates = []
        working["dates"] = dates
    explicit_sessions = {_iso_date(value) for value in trading_dates} - {""}
    sessions = sorted(explicit_sessions | {
        _iso_date(day.get("trade_date")) for day in dates if isinstance(day, Mapping)
    } - {""})
    report = {"moved_count": 0, "outside_signal_window": 0, "stale_signal_base": 0,
              "invalid_signal_date": 0, "unformed_signal": 0, "legacy_unverified": 0,
              "reclassified_removals": 0}
    for day in dates:
        if not isinstance(day, dict):
            continue
        selected_date = _iso_date(day.get("trade_date"))
        removed = day.get("removed") if isinstance(day.get("removed"), list) else []
        invalid_codes: set[str] = set()
        for tier in (FIRST_TIER, SECOND_TIER, THIRD_TIER):
            values = day.get(tier)
            if not isinstance(values, list):
                continue
            kept = []
            for record in values:
                if not isinstance(record, dict):
                    continue
                original_record = copy.deepcopy(record)
                signal_date = _iso_date(record.get("bottom_date"))
                base_date = _iso_date(record.get("signal_base_date"))
                if not base_date and signal_base_dates:
                    base_date = _iso_date(signal_base_dates.get(selected_date))
                    if base_date:
                        record["signal_base_date"] = base_date
                        record["signal_base_provenance"] = "historical_snapshot_audit"
                reason, note = _signal_issue(signal_date, base_date, selected_date, sessions, recent_days)
                if not reason and record.get("invalid_signal"):
                    reason = str(record.get("invalid_reason") or "previous_correction")
                    note = str(record.get("removal_reason") or "历史信号已纠错")
                if reason:
                    code = str(record.get("code", ""))
                    invalid_codes.add(code)
                    correction_id = f"{selected_date}:signal-audit:{tier}:{code}:{signal_date}"
                    if not any(item.get("id") == correction_id for item in removed if isinstance(item, Mapping)):
                        correction = copy.deepcopy(record)
                        correction.update({
                            "id": correction_id, "original_record": original_record,
                            "selected_tier": tier, "invalid_signal": True,
                            "invalid_reason": reason, "outside_signal_window": reason == "outside_signal_window",
                            "performance_eligible": False, "signal_integrity": "invalid",
                            "removal_reason": note + "（历史纠错，不计绩效）",
                            "removed_at": generated_at, "active_again": False,
                            "integrity_checked_at": generated_at,
                        })
                        removed.append(correction)
                    report["moved_count"] += 1
                    report[reason] = report.get(reason, 0) + 1
                    continue
                if (signal_date in explicit_sessions and selected_date in explicit_sessions
                        and base_date in explicit_sessions):
                    record["signal_integrity"] = "window_verified"
                else:
                    record["signal_integrity"] = "legacy_unverified"
                    report["legacy_unverified"] += 1
                kept.append(record)
            day[tier] = kept
        for event in removed:
            if not isinstance(event, dict) or event.get("invalid_signal"):
                continue
            event_signal = _iso_date(event.get("bottom_date"))
            event_base = _iso_date(event.get("signal_base_date"))
            if not event_base and signal_base_dates:
                event_base = _iso_date(signal_base_dates.get(selected_date))
            reason, note = _signal_issue(event_signal, event_base, selected_date, sessions, recent_days)
            if not reason:
                continue
            # An event derived from an invalid original pick is not evidence
            # that a valid signal later disappeared. Preserve the event in full.
            event.setdefault("original_record", copy.deepcopy(event))
            event.update({"invalid_signal": True, "invalid_reason": reason,
                          "outside_signal_window": reason == "outside_signal_window",
                          "signal_integrity": "invalid", "performance_eligible": False,
                          "removal_reason": note + "（原移除记录归入历史纠错，不计绩效）",
                          "integrity_checked_at": generated_at})
            if event_base:
                event["signal_base_date"] = event_base
            report["reclassified_removals"] += 1
        if invalid_codes:
            day["live_active_codes"] = [code for code in day.get("live_active_codes", []) if str(code) not in invalid_codes]
        if removed or "removed" in day:
            day["removed"] = removed
    working["signal_integrity_version"] = SIGNAL_INTEGRITY_VERSION
    reference_date = max((str(day.get("trade_date", "")) for day in dates if isinstance(day, Mapping)), default="")
    working["summary"] = summarize(dates, reference_date)
    if working != history and generated_at:
        working["updated_at"] = generated_at
    return working, report


def empty_history(started_on: str = "") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "visible_bottom_migration_version": VISIBLE_BOTTOM_MIGRATION_VERSION,
        "started_on": started_on,
        "last_close_trade_date": "",
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
    payload.setdefault("last_close_trade_date", "")
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
        "signal_base_date": _iso_date(row.get("signal_base_date")),
        "signal_integrity": "legacy_unverified",
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


def _day_records(day: Mapping[str, object]) -> dict[str, tuple[str, dict]]:
    records: dict[str, tuple[str, dict]] = {}
    for tier in (FIRST_TIER, SECOND_TIER, THIRD_TIER):
        values = day.get(tier, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", ""))
            if code and code not in records:
                records[code] = (tier, item)
    return records


def _find_or_create_day(dates: list[dict], trade_date: str) -> tuple[dict, bool]:
    for item in dates:
        if str(item.get("trade_date", "")) == trade_date:
            for tier in (FIRST_TIER, SECOND_TIER, THIRD_TIER):
                if not isinstance(item.get(tier), list):
                    item[tier] = []
            if not isinstance(item.get("removed"), list):
                item["removed"] = []
            return item, False
    day = {
        "trade_date": trade_date,
        FIRST_TIER: [],
        SECOND_TIER: [],
        THIRD_TIER: [],
        "removed": [],
        "live_active_codes": [],
    }
    dates.append(day)
    dates.sort(key=lambda item: str(item.get("trade_date", "")))
    return day, True


def _move_unformed_same_day_records(
    dates: list[dict],
    generated_at: str,
) -> bool:
    """Move legacy same-day ZIG candidates out of the selected-tier ledger.

    The corrected signal contract requires at least one later trading bar before
    a falling ZIG candidate can display the possible-bottom text.  Older runs
    briefly stored the still-forming low on its own date.  Keep those rows in the
    day's removal audit instead of letting them affect selection or success
    statistics.
    """
    changed = False
    for day in dates:
        trade_date = str(day.get("trade_date", ""))
        if not trade_date:
            continue
        removed_values = day.get("removed", [])
        if not isinstance(removed_values, list):
            removed_values = []
        correction_by_code = {
            str(item.get("code", "")): item
            for item in removed_values
            if (
                isinstance(item, dict)
                and item.get("code")
                and bool(item.get("invalid_signal"))
            )
        }
        invalid_codes: set[str] = set()
        for tier in (FIRST_TIER, SECOND_TIER, THIRD_TIER):
            values = day.get(tier, [])
            if not isinstance(values, list):
                continue
            kept: list[object] = []
            for item in values:
                if not isinstance(item, dict):
                    kept.append(item)
                    continue
                code = str(item.get("code", ""))
                is_unformed = bool(
                    code and str(item.get("bottom_date", "")) == trade_date
                )
                if not is_unformed:
                    kept.append(item)
                    continue
                invalid_codes.add(code)
                correction = correction_by_code.get(code)
                if correction is None:
                    correction = copy.deepcopy(item)
                    correction["original_record"] = copy.deepcopy(item)
                    removed_values.append(correction)
                    correction_by_code[code] = correction
                selected_tier = (
                    str(correction.get("selected_tier", ""))
                    or str(item.get("tier", ""))
                    or tier
                )
                correction.update(
                    {
                        "id": f"{trade_date}:removed-correction:{code}",
                        "selected_tier": selected_tier,
                        "removed_at": generated_at,
                        "removal_reason": "可能见底信号当日尚未形成（历史纠正）",
                        "removal_count": max(
                            1,
                            int(correction.get("removal_count", 0) or 0),
                        ),
                        "active_again": False,
                        "restored_at": "",
                        "invalid_signal": True,
                        "invalid_reason": "unformed_signal",
                        "performance_eligible": False,
                    }
                )
                changed = True
            if len(kept) != len(values):
                day[tier] = kept
        if invalid_codes:
            active_codes = day.get("live_active_codes", [])
            if isinstance(active_codes, list):
                day["live_active_codes"] = [
                    str(code)
                    for code in active_codes
                    if str(code) and str(code) not in invalid_codes
                ]
            day["removed"] = removed_values
    return changed


def record_intraday_pools(
    history: Mapping[str, object],
    trade_date: str,
    tiers: Mapping[str, Sequence[Mapping[str, object]]],
    observed_codes: Iterable[str],
    generated_at: str = "",
    *,
    signal_base_date: str = "",
    trading_dates: Iterable[str] = (),
) -> tuple[dict, bool]:
    """Persist intraday appearances and possible-bottom repaint removals.

    Tier arrays are an append-only ledger of stocks that appeared at least once
    during the day. ``live_active_codes`` stores only the previous refresh state,
    allowing a later refresh to distinguish a repaint removal from a missing
    quote. A removed stock remains in its original tier and is also copied into
    the day's ``removed`` section. The sole cleanup exception is a legacy row
    whose signal date equals its selection date: that still-forming candidate is
    moved into the removal audit so it cannot affect performance statistics.
    """
    if not trade_date:
        return copy.deepcopy(dict(history)), False
    if history.get("strategy_version") != STRATEGY_VERSION:
        working = empty_history(trade_date)
    else:
        working = copy.deepcopy(dict(history))
    if not working.get("started_on"):
        working["started_on"] = trade_date
    dates = working.get("dates", [])
    if not isinstance(dates, list):
        dates = []
    dates = [item for item in dates if isinstance(item, dict)]
    working["dates"] = dates
    history_migrated = False
    if (
        int(working.get("visible_bottom_migration_version", 0) or 0)
        < VISIBLE_BOTTOM_MIGRATION_VERSION
    ):
        _move_unformed_same_day_records(dates, generated_at)
        working["visible_bottom_migration_version"] = (
            VISIBLE_BOTTOM_MIGRATION_VERSION
        )
        history_migrated = True
    summary_changed = working.get("summary") != summarize(dates, trade_date)
    has_day = any(
        isinstance(item, dict) and str(item.get("trade_date", "")) == trade_date
        for item in dates
    )
    has_current_selection = any(
        isinstance(values, (list, tuple))
        and any(isinstance(row, Mapping) and row.get("code") for row in values)
        for values in (
            tiers.get(FIRST_TIER, []),
            tiers.get(SECOND_TIER, []),
            tiers.get(THIRD_TIER, []),
        )
    )
    if not has_day and not has_current_selection:
        if history_migrated or summary_changed:
            working["updated_at"] = generated_at or (
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
            working["summary"] = summarize(dates, trade_date)
        return working, history_migrated or summary_changed
    day, created = _find_or_create_day(dates, trade_date)
    changed = created or history_migrated or summary_changed

    existing = _day_records(day)
    current: dict[str, tuple[str, Mapping[str, object]]] = {}
    for tier in (FIRST_TIER, SECOND_TIER, THIRD_TIER):
        values = tiers.get(tier, [])
        if not isinstance(values, (list, tuple)):
            continue
        for row in values:
            if not isinstance(row, Mapping):
                continue
            code = str(row.get("code", ""))
            if code and code not in current:
                current[code] = (tier, row)
            if code and code not in existing:
                record = _pick(row, trade_date, tier)
                if signal_base_date:
                    record["signal_base_date"] = _iso_date(signal_base_date)
                    record["signal_base_provenance"] = "selection_run"
                record["first_seen_at"] = generated_at
                day[tier].append(record)
                existing[code] = (tier, record)
                changed = True

    if "live_active_codes" in day and isinstance(day.get("live_active_codes"), list):
        previous_active = {
            str(code) for code in day.get("live_active_codes", []) if str(code)
        }
    else:
        previous_active = set(existing)
    current_codes = set(current)
    observed = {str(code) for code in observed_codes if str(code)}
    disappeared = (previous_active - current_codes) & observed
    reappeared = current_codes - previous_active

    removed_values = day.get("removed", [])
    removed_by_code = {
        str(item.get("code", "")): item
        for item in removed_values
        if (
            isinstance(item, dict)
            and item.get("code")
            and not bool(item.get("invalid_signal"))
        )
    }
    correction_by_code = {
        str(item.get("code", "")): item
        for item in removed_values
        if (
            isinstance(item, dict)
            and item.get("code")
            and bool(item.get("invalid_signal"))
        )
    }
    for code in sorted(disappeared):
        original = existing.get(code)
        if original is None:
            continue
        original_tier, original_record = original
        removed = removed_by_code.get(code)
        if removed is None:
            removed = copy.deepcopy(original_record)
            removed.update(
                {
                    "id": f"{trade_date}:removed:{code}",
                    "selected_tier": original_tier,
                    "removed_at": generated_at,
                    "removal_reason": "可能见底信号消失",
                    "removal_count": 1,
                    "active_again": False,
                    "restored_at": "",
                }
            )
            removed_values.append(removed)
            removed_by_code[code] = removed
        else:
            removed["removed_at"] = generated_at
            removed["removal_reason"] = "可能见底信号消失"
            removed["removal_count"] = int(removed.get("removal_count", 0) or 0) + 1
            removed["active_again"] = False
            removed["restored_at"] = ""
        correction = correction_by_code.get(code)
        if correction is not None:
            correction["active_again"] = False
            correction["restored_at"] = ""
        changed = True

    for code in sorted(reappeared):
        removed = removed_by_code.get(code)
        if removed is not None and not bool(removed.get("active_again")):
            removed["active_again"] = True
            removed["restored_at"] = generated_at
            changed = True
        correction = correction_by_code.get(code)
        if correction is not None and not bool(correction.get("active_again")):
            correction["active_again"] = True
            correction["restored_at"] = generated_at
            changed = True

    next_active = current_codes | (previous_active - observed)
    active_list = sorted(next_active)
    if active_list != sorted(
        str(code) for code in day.get("live_active_codes", []) if str(code)
    ):
        day["live_active_codes"] = active_list
        changed = True
    day["removed"] = removed_values
    if changed:
        working["updated_at"] = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
        working["summary"] = summarize(dates, trade_date)
    audited, _ = audit_history_signals(working, trading_dates, generated_at=generated_at)
    if audited != working:
        working = audited
        changed = True
    return working, changed


def _all_records(dates: Iterable[Mapping[str, object]]) -> list[dict]:
    records: list[dict] = []
    for day in dates:
        for key in (FIRST_TIER, SECOND_TIER, THIRD_TIER):
            values = day.get(key, [])
            if isinstance(values, list):
                records.extend(item for item in values if isinstance(item, dict) and _valid_record(item))
    return records


def summarize(
    dates: Iterable[Mapping[str, object]],
    reference_date: str = "",
) -> dict:
    date_values = list(dates)
    records = _all_records(date_values)
    settled = [
        item
        for item in records
        if _settled_record(item)
    ]
    successful = [item for item in settled if float(item.get("return_pct", 0.0)) > 0]
    average = (
        sum(float(item.get("return_pct", 0.0)) for item in settled) / len(settled)
        if settled
        else None
    )
    statistics_month = reference_date[:7] if len(reference_date) >= 7 else ""
    monthly_records = [
        item
        for item in records
        if statistics_month
        and str(item.get("trade_date", "")).startswith(f"{statistics_month}-")
    ]
    monthly_settled = [
        item
        for item in monthly_records
        if _settled_record(item)
    ]
    monthly_successful = [
        item
        for item in monthly_settled
        if float(item.get("return_pct", 0.0)) > 0
    ]
    return {
        "selection_count": len(records),
        "first_tier_count": sum(item.get("tier") == FIRST_TIER for item in records),
        "second_tier_count": sum(item.get("tier") == SECOND_TIER for item in records),
        "third_tier_count": sum(item.get("tier") == THIRD_TIER for item in records),
        "removed_count": len(
            {
                (str(day.get("trade_date", "")), str(item.get("code", "")))
                for day in date_values
                if isinstance(day, Mapping) and isinstance(day.get("removed"), list)
                for item in day.get("removed", [])
                if isinstance(item, Mapping) and item.get("code") and not item.get("invalid_signal")
            }
        ),
        "evaluated_count": len(settled),
        "success_count": len(successful),
        "success_rate_pct": len(successful) / len(settled) * 100.0 if settled else None,
        "average_return_pct": average,
        "invalid_signal_count": len({
            (str(day.get("trade_date", "")), str(item.get("code", "")))
            for day in date_values for item in day.get("removed", [])
            if isinstance(item, Mapping) and item.get("invalid_signal")
        }),
        "current_month": {
            "month": statistics_month,
            "selection_count": len(monthly_records),
            "evaluated_count": len(monthly_settled),
            "success_count": len(monthly_successful),
            "success_rate_pct": (
                len(monthly_successful) / len(monthly_settled) * 100.0
                if monthly_settled
                else None
            ),
        },
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
    updated["summary"] = summarize(dates, current_date)
    return updated


def record_close(
    history: Mapping[str, object],
    trade_date: str,
    tiers: Mapping[str, list[dict]],
    all_rows: Iterable[Mapping[str, object]],
    generated_at: str = "",
    *,
    trading_dates: Iterable[str] = (),
) -> dict:
    if history.get("strategy_version") != STRATEGY_VERSION:
        working = empty_history(trade_date)
    else:
        working = copy.deepcopy(dict(history))
    if not working.get("started_on"):
        working["started_on"] = trade_date

    prices = {
        str(item.get("code", "")): item
        for item in all_rows
        if item.get("code")
    }
    working, _ = record_intraday_pools(
        working,
        trade_date,
        tiers,
        prices,
        generated_at,
        signal_base_date=trade_date,
        trading_dates=trading_dates,
    )
    updated = refresh_history(working, prices, trade_date, generated_at)
    updated["last_close_trade_date"] = trade_date
    return updated


def write_history(path: Path, history: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
