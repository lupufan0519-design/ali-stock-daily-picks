from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Sequence


POOL_NAME = "卢氏龙虎趋势池"
STATE_VERSION = 1


def empty_state() -> dict:
    return {
        "version": STATE_VERSION,
        "pool_name": POOL_NAME,
        "last_trade_date": "",
        "active": [],
        "closed": [],
        "secondary_active": [],
        "secondary_closed": [],
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
    data.setdefault("last_trade_date", "")
    for section in ("active", "closed", "secondary_active", "secondary_closed"):
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
    history = position.get("line_history", [])
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


def trend_exit_reason(position: dict, price: float | None = None) -> str:
    """Return the shared close/intraday trend-ending reason without mutating state."""
    elapsed_bars = max(0, int(position.get("holding_days", 1)) - 1)
    if elapsed_bars >= 60:
        return "趋势结束：已完成60个后续交易日跟踪"
    best_return = float(position.get("best_return_pct", 0.0))
    if best_return < 5.0:
        return ""
    entry_price = float(position.get("entry_price", 0.0))
    peak_price = entry_price * (1.0 + best_return / 100.0)
    current_price = float(
        position.get("last_close", 0.0) if price is None else price
    )
    if peak_price <= 0 or current_price <= 0:
        return ""
    peak_drawdown = (current_price / peak_price - 1.0) * 100.0
    if peak_drawdown <= -20.0 + 1e-8:
        return "趋势结束：达到5%浮盈后较最高收盘回撤20%"
    return ""


def _take_profit_exit_reason(position: dict) -> str:
    reason = trend_exit_reason(position)
    best_return = float(position.get("best_return_pct", 0.0))
    entry_price = float(position.get("entry_price", 0.0))
    last_close = float(position.get("last_close", 0.0))
    peak_price = entry_price * (1.0 + best_return / 100.0)
    if best_return >= 5.0 and peak_price > 0 and last_close > 0:
        position["peak_drawdown_pct"] = (
            last_close / peak_price - 1.0
        ) * 100.0
    return reason


def update_state(state: dict, rows: Sequence[dict], trade_date: str) -> tuple[dict, list[dict]]:
    """处理一个交易日；同一日期重复运行不会重复累计消失天数。"""
    state = deepcopy(state)
    row_by_code = {str(row["code"]): row for row in rows}
    is_new_day = not state["last_trade_date"] or trade_date > state["last_trade_date"]
    events: list[dict] = []
    exited_codes: set[str] = set()
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
            exit_reason = _take_profit_exit_reason(position)
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
            if _trend_is_weakening(position, row):
                if not position.get("missing_streak", 0):
                    events.append({"type": "trend_warning", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 1
                position["signal_lost_date"] = trade_date
                position["status"] = "上升趋势中"
            else:
                if position.get("missing_streak", 0):
                    events.append({"type": "signal_restored", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 0
                position["signal_lost_date"] = ""
                position["status"] = "上升趋势中"
        elif not position.get("status"):
            position["status"] = "上升趋势中"
        still_active.append(position)

    state["active"] = still_active
    active_by_code = {position["code"]: position for position in state["active"]}
    secondary_position_codes = {
        position["code"] for position in state["secondary_active"]
    }
    for row in rows:
        if not _eligible(row) or not row.get("selected"):
            continue
        code = str(row["code"])
        if code in exited_codes:
            continue
        if code in active_by_code:
            dates = active_by_code[code].setdefault("selected_dates", [])
            if trade_date not in dates:
                dates.append(trade_date)
            continue
        if code in secondary_position_codes:
            # 次选升级由下方流程原位转入，保留最初加入日和加入价。
            continue
        price = float(row["close"])
        position = {
            "position_id": f"{code}_{trade_date}",
            "code": code,
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
            "status": "上升趋势中",
            "line_history": [],
            "selected_dates": [trade_date],
        }
        _record_line_point(position, row, trade_date)
        state["active"].append(position)
        active_by_code[code] = position
        events.append({"type": "added", "code": code, "name": position["name"]})

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
            exit_reason = _take_profit_exit_reason(position)
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
            if _trend_is_weakening(position, row):
                if not position.get("missing_streak", 0):
                    events.append({"type": "trend_warning", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 1
                position["signal_lost_date"] = trade_date
                position["status"] = "上升趋势中"
            else:
                if position.get("missing_streak", 0):
                    events.append({"type": "signal_restored", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 0
                position["signal_lost_date"] = ""
                position["status"] = "上升趋势中"
        elif not position.get("status"):
            position["status"] = "上升趋势中"
        secondary_still_active.append(position)

    state["secondary_active"] = secondary_still_active
    secondary_by_code = {
        position["code"]: position for position in state["secondary_active"]
    }
    primary_codes = {position["code"] for position in state["active"]}
    for row in rows:
        if not _secondary_selected(row):
            continue
        code = str(row["code"])
        if code in exited_codes:
            continue
        if code in primary_codes:
            continue
        if code in secondary_by_code:
            dates = secondary_by_code[code].setdefault("selected_dates", [])
            if trade_date not in dates:
                dates.append(trade_date)
            continue
        price = float(row["close"])
        position = {
            "position_id": f"secondary_{code}_{trade_date}",
            "code": code,
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
            "status": "上升趋势中",
            "line_history": [],
            "selected_dates": [trade_date],
        }
        _record_line_point(position, row, trade_date)
        state["secondary_active"].append(position)
        secondary_by_code[code] = position
        events.append({"type": "secondary_added", "code": code, "name": position["name"]})

    state["active"].sort(key=lambda x: (x["entry_date"], x["code"]))
    state["closed"].sort(key=lambda x: (x.get("exit_date", ""), x["code"]), reverse=True)
    state["secondary_active"].sort(key=lambda x: (x["entry_date"], x["code"]))
    state["secondary_closed"].sort(
        key=lambda x: (x.get("exit_date", ""), x["code"]), reverse=True
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
    all_returns = active_returns + closed_returns
    realized_factor = math.prod(1.0 + value / 100.0 for value in closed_returns)
    return {
        "active_count": len(active_returns),
        "closed_count": len(closed_returns),
        "warning_count": sum(int(x.get("missing_streak", 0)) == 1 for x in state["active"]),
        "current_success_rate": (sum(value > 0 for value in all_returns) / len(all_returns) * 100.0) if all_returns else None,
        "closed_success_rate": (sum(value > 0 for value in closed_returns) / len(closed_returns) * 100.0) if closed_returns else None,
        "active_average_return": sum(active_returns) / len(active_returns) if active_returns else None,
        "all_average_return": sum(all_returns) / len(all_returns) if all_returns else None,
        "realized_compound_return": (realized_factor - 1.0) * 100.0 if closed_returns else None,
        "best_return": max(all_returns) if all_returns else None,
        "worst_return": min(all_returns) if all_returns else None,
        "sample_count": len(all_returns),
    }


def secondary_strategy_stats(state: dict) -> dict:
    active_returns = [
        float(x.get("return_pct", 0.0)) for x in state.get("secondary_active", [])
    ]
    closed_returns = [
        float(x.get("exit_return_pct", 0.0))
        for x in state.get("secondary_closed", [])
    ]
    all_returns = active_returns + closed_returns
    realized_factor = math.prod(1.0 + value / 100.0 for value in closed_returns)
    return {
        "active_count": len(active_returns),
        "closed_count": len(closed_returns),
        "current_success_rate": (
            sum(value > 0 for value in all_returns) / len(all_returns) * 100.0
        ) if all_returns else None,
        "closed_success_rate": (
            sum(value > 0 for value in closed_returns) / len(closed_returns) * 100.0
        ) if closed_returns else None,
        "active_average_return": (
            sum(active_returns) / len(active_returns) if active_returns else None
        ),
        "all_average_return": (
            sum(all_returns) / len(all_returns) if all_returns else None
        ),
        "realized_compound_return": (
            (realized_factor - 1.0) * 100.0 if closed_returns else None
        ),
        "sample_count": len(all_returns),
    }
