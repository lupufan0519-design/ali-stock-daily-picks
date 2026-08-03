from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Sequence


POOL_NAME = "卢氏龙虎趋势池"
STATE_VERSION = 1
TREND_START_BREAKOUT_PCT = 5.0
TREND_START_MAX_WAIT_BARS = 10
DEFAULT_CROSS_LOOKBACK_DAYS = 11
TREND_PROFIT_ACTIVATION_PCT = 5.0
TREND_TRAILING_DRAWDOWN_PCT = 5.0
TREND_PENDING_DRAWDOWN_RATIO = 0.6
TREND_MAX_HOLDING_BARS = 60


def empty_state() -> dict:
    return {
        "version": STATE_VERSION,
        "pool_name": POOL_NAME,
        "last_trade_date": "",
        "active": [],
        "closed": [],
        "secondary_active": [],
        "secondary_closed": [],
        "pending_main": [],
        "pending_secondary": [],
    }


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != STATE_VERSION:
        raise ValueError("策略状态版本不兼容")
    data["pool_name"] = POOL_NAME
    data.setdefault("active", [])
    data.setdefault("closed", [])
    data.setdefault("secondary_active", [])
    data.setdefault("secondary_closed", [])
    data.setdefault("pending_main", [])
    data.setdefault("pending_secondary", [])
    data.setdefault("last_trade_date", "")
    for section in (
        "active",
        "closed",
        "secondary_active",
        "secondary_closed",
        "pending_main",
        "pending_secondary",
    ):
        for position in data[section]:
            for key in ("status", "exit_reason"):
                if isinstance(position.get(key), str):
                    position[key] = (
                        position[key]
                        .replace("红蓝", "龙虎")
                        .replace("红线", "龙线")
                        .replace("蓝线", "虎线")
                        .replace("龙线在虎线上方", "上升趋势中")
                        .replace("趋势转弱预警", "上升趋势中")
                        .replace("\u4e00\u8fb0", "卢氏")
                    )
            if section in {"pending_main", "pending_secondary"}:
                position["status"] = "待观察中"
            elif section in {"closed", "secondary_closed"}:
                if position.get("status") != "已移出":
                    position["status"] = "趋势结束"
            elif position.get("status") != "数据待确认":
                if position.get("missing_streak", 0):
                    position["status"] = "待观察中"
                elif position.get("entry_date") == position.get("last_date"):
                    position["status"] = "趋势开始"
                else:
                    position["status"] = "上升趋势中"
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _return_pct(entry_price: float, price: float) -> float:
    return (price / entry_price - 1.0) * 100.0 if entry_price else 0.0


def _is_st_name(name: str) -> bool:
    return "ST" in str(name).upper()


def _eligible(row: dict) -> bool:
    return bool(row.get("eligible", not _is_st_name(row.get("name", "")))) and not _is_st_name(row.get("name", ""))


def _dragon_above_tiger(row: dict) -> bool:
    # 兼容旧日报字段；严格入选本身已保证龙线在虎线上方。
    return bool(
        row.get(
            "dragon_above_tiger",
            row.get("red_above_blue", row.get("selected", False)),
        )
    )


def _secondary_selected(row: dict) -> bool:
    return bool(
        _eligible(row)
        and not row.get("selected")
        and row.get("cross_ok")
        and row.get("yellow_ok")
        and (row.get("bottom_ok") or row.get("limit_up_ok"))
    )


def _record_line_point(position: dict, row: dict, trade_date: str) -> None:
    try:
        dragon = float(row["dragon_value"])
        tiger = float(row["tiger_value"])
    except (KeyError, TypeError, ValueError):
        return
    if not (math.isfinite(dragon) and math.isfinite(tiger)):
        return
    history = position.setdefault("line_history", [])
    point = {"date": trade_date, "dragon": dragon, "tiger": tiger}
    if history and history[-1].get("date") == trade_date:
        history[-1] = point
    else:
        history.append(point)
    del history[:-3]


def _trend_is_weakening(position: dict, row: dict) -> bool:
    if not _dragon_above_tiger(row):
        return True
    history = list(position.get("line_history", []))
    try:
        row_dragon = float(row["dragon_value"])
        row_tiger = float(row["tiger_value"])
        row_date = str(
            row.get("date")
            or row.get("server_time", "")[:10]
            or position.get("last_date", "")
        )
    except (KeyError, TypeError, ValueError):
        row_date = ""
    else:
        if math.isfinite(row_dragon) and math.isfinite(row_tiger):
            point = {
                "date": row_date,
                "dragon": row_dragon,
                "tiger": row_tiger,
            }
            if history and history[-1].get("date") == row_date:
                history[-1] = point
            else:
                history.append(point)
    if len(history) < 3:
        return False
    latest = history[-3:]
    if any(
        str(item.get("date", "")) < str(position["entry_date"])
        for item in latest
    ):
        return False
    dragons = [float(item["dragon"]) for item in latest]
    spreads = [
        float(item["dragon"]) - float(item["tiger"])
        for item in latest
    ]
    if (
        dragons[0] > dragons[1] > dragons[2]
        and spreads[0] > spreads[1] > spreads[2]
    ):
        return True
    return False


def _peak_drawdown_pct(position: dict, price: float | None = None) -> float | None:
    entry_price = float(position.get("entry_price", 0.0))
    current_price = float(
        position.get("last_close", 0.0) if price is None else price
    )
    if entry_price <= 0 or current_price <= 0:
        return None
    current_return = _return_pct(entry_price, current_price)
    best_return = max(
        float(position.get("best_return_pct", current_return)),
        current_return,
    )
    peak_price = entry_price * (1.0 + best_return / 100.0)
    if peak_price <= 0:
        return None
    return (current_price / peak_price - 1.0) * 100.0


def _row_cross_age(row: dict) -> int:
    value = row.get("cross_age")
    if value is None and isinstance(row.get("live_seed"), dict):
        value = row["live_seed"].get("cross_age")
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _row_cross_lookback(row: dict) -> int:
    value = row.get("cross_lookback_days")
    if value is None and isinstance(row.get("live_seed"), dict):
        value = row["live_seed"].get("cross_lookback_days")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_CROSS_LOOKBACK_DAYS
    return max(1, parsed)


def signal_recalculated_away(
    setup: dict,
    row: dict | None,
    elapsed_bars: int | None = None,
) -> bool:
    """True only when a still-young crossover is erased by XMA recalculation."""
    if row is None or row.get("cross_ok") or not _dragon_above_tiger(row):
        return False
    try:
        cross_age = int(setup.get("setup_cross_age", -1))
        lookback = int(
            setup.get(
                "setup_cross_lookback_days",
                DEFAULT_CROSS_LOOKBACK_DAYS,
            )
        )
    except (TypeError, ValueError):
        return False
    if cross_age < 0 or lookback <= 0:
        return False
    if elapsed_bars is None:
        elapsed_bars = int(setup.get("setup_elapsed_bars", 0))
    return cross_age + max(0, int(elapsed_bars)) < lookback


def trend_exit_reason(
    position: dict,
    price: float | None = None,
    dragon_above_tiger: bool | None = None,
    signal_erased: bool = False,
) -> str:
    """Return the shared close/intraday trend-ending reason without mutating state."""
    if signal_erased:
        return "趋势结束：龙腾跃虎信号被后续K线重算消失"
    if dragon_above_tiger is False:
        return "趋势结束：龙线不再高于虎线，龙腾跃虎多头关系消失"
    elapsed_bars = max(0, int(position.get("holding_days", 1)) - 1)
    if elapsed_bars >= TREND_MAX_HOLDING_BARS:
        return "趋势结束：已完成60个后续交易日跟踪"
    best_return = float(position.get("best_return_pct", 0.0))
    if price is not None:
        entry_price = float(position.get("entry_price", 0.0))
        if entry_price > 0 and float(price) > 0:
            best_return = max(best_return, _return_pct(entry_price, float(price)))
    if best_return < TREND_PROFIT_ACTIVATION_PCT:
        return ""
    peak_drawdown = _peak_drawdown_pct(position, price)
    if (
        peak_drawdown is not None
        and peak_drawdown <= -TREND_TRAILING_DRAWDOWN_PCT + 1e-8
    ):
        return "趋势结束：达到5%浮盈后较最高收盘回撤5%"
    return ""


def trend_pending_reason(
    position: dict,
    row: dict | None = None,
    price: float | None = None,
) -> str:
    reasons: list[str] = []
    if row is not None and _trend_is_weakening(position, row):
        reasons.append("龙虎差与龙线同步转弱")
    best_return = float(position.get("best_return_pct", 0.0))
    if price is not None:
        entry_price = float(position.get("entry_price", 0.0))
        if entry_price > 0 and float(price) > 0:
            best_return = max(best_return, _return_pct(entry_price, float(price)))
    peak_drawdown = _peak_drawdown_pct(position, price)
    warning_drawdown = (
        TREND_TRAILING_DRAWDOWN_PCT * TREND_PENDING_DRAWDOWN_RATIO
    )
    if (
        best_return >= TREND_PROFIT_ACTIVATION_PCT
        and peak_drawdown is not None
        and peak_drawdown <= -warning_drawdown + 1e-8
    ):
        reasons.append("已接近回撤止盈线")
    return "；".join(dict.fromkeys(reasons))


def _take_profit_exit_reason(position: dict, row: dict) -> str:
    setup_elapsed = int(position.get("setup_elapsed_bars_at_entry", 0)) + max(
        0,
        int(position.get("holding_days", 1)) - 1,
    )
    reason = trend_exit_reason(
        position,
        dragon_above_tiger=_dragon_above_tiger(row),
        signal_erased=signal_recalculated_away(
            position,
            row,
            setup_elapsed,
        ),
    )
    peak_drawdown = _peak_drawdown_pct(position)
    if peak_drawdown is not None:
        position["peak_drawdown_pct"] = peak_drawdown
    return reason


def _new_pending_setup(row: dict, trade_date: str, area: str) -> dict:
    price = float(row["close"])
    cross_age = _row_cross_age(row)
    return {
        "setup_id": f"{area}_{row['code']}_{trade_date}",
        "code": str(row["code"]),
        "name": str(row["name"]),
        "market": int(row["market"]),
        "area": area,
        "origin_area": area,
        "setup_date": trade_date,
        "setup_price": price,
        "last_date": trade_date,
        "last_close": price,
        "setup_cross_date": str(row.get("cross_date", "")),
        "setup_cross_age": cross_age,
        "setup_cross_lookback_days": _row_cross_lookback(row),
        "setup_elapsed_bars": 0,
        "status": "待观察中",
        "status_detail": "入选信号已形成，等待收盘较信号日上涨5%确认趋势开始",
        "selected_dates": [trade_date],
    }


def _confirmed_position(setup: dict, row: dict, trade_date: str) -> dict:
    price = float(row["close"])
    position = {
        "position_id": f"{row['code']}_{trade_date}",
        "code": str(row["code"]),
        "name": str(row["name"]),
        "market": int(row["market"]),
        "entry_date": trade_date,
        "entry_price": price,
        "last_date": trade_date,
        "last_close": price,
        "return_pct": 0.0,
        "best_return_pct": 0.0,
        "worst_return_pct": 0.0,
        "holding_days": 1,
        "missing_streak": 0,
        "signal_lost_date": "",
        "status": "趋势开始",
        "status_detail": "收盘较信号日上涨5%，确认建议买点",
        "line_history": [],
        "selected_dates": list(setup.get("selected_dates", [])),
        "signal_setup_date": str(setup["setup_date"]),
        "signal_setup_price": float(setup["setup_price"]),
        "setup_cross_date": str(setup.get("setup_cross_date", "")),
        "setup_cross_age": int(setup.get("setup_cross_age", -1)),
        "setup_cross_lookback_days": int(
            setup.get(
                "setup_cross_lookback_days",
                DEFAULT_CROSS_LOOKBACK_DAYS,
            )
        ),
        "setup_elapsed_bars_at_entry": int(
            setup.get("setup_elapsed_bars", 0)
        ),
        "entry_rule": "信号持续且收盘较信号日上涨5%",
        "origin_area": str(
            setup.get("origin_area", setup.get("area", "secondary"))
        ),
    }
    if trade_date not in position["selected_dates"]:
        position["selected_dates"].append(trade_date)
    _record_line_point(position, row, trade_date)
    return position


def _advance_pending_setups(
    pending: Sequence[dict],
    row_by_code: dict[str, dict],
    trade_date: str,
    is_new_day: bool,
    area: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    remaining: list[dict] = []
    confirmed: list[dict] = []
    events: list[dict] = []
    for setup in pending:
        row = row_by_code.get(str(setup["code"]))
        if row is None:
            setup["status"] = "数据待确认"
            remaining.append(setup)
            continue
        setup["last_date"] = trade_date
        setup["last_close"] = float(row["close"])
        if is_new_day and trade_date > str(setup["setup_date"]):
            setup["setup_elapsed_bars"] = int(
                setup.get("setup_elapsed_bars", 0)
            ) + 1
        elapsed = int(setup.get("setup_elapsed_bars", 0))
        if not _eligible(row):
            events.append(
                {
                    "type": "setup_cancelled",
                    "code": setup["code"],
                    "name": setup["name"],
                    "reason": "股票名称含 ST",
                }
            )
            continue
        if signal_recalculated_away(setup, row, elapsed):
            events.append(
                {
                    "type": "setup_cancelled",
                    "code": setup["code"],
                    "name": setup["name"],
                    "reason": "龙腾跃虎信号被K线重算消失",
                }
            )
            continue
        if not _dragon_above_tiger(row):
            events.append(
                {
                    "type": "setup_cancelled",
                    "code": setup["code"],
                    "name": setup["name"],
                    "reason": "龙线不再高于虎线",
                }
            )
            continue
        if elapsed > TREND_START_MAX_WAIT_BARS:
            events.append(
                {
                    "type": "setup_cancelled",
                    "code": setup["code"],
                    "name": setup["name"],
                    "reason": "10个交易日内未确认上涨趋势",
                }
            )
            continue
        setup_return = _return_pct(
            float(setup["setup_price"]),
            float(setup["last_close"]),
        )
        if elapsed > 0 and setup_return >= TREND_START_BREAKOUT_PCT:
            position = _confirmed_position(setup, row, trade_date)
            confirmed.append(position)
            events.append(
                {
                    "type": "trend_started",
                    "code": setup["code"],
                    "name": setup["name"],
                    "area": area,
                    "setup_return_pct": setup_return,
                }
            )
            continue
        gap = max(0.0, TREND_START_BREAKOUT_PCT - setup_return)
        setup["status"] = "待观察中"
        setup["status_detail"] = (
            f"信号仍有效，距趋势开始确认约差{gap:.2f}个百分点"
        )
        if row.get("selected"):
            dates = setup.setdefault("selected_dates", [])
            if trade_date not in dates:
                dates.append(trade_date)
        remaining.append(setup)
    return remaining, confirmed, events


def update_state(state: dict, rows: Sequence[dict], trade_date: str) -> tuple[dict, list[dict]]:
    """处理一个交易日；同一日期重复运行不会重复累计消失天数。"""
    state = deepcopy(state)
    row_by_code = {str(row["code"]): row for row in rows}
    is_new_day = not state["last_trade_date"] or trade_date > state["last_trade_date"]
    events: list[dict] = []
    exited_codes: set[str] = set()
    setup_cancelled_codes: set[str] = set()
    still_active: list[dict] = []

    for position in state["active"]:
        row = row_by_code.get(position["code"])
        if row is None:
            position["status"] = "数据待确认"
            still_active.append(position)
            continue

        position["last_date"] = trade_date
        position["last_close"] = float(row["close"])
        position["return_pct"] = _return_pct(
            float(position["entry_price"]), position["last_close"]
        )
        position["best_return_pct"] = max(
            float(position.get("best_return_pct", position["return_pct"])),
            position["return_pct"],
        )
        position["worst_return_pct"] = min(
            float(position.get("worst_return_pct", position["return_pct"])),
            position["return_pct"],
        )
        _record_line_point(position, row, trade_date)

        is_later_day = is_new_day and trade_date > position["entry_date"]
        if is_later_day:
            position["holding_days"] = int(position.get("holding_days", 1)) + 1

        if not _eligible(row):
            position["status"] = "已移出"
            position["exit_date"] = trade_date
            position["exit_price"] = position["last_close"]
            position["exit_return_pct"] = position["return_pct"]
            position["exit_reason"] = "股票名称含 ST，不符合入选范围"
            state["closed"].append(position)
            exited_codes.add(str(position["code"]))
            events.append({"type": "ineligible_removed", "code": position["code"], "name": str(row.get("name", position["name"])), "return_pct": position["return_pct"]})
            continue

        if is_later_day:
            exit_reason = _take_profit_exit_reason(position, row)
            if exit_reason:
                position["status"] = "趋势结束"
                position["exit_date"] = trade_date
                position["exit_price"] = position["last_close"]
                position["exit_return_pct"] = position["return_pct"]
                position["exit_reason"] = exit_reason
                state["closed"].append(position)
                exited_codes.add(str(position["code"]))
                events.append({"type": "removed", "code": position["code"], "name": position["name"], "return_pct": position["return_pct"]})
                continue
            pending_reason = trend_pending_reason(position, row)
            if pending_reason:
                if not position.get("missing_streak", 0):
                    events.append({"type": "trend_warning", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 1
                position["signal_lost_date"] = trade_date
                position["status"] = "待观察中"
                position["status_detail"] = pending_reason
            else:
                if position.get("missing_streak", 0):
                    events.append({"type": "signal_restored", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 0
                position["signal_lost_date"] = ""
                position["status"] = "上升趋势中"
                position["status_detail"] = "趋势条件仍有效"
        elif not position.get("status"):
            position["status"] = "趋势开始"
        still_active.append(position)

    state["active"] = still_active
    secondary_pending_remaining: list[dict] = []
    for setup in state.get("pending_secondary", []):
        row = row_by_code.get(str(setup["code"]))
        if row is not None and row.get("selected") and _eligible(row):
            setup["area"] = "main"
            state["pending_main"].append(setup)
            events.append(
                {
                    "type": "setup_promoted",
                    "code": setup["code"],
                    "name": setup["name"],
                }
            )
        else:
            secondary_pending_remaining.append(setup)
    state["pending_secondary"] = secondary_pending_remaining

    pending_main, confirmed_main, pending_events = _advance_pending_setups(
        state.get("pending_main", []),
        row_by_code,
        trade_date,
        is_new_day,
        "main",
    )
    state["pending_main"] = pending_main
    state["active"].extend(confirmed_main)
    events.extend(pending_events)
    setup_cancelled_codes.update(
        str(event["code"])
        for event in pending_events
        if event.get("type") == "setup_cancelled"
    )
    active_by_code = {position["code"]: position for position in state["active"]}
    pending_main_codes = {
        str(setup["code"]) for setup in state.get("pending_main", [])
    }
    secondary_position_codes = {
        position["code"] for position in state["secondary_active"]
    }
    secondary_pending_codes = {
        str(setup["code"])
        for setup in state.get("pending_secondary", [])
    }
    for row in rows:
        if not _eligible(row) or not row.get("selected"):
            continue
        code = str(row["code"])
        if code in exited_codes or code in setup_cancelled_codes:
            continue
        if code in active_by_code:
            dates = active_by_code[code].setdefault("selected_dates", [])
            if trade_date not in dates:
                dates.append(trade_date)
            continue
        if code in pending_main_codes:
            continue
        if code in secondary_position_codes or code in secondary_pending_codes:
            # 次选升级由下方流程原位转入，保留最初加入日和加入价。
            continue
        setup = _new_pending_setup(row, trade_date, "main")
        state["pending_main"].append(setup)
        pending_main_codes.add(code)
        events.append({"type": "setup_added", "code": code, "name": setup["name"]})

    secondary_still_active: list[dict] = []
    for position in state["secondary_active"]:
        row = row_by_code.get(position["code"])
        if row is None:
            position["status"] = "数据待确认"
            secondary_still_active.append(position)
            continue

        position["last_date"] = trade_date
        position["last_close"] = float(row["close"])
        position["return_pct"] = _return_pct(
            float(position["entry_price"]), position["last_close"]
        )
        position["best_return_pct"] = max(
            float(position.get("best_return_pct", position["return_pct"])),
            position["return_pct"],
        )
        position["worst_return_pct"] = min(
            float(position.get("worst_return_pct", position["return_pct"])),
            position["return_pct"],
        )
        _record_line_point(position, row, trade_date)

        is_later_day = is_new_day and trade_date > position["entry_date"]
        if is_later_day:
            position["holding_days"] = int(position.get("holding_days", 1)) + 1

        if not _eligible(row):
            position["status"] = "已移出"
            position["exit_date"] = trade_date
            position["exit_price"] = position["last_close"]
            position["exit_return_pct"] = position["return_pct"]
            position["exit_reason"] = "股票名称含 ST，不符合入选范围"
            state["secondary_closed"].append(position)
            exited_codes.add(str(position["code"]))
            events.append({"type": "ineligible_removed", "code": position["code"], "name": str(row.get("name", position["name"])), "return_pct": position["return_pct"]})
            continue

        if is_later_day:
            exit_reason = _take_profit_exit_reason(position, row)
            event_type = ""
            if exit_reason:
                event_type = "secondary_removed"
            elif row.get("selected"):
                event_type = "secondary_promoted"
                position["status"] = "上升趋势中"
                position["origin_area"] = position.get(
                    "origin_area",
                    "secondary",
                )
                dates = position.setdefault("selected_dates", [])
                if trade_date not in dates:
                    dates.append(trade_date)
                state["active"].append(position)
                active_by_code[position["code"]] = position
                events.append({
                    "type": event_type,
                    "code": position["code"],
                    "name": position["name"],
                    "return_pct": position["return_pct"],
                })
                continue
            if exit_reason:
                position["status"] = "趋势结束"
                position["exit_date"] = trade_date
                position["exit_price"] = position["last_close"]
                position["exit_return_pct"] = position["return_pct"]
                position["exit_reason"] = exit_reason
                state["secondary_closed"].append(position)
                exited_codes.add(str(position["code"]))
                events.append({
                    "type": event_type,
                    "code": position["code"],
                    "name": position["name"],
                    "return_pct": position["return_pct"],
                })
                continue
            pending_reason = trend_pending_reason(position, row)
            if pending_reason:
                if not position.get("missing_streak", 0):
                    events.append({"type": "trend_warning", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 1
                position["signal_lost_date"] = trade_date
                position["status"] = "待观察中"
                position["status_detail"] = pending_reason
            else:
                if position.get("missing_streak", 0):
                    events.append({"type": "signal_restored", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 0
                position["signal_lost_date"] = ""
                position["status"] = "上升趋势中"
                position["status_detail"] = "趋势条件仍有效"
        elif not position.get("status"):
            position["status"] = "趋势开始"
        secondary_still_active.append(position)

    state["secondary_active"] = secondary_still_active
    pending_secondary, confirmed_secondary, pending_events = (
        _advance_pending_setups(
            state.get("pending_secondary", []),
            row_by_code,
            trade_date,
            is_new_day,
            "secondary",
        )
    )
    state["pending_secondary"] = pending_secondary
    state["secondary_active"].extend(confirmed_secondary)
    events.extend(pending_events)
    setup_cancelled_codes.update(
        str(event["code"])
        for event in pending_events
        if event.get("type") == "setup_cancelled"
    )
    secondary_by_code = {
        position["code"]: position for position in state["secondary_active"]
    }
    secondary_pending_codes = {
        str(setup["code"])
        for setup in state.get("pending_secondary", [])
    }
    primary_codes = {
        position["code"] for position in state["active"]
    } | {
        str(setup["code"]) for setup in state.get("pending_main", [])
    }
    for row in rows:
        if not _secondary_selected(row):
            continue
        code = str(row["code"])
        if code in exited_codes or code in setup_cancelled_codes:
            continue
        if code in primary_codes:
            continue
        if code in secondary_by_code:
            dates = secondary_by_code[code].setdefault("selected_dates", [])
            if trade_date not in dates:
                dates.append(trade_date)
            continue
        if code in secondary_pending_codes:
            continue
        setup = _new_pending_setup(row, trade_date, "secondary")
        state["pending_secondary"].append(setup)
        secondary_pending_codes.add(code)
        events.append({"type": "secondary_setup_added", "code": code, "name": setup["name"]})

    state["active"].sort(key=lambda x: (x["entry_date"], x["code"]))
    state["closed"].sort(key=lambda x: (x.get("exit_date", ""), x["code"]), reverse=True)
    state["secondary_active"].sort(key=lambda x: (x["entry_date"], x["code"]))
    state["secondary_closed"].sort(
        key=lambda x: (x.get("exit_date", ""), x["code"]), reverse=True
    )
    state["pending_main"].sort(
        key=lambda x: (x.get("setup_date", ""), x["code"])
    )
    state["pending_secondary"].sort(
        key=lambda x: (x.get("setup_date", ""), x["code"])
    )
    if is_new_day:
        state["last_trade_date"] = trade_date
    return state, events


def bootstrap_state(state_path: Path, results_dir: Path) -> dict:
    if state_path.exists():
        return load_state(state_path)
    return replay_state(results_dir)


def replay_state(results_dir: Path, through_date: str = "") -> dict:
    state = empty_state()
    for path in sorted(results_dir.glob("选股结果_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            trade_date = str(payload["trade_date"])
            if through_date and trade_date > through_date:
                continue
            state, _ = update_state(state, payload.get("results", []), trade_date)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return state


def strategy_stats(state: dict) -> dict:
    active_returns = [float(x.get("return_pct", 0.0)) for x in state["active"]]
    closed_returns = [float(x.get("exit_return_pct", 0.0)) for x in state["closed"]]
    realized_factor = math.prod(1.0 + value / 100.0 for value in closed_returns)
    return {
        "active_count": len(active_returns),
        "closed_count": len(closed_returns),
        "warning_count": sum(int(x.get("missing_streak", 0)) == 1 for x in state["active"]),
        "current_success_rate": (sum(value > 0 for value in closed_returns) / len(closed_returns) * 100.0) if closed_returns else None,
        "closed_success_rate": (sum(value > 0 for value in closed_returns) / len(closed_returns) * 100.0) if closed_returns else None,
        "active_average_return": sum(active_returns) / len(active_returns) if active_returns else None,
        "all_average_return": sum(closed_returns) / len(closed_returns) if closed_returns else None,
        "realized_compound_return": (realized_factor - 1.0) * 100.0 if closed_returns else None,
        "best_return": max(closed_returns) if closed_returns else None,
        "worst_return": min(closed_returns) if closed_returns else None,
        "sample_count": len(closed_returns),
        "success_definition": "趋势结束价高于趋势开始价；未结束样本不计入",
    }


def secondary_strategy_stats(state: dict) -> dict:
    active_returns = [
        float(x.get("return_pct", 0.0)) for x in state.get("secondary_active", [])
    ]
    closed_returns = [
        float(x.get("exit_return_pct", 0.0))
        for x in state.get("secondary_closed", [])
    ]
    realized_factor = math.prod(1.0 + value / 100.0 for value in closed_returns)
    return {
        "active_count": len(active_returns),
        "closed_count": len(closed_returns),
        "current_success_rate": (
            sum(value > 0 for value in closed_returns) / len(closed_returns) * 100.0
        ) if closed_returns else None,
        "closed_success_rate": (
            sum(value > 0 for value in closed_returns) / len(closed_returns) * 100.0
        ) if closed_returns else None,
        "active_average_return": (
            sum(active_returns) / len(active_returns) if active_returns else None
        ),
        "all_average_return": (
            sum(closed_returns) / len(closed_returns) if closed_returns else None
        ),
        "realized_compound_return": (
            (realized_factor - 1.0) * 100.0 if closed_returns else None
        ),
        "sample_count": len(closed_returns),
        "success_definition": "趋势结束价高于趋势开始价；未结束样本不计入",
    }
