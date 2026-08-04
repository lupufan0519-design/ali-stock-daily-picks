from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Sequence

from strategy_contract import (
    ENTRY_DELAY_BARS,
    ENTRY_EXECUTION_MAX_WAIT_BARS,
    ENTRY_MAX_PULLBACK_PCT,
    EXIT_MAX_HOLDING_BARS,
    EXIT_PROFIT_ACTIVATION_PCT,
    EXIT_TRAILING_DRAWDOWN_PCT,
    EXIT_WEAKENING_CONFIRMATIONS,
    EXIT_WEAKENING_POINTS,
    LIVE_STRATEGY_ID,
)


POOL_NAME = "卢氏龙虎趋势池"
STATE_VERSION = 1
CURRENT_STRATEGY_VERSION = LIVE_STRATEGY_ID
LEGACY_STRATEGY_VERSION = "legacy_before_break5_trail3_2"
TREND_START_LOOKBACK_BARS = 5
TREND_START_MAX_WAIT_BARS = 10
DEFAULT_CROSS_LOOKBACK_DAYS = 8
TREND_PROFIT_ACTIVATION_PCT = 3.0
TREND_TRAILING_DRAWDOWN_PCT = 2.0
TREND_PENDING_DRAWDOWN_RATIO = 0.5
TREND_MAX_HOLDING_BARS = EXIT_MAX_HOLDING_BARS


def empty_state() -> dict:
    return {
        "version": STATE_VERSION,
        "strategy_version": CURRENT_STRATEGY_VERSION,
        "pool_name": POOL_NAME,
        "last_trade_date": "",
        "active": [],
        "closed": [],
        "secondary_active": [],
        "secondary_closed": [],
        "pending_main": [],
        "pending_secondary": [],
        "pending_entry_execution": [],
        "pending_exit_execution": [],
        "consumed_signals": [],
        "active_signal_lineages": [],
    }


def _uses_current_strategy(item: dict) -> bool:
    return str(item.get("strategy_version", "")) == CURRENT_STRATEGY_VERSION


def load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != STATE_VERSION:
        raise ValueError("策略状态版本不兼容")
    stored_strategy_version = str(data.get("strategy_version", ""))
    data["pool_name"] = POOL_NAME
    data["strategy_version"] = CURRENT_STRATEGY_VERSION
    data.setdefault("active", [])
    data.setdefault("closed", [])
    data.setdefault("secondary_active", [])
    data.setdefault("secondary_closed", [])
    data.setdefault("pending_main", [])
    data.setdefault("pending_secondary", [])
    data.setdefault("pending_entry_execution", [])
    data.setdefault("pending_exit_execution", [])
    data.setdefault("active_signal_lineages", [])
    data.setdefault("last_trade_date", "")
    for section in (
        "active",
        "closed",
        "secondary_active",
        "secondary_closed",
        "pending_main",
        "pending_secondary",
        "pending_entry_execution",
        "pending_exit_execution",
    ):
        for position in data[section]:
            if not position.get("strategy_version"):
                # 新策略生成的记录始终显式携带版本。无版本记录只能按旧策略
                # 处理，避免一次状态头升级把历史持仓误计入新策略绩效。
                position["strategy_version"] = LEGACY_STRATEGY_VERSION
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
                position["operation"] = (
                    "等待D+2收盘确认"
                    if _uses_current_strategy(position)
                    else "等待买入"
                )
            elif section == "pending_entry_execution":
                position["status"] = "买点已确认"
                position["operation"] = "下一交易日开盘买入"
            elif section == "pending_exit_execution":
                position["status"] = "卖点已确认"
                position["operation"] = "下一交易日开盘卖出"
            elif section in {"closed", "secondary_closed"}:
                if position.get("status") != "已移出":
                    position["status"] = "趋势结束"
                position["operation"] = (
                    "开盘已执行卖出"
                    if position.get("exit_trigger_date")
                    and position.get("exit_date")
                    else "建议卖出"
                )
            elif position.get("status") != "数据待确认":
                if position.get("missing_streak", 0):
                    position["status"] = "待观察中"
                    position["operation"] = "谨慎持有"
                elif position.get("entry_date") == position.get("last_date"):
                    position["status"] = "趋势开始"
                    position["operation"] = (
                        "开盘已执行买入"
                        if position.get("entry_trigger_date")
                        else "建议买入"
                    )
                else:
                    position["status"] = "上升趋势中"
                    position["operation"] = "继续持有"
    # Build the tombstone set before a strategy migration clears old pending
    # setups.  Otherwise the same historical crossover can be recreated on the
    # next daily run even though that setup was already consumed.
    consumed_signals = _stored_signal_keys(data.get("consumed_signals", []))
    active_signal_lineages = _stored_signal_lineages(
        data.get("active_signal_lineages", [])
    )
    for section in (
        "active",
        "closed",
        "secondary_active",
        "secondary_closed",
        "pending_main",
        "pending_secondary",
        "pending_entry_execution",
        "pending_exit_execution",
    ):
        consumed_signals.update(
            key
            for item in data.get(section, [])
            if (
                key := _signal_key(
                    item.get("code"),
                    item.get("setup_cross_date") or item.get("cross_date"),
                )
            )
        )
    for section in (
        "active",
        "secondary_active",
        "pending_main",
        "pending_secondary",
        "pending_entry_execution",
        "pending_exit_execution",
    ):
        for item in data.get(section, []):
            if (
                section == "pending_exit_execution"
                and "龙线不再高于虎线" in str(item.get("exit_reason", ""))
            ):
                continue
            key = _signal_key(
                item.get("code"),
                item.get("setup_cross_date") or item.get("cross_date"),
            )
            if key:
                active_signal_lineages.setdefault(key[0], key[1])
    pending_main = list(data["pending_main"])
    pending_secondary = list(data["pending_secondary"])
    pending_entry = list(data["pending_entry_execution"])
    migrated_pending = (
        pending_main
        + [item for item in pending_secondary if not _uses_current_strategy(item)]
        + [
            item
            for item in pending_entry
            if not _uses_current_strategy(item)
            or str(item.get("area", "main")) != "secondary"
        ]
    )
    if stored_strategy_version != CURRENT_STRATEGY_VERSION:
        migrated_pending = pending_main + pending_secondary + pending_entry
        data["pending_main"] = []
        data["pending_secondary"] = []
        data["pending_entry_execution"] = []
    else:
        # 正式策略只自动执行次选。即使状态头已经升级，也清除残留的
        # 主选候选和旧版本候选；其信号墓碑已在上方预先保存。
        data["pending_main"] = []
        data["pending_secondary"] = [
            item for item in pending_secondary if _uses_current_strategy(item)
        ]
        data["pending_entry_execution"] = [
            item
            for item in pending_entry
            if _uses_current_strategy(item)
            and str(item.get("area", "main")) == "secondary"
        ]
    if migrated_pending or stored_strategy_version != CURRENT_STRATEGY_VERSION:
        reset_pending_count = len(migrated_pending)
        data["strategy_migration"] = {
            "from": stored_strategy_version or LEGACY_STRATEGY_VERSION,
            "to": CURRENT_STRATEGY_VERSION,
            "reset_pending_count": reset_pending_count,
            "note": "旧买点候选不沿用；原信号已保留消费墓碑，新交叉可重新评估",
        }
    data["consumed_signals"] = _serialize_signal_keys(consumed_signals)
    data["active_signal_lineages"] = _serialize_signal_lineages(
        active_signal_lineages
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
    required_history = (
        EXIT_WEAKENING_POINTS + EXIT_WEAKENING_CONFIRMATIONS - 1
    )
    del history[:-required_history]


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
    required_history = (
        EXIT_WEAKENING_POINTS + EXIT_WEAKENING_CONFIRMATIONS - 1
    )
    if len(history) < required_history:
        return False
    latest = history[-required_history:]
    dragons = [float(item["dragon"]) for item in latest]
    spreads = [
        float(item["dragon"]) - float(item["tiger"])
        for item in latest
    ]
    return all(left > right for left, right in zip(dragons, dragons[1:])) and all(
        left > right for left, right in zip(spreads, spreads[1:])
    )


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


def _row_cross_date(row: dict) -> str:
    value = row.get("cross_date")
    if not value and isinstance(row.get("live_seed"), dict):
        value = row["live_seed"].get("cross_date")
    return str(value or "")


def _signal_key(code: object, cross_date: object) -> tuple[str, str] | None:
    normalized_code = str(code or "")
    normalized_date = str(cross_date or "")
    if not normalized_code or not normalized_date:
        return None
    return normalized_code, normalized_date


def _stored_signal_keys(values: object) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not isinstance(values, list):
        return keys
    for item in values:
        if isinstance(item, dict):
            key = _signal_key(item.get("code"), item.get("cross_date"))
        elif isinstance(item, str) and "|" in item:
            code, cross_date = item.split("|", 1)
            key = _signal_key(code, cross_date)
        else:
            key = None
        if key:
            keys.add(key)
    return keys


def _serialize_signal_keys(
    keys: set[tuple[str, str]],
) -> list[dict[str, str]]:
    return [
        {"code": code, "cross_date": cross_date}
        for code, cross_date in sorted(keys)
    ]


def _stored_signal_lineages(values: object) -> dict[str, str]:
    lineages: dict[str, str] = {}
    if not isinstance(values, list):
        return lineages
    for item in values:
        if not isinstance(item, dict):
            continue
        key = _signal_key(
            item.get("code"),
            item.get("original_cross_date") or item.get("cross_date"),
        )
        if key:
            lineages[key[0]] = key[1]
    return lineages


def _serialize_signal_lineages(
    lineages: dict[str, str],
) -> list[dict[str, str]]:
    return [
        {"code": code, "original_cross_date": cross_date}
        for code, cross_date in sorted(lineages.items())
    ]


def _finite_positive(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _row_open_price(row: dict) -> float | None:
    return _finite_positive(row.get("open"))


def _row_is_one_word_limit(row: dict, direction: str) -> bool:
    explicit_key = f"one_word_limit_{direction}"
    if explicit_key in row:
        return bool(row.get(explicit_key))
    limit_price = _finite_positive(row.get(f"limit_{direction}_price"))
    if limit_price is None:
        return False
    prices = [
        _finite_positive(row.get(key))
        for key in ("open", "high", "low", "close")
    ]
    if any(value is None for value in prices):
        return False
    return all(abs(float(value) - limit_price) <= 0.0051 for value in prices)


def _record_execution_wait(order: dict, trade_date: str) -> tuple[bool, int]:
    new_attempt = trade_date > str(order.get("last_execution_attempt_date", ""))
    if new_attempt:
        order["execution_wait_bars"] = int(
            order.get("execution_wait_bars", 0)
        ) + 1
        order["last_execution_attempt_date"] = trade_date
    return new_attempt, int(order.get("execution_wait_bars", 0))


def _mark_position_at_close(
    position: dict,
    row: dict,
    trade_date: str,
    *,
    increment_holding: bool = False,
) -> None:
    position["last_date"] = trade_date
    position["last_close"] = float(row["close"])
    position["return_pct"] = _return_pct(
        float(position["entry_price"]),
        position["last_close"],
    )
    position["best_return_pct"] = max(
        float(position.get("best_return_pct", position["return_pct"])),
        position["return_pct"],
    )
    position["worst_return_pct"] = min(
        float(position.get("worst_return_pct", position["return_pct"])),
        position["return_pct"],
    )
    if increment_holding:
        position["holding_days"] = int(position.get("holding_days", 1)) + 1
    _record_line_point(position, row, trade_date)


def _row_entry_breakout_high(row: dict) -> float | None:
    value = row.get("entry_breakout_high_5")
    if value is None and isinstance(row.get("live_seed"), dict):
        value = row["live_seed"].get("entry_breakout_high_5")
    return _finite_positive(value)


def _row_next_breakout_high(row: dict) -> float | None:
    value = row.get("next_breakout_high_5")
    if value is None and isinstance(row.get("live_seed"), dict):
        value = row["live_seed"].get("next_breakout_high_5")
    return _finite_positive(value)


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
    row: dict | None = None,
) -> str:
    """Return the shared close/intraday trend-ending reason without mutating state."""
    if _uses_current_strategy(position):
        # 正式策略的优先级是不可交换的：真实消失、龙虎终止、
        # 10%/10%移动止盈、三点同步转弱、最长持有期。
        if signal_erased:
            return "趋势结束：原龙腾跃虎信号在有效窗口内被K线重算消失"
        if dragon_above_tiger is False:
            return "趋势结束：龙线不再高于虎线，龙腾跃虎多头关系消失"
        best_return = float(position.get("best_return_pct", 0.0))
        if price is not None:
            entry_price = float(position.get("entry_price", 0.0))
            if entry_price > 0 and float(price) > 0:
                best_return = max(
                    best_return,
                    _return_pct(entry_price, float(price)),
                )
        if best_return >= EXIT_PROFIT_ACTIVATION_PCT:
            peak_drawdown = _peak_drawdown_pct(position, price)
            if (
                peak_drawdown is not None
                and peak_drawdown
                <= -EXIT_TRAILING_DRAWDOWN_PCT + 1e-8
            ):
                return "趋势结束：浮盈达到10%后较最高收盘回撤10%"
        if row is not None and _trend_is_weakening(position, row):
            return "趋势结束：龙线与龙虎差连续三点同步递减"
        elapsed_bars = max(0, int(position.get("holding_days", 1)) - 1)
        if elapsed_bars >= TREND_MAX_HOLDING_BARS:
            return "趋势结束：已完成60个后续交易日跟踪"
        return ""

    # 迁移前持仓继续使用原 3%/2% 退出规则；信号重算只保留风险提示。
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
        return "趋势结束：达到3%浮盈后较最高收盘回撤2%"
    return ""


def trend_pending_reason(
    position: dict,
    row: dict | None = None,
    price: float | None = None,
) -> str:
    reasons: list[str] = []
    current_strategy = _uses_current_strategy(position)
    if not current_strategy and position.get("signal_repainted_after_entry"):
        reasons.append("龙腾跃虎标签曾被后续K线重算消失")
    if (
        not current_strategy
        and row is not None
        and not position.get("signal_repainted_after_entry")
    ):
        setup_elapsed = int(position.get("setup_elapsed_bars_at_entry", 0)) + max(
            0,
            int(position.get("holding_days", 1)) - 1,
        )
        if signal_recalculated_away(position, row, setup_elapsed):
            reasons.append("龙腾跃虎标签被后续K线重算消失")
    if (
        not current_strategy
        and row is not None
        and _trend_is_weakening(position, row)
    ):
        reasons.append("龙虎差与龙线同步转弱")
    best_return = float(position.get("best_return_pct", 0.0))
    if price is not None:
        entry_price = float(position.get("entry_price", 0.0))
        if entry_price > 0 and float(price) > 0:
            best_return = max(best_return, _return_pct(entry_price, float(price)))
    peak_drawdown = _peak_drawdown_pct(position, price)
    activation_pct = (
        EXIT_PROFIT_ACTIVATION_PCT
        if current_strategy
        else TREND_PROFIT_ACTIVATION_PCT
    )
    trailing_pct = (
        EXIT_TRAILING_DRAWDOWN_PCT
        if current_strategy
        else TREND_TRAILING_DRAWDOWN_PCT
    )
    warning_drawdown = trailing_pct * TREND_PENDING_DRAWDOWN_RATIO
    if (
        best_return >= activation_pct
        and peak_drawdown is not None
        and peak_drawdown <= -warning_drawdown + 1e-8
    ):
        reasons.append("已接近回撤止盈线")
    return "；".join(dict.fromkeys(reasons))


def _update_repaint_risk(position: dict, row: dict, trade_date: str) -> None:
    setup_elapsed = int(position.get("setup_elapsed_bars_at_entry", 0)) + max(
        0,
        int(position.get("holding_days", 1)) - 1,
    )
    if signal_recalculated_away(position, row, setup_elapsed):
        position["signal_repainted_after_entry"] = True
        position.setdefault("signal_repainted_date", trade_date)
    elif position.get("signal_repainted_after_entry") and row.get("cross_ok"):
        position["signal_repainted_after_entry"] = False
        position["signal_repainted_restored_date"] = trade_date


def _take_profit_exit_reason(position: dict, row: dict) -> str:
    setup_elapsed = int(position.get("setup_elapsed_bars_at_entry", 0)) + max(
        0,
        int(position.get("holding_days", 1)) - 1,
    )
    signal_erased = signal_recalculated_away(position, row, setup_elapsed)
    reason = trend_exit_reason(
        position,
        price=float(position.get("last_close", row.get("close", 0.0))),
        dragon_above_tiger=_dragon_above_tiger(row),
        signal_erased=signal_erased,
        row=row,
    )
    peak_drawdown = _peak_drawdown_pct(position)
    if peak_drawdown is not None:
        position["peak_drawdown_pct"] = peak_drawdown
    return reason


def _new_pending_setup(row: dict, trade_date: str, area: str) -> dict:
    price = float(row["close"])
    cross_age = _row_cross_age(row)
    cross_date = _row_cross_date(row)
    setup = {
        "setup_id": f"{area}_{row['code']}_{cross_date or trade_date}",
        "code": str(row["code"]),
        "name": str(row["name"]),
        "market": int(row["market"]),
        "area": area,
        "origin_area": area,
        "setup_date": trade_date,
        "setup_price": price,
        "last_date": trade_date,
        "last_close": price,
        "setup_cross_date": cross_date,
        "setup_cross_age": cross_age,
        "setup_cross_lookback_days": _row_cross_lookback(row),
        "setup_elapsed_bars": 0,
        "status": "待观察中",
        "operation": "等待D+2收盘确认",
        "status_detail": (
            "次选信号已形成；等待第二个完整交易日收盘确认信号、"
            "龙虎关系、龙线与最大3%回撤"
        ),
        "strategy_version": CURRENT_STRATEGY_VERSION,
        "confirmation_d1_dragon": None,
        "line_history": [],
        "selected_dates": [trade_date],
    }
    _record_line_point(setup, row, trade_date)
    return setup


def _new_pending_entry_execution(
    setup: dict,
    row: dict,
    trade_date: str,
    area: str,
) -> dict:
    order = deepcopy(setup)
    order.update(
        {
            "execution_id": f"entry_{row['code']}_{trade_date}",
            "name": str(row.get("name", setup.get("name", ""))),
            "market": int(row.get("market", setup.get("market", 0))),
            "area": area,
            "entry_trigger_date": trade_date,
            "entry_trigger_close": float(row["close"]),
            "entry_confirmation_dragon": float(row["dragon_value"]),
            "execution_wait_bars": 0,
            "last_execution_attempt_date": "",
            "execution_blocked_reason": "",
            "status": "买点已确认",
            "operation": "下一交易日开盘买入",
            "status_detail": (
                "D+2收盘已确认买点；下一可交易日按开盘价模拟执行"
            ),
        }
    )
    return order


def _confirmed_position(setup: dict, row: dict, trade_date: str) -> dict:
    entry_price = _row_open_price(row)
    if entry_price is None:
        raise ValueError("开盘价缺失，不能确认模拟买入")
    close_price = float(row["close"])
    close_return = _return_pct(entry_price, close_price)
    position = {
        "position_id": f"{row['code']}_{trade_date}",
        "code": str(row["code"]),
        "name": str(row["name"]),
        "market": int(row["market"]),
        "entry_date": trade_date,
        "entry_price": entry_price,
        "entry_trigger_date": str(setup.get("entry_trigger_date", "")),
        "entry_trigger_close": float(setup.get("entry_trigger_close", 0.0)),
        "last_date": trade_date,
        "last_close": close_price,
        "return_pct": close_return,
        "best_return_pct": max(0.0, close_return),
        "worst_return_pct": min(0.0, close_return),
        "holding_days": 1,
        "missing_streak": 0,
        "signal_lost_date": "",
        "status": "趋势开始",
        "operation": "开盘已执行买入",
        "status_detail": "前一交易日收盘确认买点，今日按开盘价模拟买入",
        "strategy_version": str(
            setup.get("strategy_version", CURRENT_STRATEGY_VERSION)
        ),
        "line_history": deepcopy(setup.get("line_history", [])),
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
        )
        + int(setup.get("execution_wait_bars", 0))
        + 1,
        "entry_rule": (
            "D+2收盘确认：信号真实有效、龙线高于虎线、收盘不低于龙线、"
            "龙线不低于D+1且较信号日收盘回撤不超过3%；下一可交易日开盘执行"
        ),
        "entry_confirmation_dragon": _finite_positive(
            setup.get("entry_confirmation_dragon")
        ),
        "origin_area": str(
            setup.get("origin_area", setup.get("area", "secondary"))
        ),
    }
    if trade_date not in position["selected_dates"]:
        position["selected_dates"].append(trade_date)
    _record_line_point(position, row, trade_date)
    return position


def _new_pending_exit_execution(
    position: dict,
    row: dict,
    trade_date: str,
    reason: str,
    area: str,
) -> dict:
    order = deepcopy(position)
    order.update(
        {
            "execution_id": f"exit_{position['code']}_{trade_date}",
            "name": str(row.get("name", position.get("name", ""))),
            "market": int(row.get("market", position.get("market", 0))),
            "area": area,
            "exit_trigger_date": trade_date,
            "exit_trigger_close": float(row["close"]),
            "exit_trigger_return_pct": float(position.get("return_pct", 0.0)),
            "exit_reason": reason,
            "execution_wait_bars": 0,
            "last_execution_attempt_date": "",
            "execution_blocked_reason": "",
            "status": "卖点已确认",
            "operation": "下一交易日开盘卖出",
            "status_detail": "收盘已确认卖点；下一交易日按开盘价模拟执行",
        }
    )
    return order


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
            setup["operation"] = "暂停操作"
            remaining.append(setup)
            continue
        setup["last_date"] = trade_date
        setup["last_close"] = float(row["close"])
        if is_new_day and trade_date > str(setup["setup_date"]):
            setup["setup_elapsed_bars"] = int(
                setup.get("setup_elapsed_bars", 0)
            ) + 1
        elapsed = int(setup.get("setup_elapsed_bars", 0))
        _record_line_point(setup, row, trade_date)
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
        if elapsed > ENTRY_DELAY_BARS:
            events.append(
                {
                    "type": "setup_cancelled",
                    "code": setup["code"],
                    "name": setup["name"],
                    "area": area,
                    "reason": "已错过D+2收盘确认窗口",
                }
            )
            continue
        if elapsed == 1:
            dragon = _finite_positive(row.get("dragon_value"))
            setup["confirmation_d1_dragon"] = dragon
            setup["status"] = "待观察中"
            setup["operation"] = "等待D+2收盘确认"
            setup["status_detail"] = (
                "D+1信号与龙虎关系仍有效；等待下一完整交易日收盘确认"
            )
            remaining.append(setup)
            continue
        if elapsed == ENTRY_DELAY_BARS:
            close_price = _finite_positive(row.get("close"))
            dragon = _finite_positive(row.get("dragon_value"))
            d1_dragon = _finite_positive(setup.get("confirmation_d1_dragon"))
            setup_price = _finite_positive(setup.get("setup_price"))
            failure_reason = ""
            if close_price is None or dragon is None or d1_dragon is None:
                failure_reason = "D+2确认所需的收盘价或龙线数据缺失"
            elif close_price + 1e-8 < dragon:
                failure_reason = "D+2收盘价低于龙线"
            elif dragon + 1e-8 < d1_dragon:
                failure_reason = "D+2龙线低于D+1龙线"
            elif (
                setup_price is None
                or close_price + 1e-8
                < setup_price * (1.0 - ENTRY_MAX_PULLBACK_PCT / 100.0)
            ):
                failure_reason = "D+2收盘较信号日收盘回撤超过3%"
            if failure_reason:
                events.append(
                    {
                        "type": "setup_cancelled",
                        "code": setup["code"],
                        "name": setup["name"],
                        "area": area,
                        "reason": failure_reason,
                    }
                )
                continue
            order = _new_pending_entry_execution(
                setup,
                row,
                trade_date,
                area,
            )
            confirmed.append(order)
            events.append(
                {
                    "type": "entry_triggered",
                    "code": setup["code"],
                    "name": setup["name"],
                    "area": area,
                    "trigger_close": close_price,
                    "confirmation_dragon": dragon,
                    "reason": "D+2收盘满足低风险确认条件",
                }
            )
            continue
        setup["status"] = "待观察中"
        setup["operation"] = "等待D+2收盘确认"
        setup["status_detail"] = "等待D+1与D+2两个完整交易日完成确认"
        if row.get("selected"):
            dates = setup.setdefault("selected_dates", [])
            if trade_date not in dates:
                dates.append(trade_date)
        remaining.append(setup)
    return remaining, confirmed, events


def _advance_pending_entry_executions(
    pending: Sequence[dict],
    row_by_code: dict[str, dict],
    trade_date: str,
    is_new_day: bool,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    remaining: list[dict] = []
    main_positions: list[dict] = []
    secondary_positions: list[dict] = []
    events: list[dict] = []
    for order in pending:
        trigger_date = str(order.get("entry_trigger_date", ""))
        if not is_new_day or not trigger_date or trade_date <= trigger_date:
            remaining.append(order)
            continue
        row = row_by_code.get(str(order["code"]))
        if row is None:
            _, wait_bars = _record_execution_wait(order, trade_date)
            if wait_bars >= ENTRY_EXECUTION_MAX_WAIT_BARS:
                events.append(
                    {
                        "type": "entry_cancelled",
                        "code": order["code"],
                        "name": order["name"],
                        "area": order.get("area", "main"),
                        "reason": (
                            f"连续{ENTRY_EXECUTION_MAX_WAIT_BARS}个交易日"
                            "停牌或行情缺失，无法按开盘价买入"
                        ),
                    }
                )
                continue
            order["status"] = "数据待确认"
            order["operation"] = "暂停执行买入"
            order["execution_blocked_reason"] = "停牌或行情缺失"
            order["status_detail"] = (
                f"第{wait_bars}个交易日行情缺失；未使用替代价格成交，继续等待"
            )
            remaining.append(order)
            continue
        if not _eligible(row):
            events.append(
                {
                    "type": "entry_cancelled",
                    "code": order["code"],
                    "name": order["name"],
                    "area": order.get("area", "main"),
                    "reason": "股票名称含 ST，取消待执行买入",
                }
            )
            continue
        _record_line_point(order, row, trade_date)
        open_price = _row_open_price(row)
        if open_price is None:
            new_attempt, wait_bars = _record_execution_wait(order, trade_date)
            invalid_reason = ""
            if not _dragon_above_tiger(row):
                invalid_reason = "等待成交期间龙线不再高于虎线"
            else:
                if signal_recalculated_away(
                    order,
                    row,
                    int(order.get("setup_elapsed_bars", 0)) + wait_bars,
                ):
                    invalid_reason = "原龙腾跃虎信号被K线重算消失"
            if not invalid_reason and wait_bars >= ENTRY_EXECUTION_MAX_WAIT_BARS:
                invalid_reason = (
                    f"连续{ENTRY_EXECUTION_MAX_WAIT_BARS}个交易日"
                    "停牌或开盘价缺失，无法买入"
                )
            if invalid_reason:
                events.append(
                    {
                        "type": "entry_cancelled",
                        "code": order["code"],
                        "name": order["name"],
                        "area": order.get("area", "main"),
                        "reason": invalid_reason,
                    }
                )
                continue
            order["status"] = "数据待确认"
            order["operation"] = "暂停执行买入"
            order["execution_blocked_reason"] = "停牌或开盘价缺失"
            order["status_detail"] = (
                f"第{wait_bars}个交易日开盘价缺失；未使用收盘价代替成交，继续等待"
            )
            if new_attempt:
                events.append(
                    {
                        "type": "entry_execution_blocked",
                        "code": order["code"],
                        "name": order["name"],
                        "area": order.get("area", "main"),
                        "reason": order["execution_blocked_reason"],
                    }
                )
            remaining.append(order)
            continue
        if _row_is_one_word_limit(row, "up"):
            new_attempt, wait_bars = _record_execution_wait(order, trade_date)
            invalid_reason = ""
            if not _dragon_above_tiger(row):
                invalid_reason = "等待成交期间龙线不再高于虎线"
            else:
                if signal_recalculated_away(
                    order,
                    row,
                    int(order.get("setup_elapsed_bars", 0)) + wait_bars,
                ):
                    invalid_reason = "原龙腾跃虎信号被K线重算消失"
            if not invalid_reason and wait_bars >= ENTRY_EXECUTION_MAX_WAIT_BARS:
                invalid_reason = (
                    f"连续{ENTRY_EXECUTION_MAX_WAIT_BARS}个交易日一字涨停无法买入"
                )
            if invalid_reason:
                events.append(
                    {
                        "type": "entry_cancelled",
                        "code": order["code"],
                        "name": order["name"],
                        "area": order.get("area", "main"),
                        "reason": invalid_reason,
                    }
                )
                continue
            order["execution_blocked_reason"] = "一字涨停，开盘无法买入"
            order["status"] = "买点已确认"
            order["operation"] = "等待可成交开盘"
            order["status_detail"] = (
                f"第{wait_bars}个交易日一字涨停未成交；信号仍有效，继续等待"
            )
            if new_attempt:
                events.append(
                    {
                        "type": "entry_execution_blocked",
                        "code": order["code"],
                        "name": order["name"],
                        "area": order.get("area", "main"),
                        "reason": order["execution_blocked_reason"],
                    }
                )
            remaining.append(order)
            continue

        position = _confirmed_position(order, row, trade_date)
        area = str(order.get("area", "main"))
        if area == "secondary":
            secondary_positions.append(position)
        else:
            main_positions.append(position)
        events.append(
            {
                "type": "entry_executed",
                "code": order["code"],
                "name": order["name"],
                "area": area,
                "trigger_date": trigger_date,
                "entry_date": trade_date,
                "entry_price": open_price,
            }
        )
    return remaining, main_positions, secondary_positions, events


def _advance_pending_exit_executions(
    pending: Sequence[dict],
    row_by_code: dict[str, dict],
    trade_date: str,
    is_new_day: bool,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    remaining: list[dict] = []
    main_closed: list[dict] = []
    secondary_closed: list[dict] = []
    events: list[dict] = []
    for order in pending:
        trigger_date = str(order.get("exit_trigger_date", ""))
        if not is_new_day or not trigger_date or trade_date <= trigger_date:
            remaining.append(order)
            continue
        row = row_by_code.get(str(order["code"]))
        if row is None:
            order["status"] = "数据待确认"
            order["operation"] = "暂停执行卖出"
            order["status_detail"] = "下一交易日行情缺失，未使用替代价格成交"
            remaining.append(order)
            continue
        open_price = _row_open_price(row)
        if open_price is None:
            order["status"] = "数据待确认"
            order["operation"] = "暂停执行卖出"
            order["status_detail"] = "开盘价缺失，未使用收盘价代替成交"
            remaining.append(order)
            continue
        if _row_is_one_word_limit(row, "down"):
            new_attempt = trade_date > str(
                order.get("last_execution_attempt_date", "")
            )
            if new_attempt:
                order["execution_wait_bars"] = int(
                    order.get("execution_wait_bars", 0)
                ) + 1
                order["last_execution_attempt_date"] = trade_date
            _mark_position_at_close(
                order,
                row,
                trade_date,
                increment_holding=(trade_date > str(order.get("last_date", ""))),
            )
            order["execution_blocked_reason"] = "一字跌停，开盘无法卖出"
            order["status"] = "卖点已确认"
            order["operation"] = "等待可成交开盘"
            order["status_detail"] = (
                f"卖点已确认；第{int(order.get('execution_wait_bars', 0))}个交易日"
                "一字跌停未成交，继续等待首次可成交开盘"
            )
            if new_attempt:
                events.append(
                    {
                        "type": "exit_execution_blocked",
                        "code": order["code"],
                        "name": order["name"],
                        "area": order.get("area", "main"),
                        "reason": order["execution_blocked_reason"],
                    }
                )
            remaining.append(order)
            continue

        closed = deepcopy(order)
        if trade_date > str(closed.get("last_date", "")):
            closed["holding_days"] = int(closed.get("holding_days", 1)) + 1
        closed["last_date"] = trade_date
        closed["last_close"] = open_price
        closed["return_pct"] = _return_pct(
            float(closed["entry_price"]),
            open_price,
        )
        closed["best_return_pct"] = max(
            float(closed.get("best_return_pct", closed["return_pct"])),
            closed["return_pct"],
        )
        closed["worst_return_pct"] = min(
            float(closed.get("worst_return_pct", closed["return_pct"])),
            closed["return_pct"],
        )
        closed["exit_date"] = trade_date
        closed["exit_price"] = open_price
        closed["exit_return_pct"] = closed["return_pct"]
        closed["status"] = "趋势结束"
        closed["operation"] = "开盘已执行卖出"
        closed["status_detail"] = "前一交易日收盘确认卖点，今日按开盘价模拟卖出"
        area = str(closed.get("area", "main"))
        if area == "secondary":
            secondary_closed.append(closed)
            event_type = "secondary_removed"
        else:
            main_closed.append(closed)
            event_type = "removed"
        events.append(
            {
                "type": event_type,
                "execution": "next_open",
                "code": closed["code"],
                "name": closed["name"],
                "trigger_date": trigger_date,
                "exit_date": trade_date,
                "exit_price": open_price,
                "return_pct": closed["return_pct"],
            }
        )
    return remaining, main_closed, secondary_closed, events


def update_state(state: dict, rows: Sequence[dict], trade_date: str) -> tuple[dict, list[dict]]:
    """处理一个交易日；同一日期重复运行不会重复累计消失天数。"""
    state = deepcopy(state)
    for section in (
        "active",
        "closed",
        "secondary_active",
        "secondary_closed",
        "pending_main",
        "pending_secondary",
        "pending_entry_execution",
        "pending_exit_execution",
    ):
        state.setdefault(section, [])
    state.setdefault("last_trade_date", "")
    state["strategy_version"] = CURRENT_STRATEGY_VERSION
    row_by_code = {str(row["code"]): row for row in rows}
    is_new_day = not state["last_trade_date"] or trade_date > state["last_trade_date"]
    events: list[dict] = []
    exited_codes: set[str] = set()
    setup_cancelled_codes: set[str] = set()
    consumed_signals = _stored_signal_keys(
        state.get("consumed_signals", [])
    )
    consumed_signals.update({
        key
        for section in (
            "active",
            "closed",
            "secondary_active",
            "secondary_closed",
            "pending_main",
            "pending_secondary",
            "pending_entry_execution",
            "pending_exit_execution",
        )
        for item in state.get(section, [])
        if (
            key := _signal_key(
                item.get("code"),
                item.get("setup_cross_date") or item.get("cross_date"),
            )
        )
    })
    active_signal_lineages = _stored_signal_lineages(
        state.get("active_signal_lineages", [])
    )
    for section in (
        "active",
        "secondary_active",
        "pending_main",
        "pending_secondary",
        "pending_entry_execution",
        "pending_exit_execution",
    ):
        for item in state.get(section, []):
            if (
                section == "pending_exit_execution"
                and "龙线不再高于虎线" in str(item.get("exit_reason", ""))
            ):
                continue
            key = _signal_key(
                item.get("code"),
                item.get("setup_cross_date") or item.get("cross_date"),
            )
            if key:
                active_signal_lineages.setdefault(key[0], key[1])
    for code, row in row_by_code.items():
        if not _dragon_above_tiger(row):
            active_signal_lineages.pop(code, None)
            continue
        row_key = _signal_key(code, _row_cross_date(row))
        if row_key and row_key in consumed_signals:
            active_signal_lineages.setdefault(code, row_key[1])
    # update_state 也可能被测试或重放直接调用，不能假定调用方先经过
    # load_state；因此在任何成交处理前执行同一迁移保护。
    state["pending_main"] = []
    state["pending_secondary"] = [
        item
        for item in state.get("pending_secondary", [])
        if _uses_current_strategy(item)
    ]
    state["pending_entry_execution"] = [
        item
        for item in state.get("pending_entry_execution", [])
        if _uses_current_strategy(item)
        and str(item.get("area", "main")) == "secondary"
    ]

    (
        state["pending_exit_execution"],
        executed_main_closed,
        executed_secondary_closed,
        execution_events,
    ) = _advance_pending_exit_executions(
        state.get("pending_exit_execution", []),
        row_by_code,
        trade_date,
        is_new_day,
    )
    state["closed"].extend(executed_main_closed)
    state["secondary_closed"].extend(executed_secondary_closed)
    events.extend(execution_events)

    (
        state["pending_entry_execution"],
        executed_main_positions,
        executed_secondary_positions,
        execution_events,
    ) = _advance_pending_entry_executions(
        state.get("pending_entry_execution", []),
        row_by_code,
        trade_date,
        is_new_day,
    )
    state["active"].extend(executed_main_positions)
    state["secondary_active"].extend(executed_secondary_positions)
    events.extend(execution_events)
    still_active: list[dict] = []

    for position in state["active"]:
        row = row_by_code.get(position["code"])
        if row is None:
            position["status"] = "数据待确认"
            position["operation"] = "暂停操作"
            still_active.append(position)
            continue

        if signal_key := _signal_key(
            position["code"],
            position.get("setup_cross_date"),
        ):
            consumed_signals.add(signal_key)

        position["last_date"] = trade_date
        if not position.get("setup_cross_date") and _row_cross_date(row):
            position["setup_cross_date"] = _row_cross_date(row)
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
            exit_reason = "股票名称含 ST，不符合入选范围"
            state["pending_exit_execution"].append(
                _new_pending_exit_execution(
                    position,
                    row,
                    trade_date,
                    exit_reason,
                    "main",
                )
            )
            exited_codes.add(str(position["code"]))
            events.append(
                {
                    "type": "exit_triggered",
                    "code": position["code"],
                    "name": str(row.get("name", position["name"])),
                    "area": "main",
                    "reason": exit_reason,
                }
            )
            continue

        should_check_exit = is_later_day or _uses_current_strategy(position)
        if should_check_exit:
            if not _uses_current_strategy(position):
                _update_repaint_risk(position, row, trade_date)
            exit_reason = _take_profit_exit_reason(position, row)
            if exit_reason:
                state["pending_exit_execution"].append(
                    _new_pending_exit_execution(
                        position,
                        row,
                        trade_date,
                        exit_reason,
                        "main",
                    )
                )
                exited_codes.add(str(position["code"]))
                events.append(
                    {
                        "type": "exit_triggered",
                        "code": position["code"],
                        "name": position["name"],
                        "area": "main",
                        "reason": exit_reason,
                        "trigger_return_pct": position["return_pct"],
                    }
                )
                continue
            pending_reason = trend_pending_reason(position, row)
            if pending_reason:
                if not position.get("missing_streak", 0):
                    events.append({"type": "trend_warning", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 1
                position["signal_lost_date"] = trade_date
                position["status"] = "待观察中"
                position["operation"] = "谨慎持有"
                position["status_detail"] = pending_reason
            else:
                if position.get("missing_streak", 0):
                    events.append({"type": "signal_restored", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 0
                position["signal_lost_date"] = ""
                position["status"] = "上升趋势中"
                position["operation"] = "继续持有"
                position["status_detail"] = "趋势条件仍有效"
        elif not position.get("status"):
            position["status"] = "趋势开始"
            position["operation"] = "建议买入"
        still_active.append(position)

    state["active"] = still_active
    # 主选是观察层：首次看到的信号只写消费墓碑，不创建候选、订单或持仓。
    # 同一 (code, original cross_date) 此后即使落入次选也不会自动交易。
    state["pending_main"] = []
    active_lineage_codes = set(active_signal_lineages) | {
        str(item.get("code", ""))
        for section in (
            "active",
            "secondary_active",
            "pending_secondary",
            "pending_entry_execution",
        )
        for item in state.get(section, [])
        if item.get("code")
    }
    for row in rows:
        if (
            not _eligible(row)
            or not row.get("selected")
            or not row.get("cross_ok")
            or not _dragon_above_tiger(row)
        ):
            continue
        code = str(row["code"])
        # 活跃候选或持仓的 cross_date 可能因尾部重算漂移；只要信号和
        # 龙虎关系仍活跃，就沿用原 setup 身份，不能另写一个新墓碑。
        if code in active_lineage_codes:
            continue
        signal_key = _signal_key(code, _row_cross_date(row))
        if not signal_key or signal_key in consumed_signals:
            continue
        consumed_signals.add(signal_key)
        active_signal_lineages[code] = signal_key[1]
        events.append(
            {
                "type": "main_signal_observed",
                "code": code,
                "name": str(row.get("name", "")),
                "area": "main",
                "reason": "主选信号仅观察，不进入自动交易",
            }
        )

    active_by_code = {position["code"]: position for position in state["active"]}
    secondary_still_active: list[dict] = []
    for position in state["secondary_active"]:
        row = row_by_code.get(position["code"])
        if row is None:
            position["status"] = "数据待确认"
            position["operation"] = "暂停操作"
            secondary_still_active.append(position)
            continue

        if signal_key := _signal_key(
            position["code"],
            position.get("setup_cross_date"),
        ):
            consumed_signals.add(signal_key)

        position["last_date"] = trade_date
        if not position.get("setup_cross_date") and _row_cross_date(row):
            position["setup_cross_date"] = _row_cross_date(row)
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
            exit_reason = "股票名称含 ST，不符合入选范围"
            state["pending_exit_execution"].append(
                _new_pending_exit_execution(
                    position,
                    row,
                    trade_date,
                    exit_reason,
                    "secondary",
                )
            )
            exited_codes.add(str(position["code"]))
            events.append(
                {
                    "type": "exit_triggered",
                    "code": position["code"],
                    "name": str(row.get("name", position["name"])),
                    "area": "secondary",
                    "reason": exit_reason,
                }
            )
            continue

        should_check_exit = is_later_day or _uses_current_strategy(position)
        if should_check_exit:
            if not _uses_current_strategy(position):
                _update_repaint_risk(position, row, trade_date)
            exit_reason = _take_profit_exit_reason(position, row)
            event_type = ""
            if exit_reason:
                event_type = "secondary_removed"
            elif row.get("selected") and not _uses_current_strategy(position):
                event_type = "secondary_promoted"
                position["status"] = "上升趋势中"
                position["operation"] = "继续持有"
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
                state["pending_exit_execution"].append(
                    _new_pending_exit_execution(
                        position,
                        row,
                        trade_date,
                        exit_reason,
                        "secondary",
                    )
                )
                exited_codes.add(str(position["code"]))
                events.append({
                    "type": "exit_triggered",
                    "code": position["code"],
                    "name": position["name"],
                    "area": "secondary",
                    "reason": exit_reason,
                    "trigger_return_pct": position["return_pct"],
                })
                continue
            position["current_area"] = (
                "main" if row.get("selected") else "secondary"
            )
            pending_reason = trend_pending_reason(position, row)
            if pending_reason:
                if not position.get("missing_streak", 0):
                    events.append({"type": "trend_warning", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 1
                position["signal_lost_date"] = trade_date
                position["status"] = "待观察中"
                position["operation"] = "谨慎持有"
                position["status_detail"] = pending_reason
            else:
                if position.get("missing_streak", 0):
                    events.append({"type": "signal_restored", "code": position["code"], "name": position["name"]})
                position["missing_streak"] = 0
                position["signal_lost_date"] = ""
                position["status"] = "上升趋势中"
                position["operation"] = "继续持有"
                position["status_detail"] = "趋势条件仍有效"
        elif row.get("selected") and not _uses_current_strategy(position):
            position["status"] = "趋势开始"
            position["operation"] = "开盘已执行买入"
            position["origin_area"] = position.get("origin_area", "secondary")
            dates = position.setdefault("selected_dates", [])
            if trade_date not in dates:
                dates.append(trade_date)
            state["active"].append(position)
            active_by_code[position["code"]] = position
            events.append(
                {
                    "type": "secondary_promoted",
                    "code": position["code"],
                    "name": position["name"],
                    "return_pct": position["return_pct"],
                }
            )
            continue
        else:
            position["current_area"] = (
                "main" if row.get("selected") else "secondary"
            )
        if not position.get("status"):
            position["status"] = "趋势开始"
            position["operation"] = "开盘已执行买入"
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
    state["pending_entry_execution"].extend(confirmed_secondary)
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
    execution_codes = {
        str(item["code"])
        for item in (
            list(state.get("pending_entry_execution", []))
            + list(state.get("pending_exit_execution", []))
        )
    }
    primary_codes = {
        position["code"] for position in state["active"]
    } | {
        str(setup["code"]) for setup in state.get("pending_main", [])
    } | execution_codes
    for row in rows:
        if not _secondary_selected(row):
            continue
        code = str(row["code"])
        signal_key = _signal_key(code, _row_cross_date(row))
        if code in active_signal_lineages:
            continue
        if signal_key and signal_key in consumed_signals:
            continue
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
        if signal_key:
            consumed_signals.add(signal_key)
            active_signal_lineages[code] = signal_key[1]
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
    state["pending_entry_execution"].sort(
        key=lambda x: (x.get("entry_trigger_date", ""), x["code"])
    )
    state["pending_exit_execution"].sort(
        key=lambda x: (x.get("exit_trigger_date", ""), x["code"])
    )
    state["consumed_signals"] = _serialize_signal_keys(consumed_signals)
    state["active_signal_lineages"] = _serialize_signal_lineages(
        active_signal_lineages
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
    main_exit_pending = [
        x
        for x in state.get("pending_exit_execution", [])
        if str(x.get("area", "main")) == "main"
    ]
    tracked_active = list(state.get("active", [])) + main_exit_pending
    current_active = [
        x
        for x in tracked_active
        if str(x.get("strategy_version", LEGACY_STRATEGY_VERSION))
        == CURRENT_STRATEGY_VERSION
    ]
    active_returns = [
        float(x.get("return_pct", 0.0)) for x in current_active
    ]
    current_closed = [
        x
        for x in state["closed"]
        if str(x.get("strategy_version", LEGACY_STRATEGY_VERSION))
        == CURRENT_STRATEGY_VERSION
    ]
    closed_returns = [
        float(x.get("exit_return_pct", 0.0)) for x in current_closed
    ]
    realized_factor = math.prod(1.0 + value / 100.0 for value in closed_returns)
    return {
        "active_count": len(active_returns),
        "tracked_active_count": len(tracked_active),
        "legacy_active_count": len(tracked_active) - len(current_active),
        "pending_entry_execution_count": sum(
            str(x.get("area", "main")) == "main"
            for x in state.get("pending_entry_execution", [])
        ),
        "pending_exit_execution_count": len(main_exit_pending),
        "closed_count": len(closed_returns),
        "legacy_closed_count": len(state["closed"]) - len(current_closed),
        "warning_count": sum(
            int(x.get("missing_streak", 0)) == 1 for x in current_active
        ),
        "current_success_rate": (sum(value > 0 for value in closed_returns) / len(closed_returns) * 100.0) if closed_returns else None,
        "closed_success_rate": (sum(value > 0 for value in closed_returns) / len(closed_returns) * 100.0) if closed_returns else None,
        "active_average_return": sum(active_returns) / len(active_returns) if active_returns else None,
        "all_average_return": sum(closed_returns) / len(closed_returns) if closed_returns else None,
        "realized_compound_return": (realized_factor - 1.0) * 100.0 if closed_returns else None,
        "best_return": max(closed_returns) if closed_returns else None,
        "worst_return": min(closed_returns) if closed_returns else None,
        "sample_count": len(closed_returns),
        "success_definition": "当前正式策略中，卖出触发后下一交易日开盘成交价高于买入触发后下一交易日开盘成交价；未结束和旧规则样本不计入",
        "strategy_version": CURRENT_STRATEGY_VERSION,
    }


def secondary_strategy_stats(state: dict) -> dict:
    secondary_exit_pending = [
        x
        for x in state.get("pending_exit_execution", [])
        if str(x.get("area", "main")) == "secondary"
    ]
    tracked_active = list(state.get("secondary_active", [])) + secondary_exit_pending
    current_active = [
        x
        for x in tracked_active
        if str(x.get("strategy_version", LEGACY_STRATEGY_VERSION))
        == CURRENT_STRATEGY_VERSION
    ]
    active_returns = [
        float(x.get("return_pct", 0.0)) for x in current_active
    ]
    current_closed = [
        x
        for x in state.get("secondary_closed", [])
        if str(x.get("strategy_version", LEGACY_STRATEGY_VERSION))
        == CURRENT_STRATEGY_VERSION
    ]
    closed_returns = [
        float(x.get("exit_return_pct", 0.0)) for x in current_closed
    ]
    realized_factor = math.prod(1.0 + value / 100.0 for value in closed_returns)
    return {
        "active_count": len(active_returns),
        "tracked_active_count": len(tracked_active),
        "legacy_active_count": (
            len(tracked_active) - len(current_active)
        ),
        "pending_entry_execution_count": sum(
            str(x.get("area", "main")) == "secondary"
            for x in state.get("pending_entry_execution", [])
        ),
        "pending_exit_execution_count": len(secondary_exit_pending),
        "closed_count": len(closed_returns),
        "legacy_closed_count": len(state.get("secondary_closed", [])) - len(current_closed),
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
        "success_definition": "当前正式策略中，卖出触发后下一交易日开盘成交价高于买入触发后下一交易日开盘成交价；未结束和旧规则样本不计入",
        "strategy_version": CURRENT_STRATEGY_VERSION,
    }
