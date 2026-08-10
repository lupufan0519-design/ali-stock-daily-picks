from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Sequence
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from observation import OBSERVATION_LIMIT, visible_observations
from selection_history import (
    load_history,
    record_intraday_pools,
    refresh_history,
    write_history,
)
from screener import cross_yellow_pair
from simple_strategy import FIRST_TIER, SECOND_TIER, THIRD_TIER, decorate_row, split_tiers
from strategy_contract import (
    ENTRY_DELAY_BARS,
    ENTRY_EXECUTION_MAX_WAIT_BARS,
    ENTRY_MAX_PULLBACK_PCT,
)
from strategy_tracker import (
    signal_recalculated_away,
    trend_exit_reason,
    trend_pending_reason,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_RESULT = ROOT / "results" / "latest.json"
DEFAULT_OUTPUT = ROOT / "results" / "live.json"
HISTORY_PATH = ROOT / "results" / "history.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def is_st_name(name: object) -> bool:
    return "ST" in str(name).upper()


def _live_limit_rate(code: object, market: object, name: object) -> Decimal:
    if is_st_name(name):
        return Decimal("0.05")
    if int(market or 0) == 2:
        return Decimal("0.30")
    if str(code).startswith(("30", "68")):
        return Decimal("0.20")
    return Decimal("0.10")


def _quote_is_locked_limit(
    quote: dict,
    code: object,
    market: object,
    name: object,
    direction: str,
) -> bool:
    previous_close = float(quote.get("pre_close", 0.0) or 0.0)
    if previous_close <= 0:
        return False
    rate = _live_limit_rate(code, market, name)
    factor = Decimal("1") + rate if direction == "up" else Decimal("1") - rate
    limit_price = float(
        (Decimal(str(previous_close)) * factor).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )
    prices = [
        float(quote.get(key, 0.0) or 0.0)
        for key in ("open", "high", "low", "price")
    ]
    return min(prices) > 0 and all(
        abs(value - limit_price) <= 0.0051 for value in prices
    )


def unpack_live_seed(item: object, seed_format: int = 0) -> dict:
    """Decode the compact close-generated seed used by the intraday workflow."""
    if isinstance(item, dict):
        return item
    if seed_format not in {1, 2, 3, 4, 5, 6, 7} or not isinstance(item, list) or len(item) < 19:
        return {}

    def triples(values: object) -> list[list[float]]:
        if not isinstance(values, list) or len(values) % 3:
            return []
        return [
            [float(value) for value in values[index : index + 3]]
            for index in range(0, len(values), 3)
        ]

    dragon_tail = triples(item[8])
    tiger_tail = triples(item[9])
    yellow_tail = (
        triples(item[25])
        if seed_format >= 5 and len(item) > 25
        else []
    )
    if len(dragon_tail) < 2 or len(tiger_tail) < 2:
        return {}
    flags = int(item[18])
    return {
        "code": str(item[0]),
        "name": str(item[1]),
        "market": int(item[2]),
        "base_date": str(item[3]),
        "previous_close": float(item[4]),
        "min_close_15": float(item[5]),
        "next_limit_price": float(item[6]),
        "typical_13": [float(value) for value in item[7]],
        "line_coefficients": {
            "dragon_tail": dragon_tail,
            "tiger_tail": tiger_tail,
            "dragon": dragon_tail[-1],
            "tiger": tiger_tail[-1],
            "previous_dragon": dragon_tail[-2],
            "previous_tiger": tiger_tail[-2],
            "yellow_tail": yellow_tail,
            "yellow": yellow_tail[-1] if yellow_tail else [],
            "previous_yellow": yellow_tail[-2] if len(yellow_tail) >= 2 else [],
        },
        "cross_tail_dates": [str(value) for value in item[10]],
        "bottom_date": str(item[11]),
        "cross_date": str(item[12]),
        "limit_up_date": str(item[13]),
        "bottom_age": int(item[14]),
        "cross_age": int(item[15]),
        "limit_up_age": int(item[16]),
        "yellow_count": int(item[17]),
        "bottom_ok": bool(flags & 1),
        "cross_ok": bool(flags & 2),
        "limit_up_ok": bool(flags & 4),
        "yellow_ok": bool(flags & 8),
        "dragon_above_tiger": bool(flags & 16),
        "selected": bool(flags & 32),
        "eligible": True,
        "matched_count": sum(bool(flags & bit) for bit in (1, 2, 4, 8)),
        "body_low_tail": (
            [float(value) for value in item[19]]
            if seed_format >= 2 and len(item) > 19
            else []
        ),
        "yellow_date": (
            str(item[20]) if seed_format >= 2 and len(item) > 20 else ""
        ),
        "body_low_tail_dates": (
            [str(value) for value in item[21]]
            if seed_format >= 2 and len(item) > 21
            else []
        ),
        "observation_yellow_ok": (
            bool(flags & 64) if seed_format >= 3 else bool(flags & 8)
        ),
        "observation_yellow_count": (
            int(item[22])
            if seed_format >= 3 and len(item) > 22
            else int(item[17])
        ),
        "observation_yellow_date": (
            str(item[23])
            if seed_format >= 3 and len(item) > 23
            else str(item[20])
            if seed_format >= 2 and len(item) > 20
            else ""
        ),
        "observation_matched_count": sum(
            bool(flags & bit)
            for bit in (1, 2, 4, 64 if seed_format >= 3 else 8)
        ),
        "next_breakout_high_5": (
            float(item[24])
            if seed_format >= 4 and len(item) > 24
            else 0.0
        ),
        "dragon_value": (
            float(item[26]) if seed_format >= 5 and len(item) > 26 else 0.0
        ),
        "tiger_value": (
            float(item[27]) if seed_format >= 5 and len(item) > 27 else 0.0
        ),
        "yellow_line_value": (
            float(item[28]) if seed_format >= 5 and len(item) > 28 else 0.0
        ),
        "tier": str(item[29]) if seed_format >= 5 and len(item) > 29 else "",
        "prior_three_gap_abs": (
            [float(value) for value in item[30]]
            if seed_format >= 5 and len(item) > 30 and isinstance(item[30], list)
            else []
        ),
        "company_intro": (
            str(item[31]) if seed_format >= 6 and len(item) > 31 else ""
        ),
        "industry": (
            str(item[32]) if seed_format >= 6 and len(item) > 32 else ""
        ),
        "concepts": (
            [str(value) for value in item[33]]
            if seed_format >= 6 and len(item) > 33 and isinstance(item[33], list)
            else []
        ),
        "zig16_state": (
            int(item[34]) if seed_format >= 6 and len(item) > 34 else 0
        ),
        "zig16_candidate_value": (
            float(item[35]) if seed_format >= 6 and len(item) > 35 else 0.0
        ),
        "zig16_candidate_age": (
            int(item[36]) if seed_format >= 6 and len(item) > 36 else -1
        ),
        "zig16_candidate_date": (
            str(item[37]) if seed_format >= 6 and len(item) > 37 else ""
        ),
        "zig16_candidate_signal_ok": (
            bool(item[38]) if seed_format >= 6 and len(item) > 38 else False
        ),
        "bottom_price": (
            float(item[39]) if seed_format >= 7 and len(item) > 39 else 0.0
        ),
    }


def live_seeds(payload: dict) -> list[dict]:
    seed_format = int(payload.get("live_seed_format", 0))
    return [
        seed
        for item in payload.get("live_universe", [])
        if (seed := unpack_live_seed(item, seed_format))
    ]


def collect_targets(
    payload: dict,
    observation_limit: int | None = OBSERVATION_LIMIT,
) -> list[dict]:
    """Return the full lightweight universe when live signal seeds are present."""
    universe = live_seeds(payload)
    if universe:
        targets = {
            str(item["code"]): {
                "code": str(item["code"]),
                "name": str(item.get("name", "")),
                "market": int(item["market"]),
                "scope": "universe",
            }
            for item in universe
            if item.get("eligible")
            and not is_st_name(item.get("name", ""))
        }
        strategy = payload.get("strategy", {})
        for key, scope in (
            ("pending_entry_execution", "pending_entry"),
            ("pending_exit_execution", "pending_exit"),
        ):
            for position in strategy.get(key, []):
                code = str(position.get("code", ""))
                if code:
                    targets.setdefault(
                        code,
                        {
                            "code": code,
                            "name": str(position.get("name", "")),
                            "market": int(position.get("market", 0)),
                            "scope": scope,
                        },
                    )
        return sorted(
            targets.values(),
            key=lambda item: (item["market"], item["code"]),
        )
    return collect_display_targets(payload, observation_limit)


def collect_display_targets(
    payload: dict,
    observation_limit: int | None = OBSERVATION_LIMIT,
) -> list[dict]:
    """Return settled positions and close-confirmed rows visible on the page."""
    targets: dict[str, dict] = {}
    strategy = payload.get("strategy", {})
    for position in (
        list(strategy.get("active", []))
        + list(strategy.get("secondary_active", []))
        + list(strategy.get("pending_main", []))
        + list(strategy.get("pending_secondary", []))
        + list(strategy.get("pending_entry_execution", []))
    ):
        if is_st_name(position.get("name", "")):
            continue
        code = str(position["code"])
        targets[code] = {
            "code": code,
            "name": str(position.get("name", "")),
            "market": int(position["market"]),
            "scope": "pool",
        }
    for position in strategy.get("pending_exit_execution", []):
        code = str(position.get("code", ""))
        if not code:
            continue
        targets[code] = {
            "code": code,
            "name": str(position.get("name", "")),
            "market": int(position.get("market", 0)),
            "scope": "pending_exit",
        }

    minimum = int(payload.get("config", {}).get("near_match_minimum", 3))
    candidates = visible_observations(
        payload.get("results", []),
        minimum,
        observation_limit,
    )
    for row in candidates:
        code = str(row["code"])
        targets.setdefault(
            code,
            {
                "code": code,
                "name": str(row.get("name", "")),
                "market": int(row["market"]),
                "scope": "observation",
            },
        )
    return sorted(targets.values(), key=lambda item: (item["market"], item["code"]))


def collect_tracking_codes(
    payload: dict,
    live_tracking: dict[str, list[dict]] | None = None,
) -> dict[str, list[str]]:
    if live_tracking is not None:
        return {
            area: sorted(
                {
                    str(item["code"])
                    for item in live_tracking.get(area, [])
                    if item.get("code") and not item.get("trend_ended")
                }
            )
            for area in ("main", "secondary")
        }
    strategy = payload.get("strategy", {})

    def codes(key: str) -> list[str]:
        return sorted(
            {
                str(item["code"])
                for item in strategy.get(key, [])
                if item.get("code") and not is_st_name(item.get("name", ""))
            }
        )

    return {
        "main": sorted(
            set(codes("active"))
            | set(codes("pending_main"))
            | {
                str(item["code"])
                for key in ("pending_entry_execution", "pending_exit_execution")
                for item in strategy.get(key, [])
                if str(item.get("area", "main")) == "main" and item.get("code")
            }
        ),
        "secondary": sorted(
            set(codes("secondary_active"))
            | set(codes("pending_secondary"))
            | {
                str(item["code"])
                for key in ("pending_entry_execution", "pending_exit_execution")
                for item in strategy.get(key, [])
                if str(item.get("area", "main")) == "secondary" and item.get("code")
            }
        ),
    }


def build_live_tracking(
    payload: dict,
    quotes: dict[str, dict],
    *,
    live_trade_date: str = "",
) -> dict[str, list[dict]]:
    """Project settled positions onto live prices without settling strategy state."""
    strategy = payload.get("strategy", {})
    cfg = payload.get("config", {})
    close_trade_date = str(payload.get("trade_date", ""))
    evaluated_by_code: dict[str, dict] = {}
    for seed in live_seeds(payload):
        code = str(seed.get("code", ""))
        quote = quotes.get(code)
        if not code or quote is None:
            continue
        try:
            evaluated = evaluate_live_seed(seed, quote, cfg, close_trade_date)
        except (KeyError, TypeError, ValueError):
            evaluated = None
        if evaluated is not None:
            evaluated_by_code[code] = evaluated
    result: dict[str, list[dict]] = {"main": [], "secondary": []}
    for area, key in (("main", "active"), ("secondary", "secondary_active")):
        for position in strategy.get(key, []):
            if not position.get("code"):
                continue
            code = str(position["code"])
            quote = quotes.get(code, {})
            live_name = str(
                quote.get("name") or position.get("name", "")
            )
            ineligible_live = is_st_name(live_name)
            quote_price = float(quote.get("price", 0.0) or 0.0)
            has_quote = quote_price > 0
            live_price = quote_price if has_quote else float(position.get("last_close", 0.0))
            entry_price = float(position.get("entry_price", 0.0))
            live_return = (
                (live_price / entry_price - 1.0) * 100.0
                if entry_price > 0 and live_price > 0
                else float(position.get("return_pct", 0.0))
            )
            live_signal = evaluated_by_code.get(code)
            dragon_above_tiger = (
                bool(live_signal.get("dragon_above_tiger"))
                if live_signal is not None
                else None
            )
            live_extra_bar = int(
                bool(
                    str(quote.get("server_time", ""))[:10]
                    and str(quote.get("server_time", ""))[:10]
                    > str(position.get("last_date", ""))
                )
            )
            live_position = dict(position)
            live_position["holding_days"] = (
                int(position.get("holding_days", 1)) + live_extra_bar
            )
            setup_elapsed = int(
                position.get("setup_elapsed_bars_at_entry", 0)
            ) + max(0, int(position.get("holding_days", 1)) - 1) + live_extra_bar
            signal_erased = signal_recalculated_away(
                position,
                live_signal,
                setup_elapsed,
            )
            if has_quote and ineligible_live:
                exit_reason = "趋势结束：股票名称含 ST，不符合入选范围"
            else:
                exit_reason = (
                    trend_exit_reason(
                        live_position,
                        live_price,
                        dragon_above_tiger=dragon_above_tiger,
                        signal_erased=signal_erased,
                        row=live_signal,
                    )
                    if has_quote
                    else ""
                )
            provisional_exit = bool(exit_reason)
            pending_reasons: list[str] = []
            if signal_erased:
                pending_reasons.append("龙腾跃虎标签被后续K线重算消失")
            if live_signal is not None and not provisional_exit:
                pending_reasons.extend(
                    reason
                    for reason in trend_pending_reason(
                        live_position,
                        live_signal,
                        live_price,
                    ).split("；")
                    if reason
                )
            elif (
                not has_quote
                and position.get("status") == "待观察中"
                and position.get("status_detail")
            ):
                pending_reasons.append(str(position["status_detail"]))
            pending_reason = "；".join(dict.fromkeys(pending_reasons))
            if provisional_exit:
                detail = (
                    f"{exit_reason.removeprefix('趋势结束：')}；"
                    "若收盘仍满足则确认卖点，下一交易日开盘执行"
                )
                status = "待观察中"
                operation = "卖出触发 · 等待收盘"
            elif pending_reason:
                detail = f"{pending_reason}；尚未形成正式卖点"
                status = "待观察中"
                operation = "谨慎持有"
            elif has_quote:
                detail = "趋势条件仍有效，盘中持续跟踪"
                status = (
                    "趋势开始"
                    if str(position.get("entry_date", ""))
                    == str(position.get("last_date", ""))
                    and str(quote.get("server_time", ""))[:10]
                    <= str(position.get("last_date", ""))
                    else "上升趋势中"
                )
                operation = (
                    "开盘已执行买入" if status == "趋势开始" else "继续持有"
                )
            else:
                detail = "最新行情待确认，暂按最近收盘展示"
                status = str(position.get("status", "上升趋势中"))
                operation = str(
                    position.get(
                        "operation",
                        "谨慎持有" if status == "待观察中" else "继续持有",
                    )
                )
            result[area].append(
                {
                    "position_id": str(position.get("position_id", "")),
                    "code": code,
                    "name": live_name,
                    "market": int(position.get("market", quote.get("market", 0))),
                    "entry_date": str(position.get("entry_date", "")),
                    "entry_price": entry_price,
                    "holding_days": int(live_position.get("holding_days", 0)),
                    "settled_date": str(position.get("last_date", "")),
                    "settled_price": float(position.get("last_close", 0.0)),
                    "settled_return_pct": float(position.get("return_pct", 0.0)),
                    "live_price": live_price,
                    "live_return_pct": live_return,
                    "server_time": str(quote.get("server_time", "")),
                    "quote_available": has_quote,
                    "trend_ended": False,
                    "provisional_exit": provisional_exit,
                    "status": status,
                    "operation": operation,
                    "status_detail": detail,
                    "exit_reason": exit_reason,
                    "setup_cancelled": False,
                }
            )
    for area, key in (
        ("main", "pending_main"),
        ("secondary", "pending_secondary"),
    ):
        for setup in strategy.get(key, []):
            if not setup.get("code"):
                continue
            code = str(setup["code"])
            quote = quotes.get(code, {})
            live_name = str(quote.get("name") or setup.get("name", ""))
            quote_price = float(quote.get("price", 0.0) or 0.0)
            has_quote = quote_price > 0
            live_price = (
                quote_price
                if has_quote
                else float(setup.get("last_close", setup.get("setup_price", 0.0)))
            )
            setup_price = float(setup.get("setup_price", 0.0))
            setup_return = (
                (live_price / setup_price - 1.0) * 100.0
                if live_price > 0 and setup_price > 0
                else 0.0
            )
            live_signal = evaluated_by_code.get(code)
            live_extra_bar = int(
                bool(
                    str(quote.get("server_time", ""))[:10]
                    and str(quote.get("server_time", ""))[:10]
                    > str(setup.get("last_date", ""))
                )
            )
            elapsed = int(setup.get("setup_elapsed_bars", 0)) + live_extra_bar
            cancel_reason = ""
            if area == "main":
                confirmed = False
                status = "观察中"
                operation = "仅观察"
                detail = "主选信号不进入自动交易；同一信号仅记录一次"
            elif is_st_name(live_name):
                cancel_reason = "股票名称含 ST，不符合入选范围"
            elif live_signal is not None and signal_recalculated_away(
                setup,
                live_signal,
                elapsed,
            ):
                cancel_reason = "龙腾跃虎信号被后续K线重算消失"
            elif (
                live_signal is not None
                and not live_signal.get("dragon_above_tiger")
            ):
                cancel_reason = "龙线不再高于虎线"
            elif elapsed > ENTRY_DELAY_BARS:
                cancel_reason = "已错过D+2收盘确认窗口"
            if area != "main":
                current_dragon = float(
                    (live_signal or {}).get("dragon_value", 0.0) or 0.0
                )
                d1_dragon = float(
                    setup.get("confirmation_d1_dragon", 0.0) or 0.0
                )
                pullback_floor = setup_price * (
                    1.0 - ENTRY_MAX_PULLBACK_PCT / 100.0
                )
                confirmed = bool(
                    not cancel_reason
                    and live_signal is not None
                    and elapsed == ENTRY_DELAY_BARS
                    and current_dragon > 0
                    and d1_dragon > 0
                    and live_price + 1e-8 >= current_dragon
                    and current_dragon + 1e-8 >= d1_dragon
                    and live_price + 1e-8 >= pullback_floor
                )
            if area == "main":
                pass
            elif cancel_reason:
                status = "待观察中"
                operation = "取消候选 · 等待收盘"
                detail = f"{cancel_reason}；若收盘仍成立则停止等待买点"
            elif confirmed:
                status = "待观察中"
                operation = "买点触发 · 等待收盘"
                detail = (
                    "盘中满足D+2低风险确认条件；若收盘保持，"
                    "下一可交易日开盘执行买入"
                )
            else:
                status = "待观察中"
                operation = "等待D+2收盘确认"
                if live_signal is None:
                    detail = "盘中信号数据待确认，不提前给出买点"
                elif elapsed < ENTRY_DELAY_BARS:
                    detail = "信号与龙虎关系仍有效；等待D+2收盘确认"
                elif current_dragon <= 0 or d1_dragon <= 0:
                    detail = "D+2确认所需的龙线数据不足，不提前给出买点"
                elif live_price + 1e-8 < current_dragon:
                    detail = "盘中价格仍低于龙线，尚未满足D+2确认条件"
                elif current_dragon + 1e-8 < d1_dragon:
                    detail = "当前龙线低于D+1龙线，尚未满足D+2确认条件"
                elif live_price + 1e-8 < pullback_floor:
                    detail = "盘中价格较信号日收盘回撤超过3%，尚未满足确认条件"
                else:
                    detail = "等待D+2收盘完成正式确认"
            result[area].append(
                {
                    "position_id": str(setup.get("setup_id", "")),
                    "code": code,
                    "name": live_name,
                    "market": int(setup.get("market", quote.get("market", 0))),
                    "entry_date": str(setup.get("setup_date", "")),
                    "entry_price": setup_price,
                    "holding_days": elapsed,
                    "settled_date": str(setup.get("last_date", "")),
                    "settled_price": float(setup.get("last_close", setup_price)),
                    "settled_return_pct": setup_return,
                    "live_price": live_price,
                    "live_return_pct": setup_return,
                    "server_time": str(quote.get("server_time", "")),
                    "quote_available": has_quote,
                    "trend_ended": False,
                    "provisional_cancel": bool(cancel_reason),
                    "provisional_entry": confirmed,
                    "status": status,
                    "operation": operation,
                    "status_detail": detail,
                    "exit_reason": cancel_reason,
                    "setup_cancelled": False,
                    "pending_setup": True,
                    "confirmation_d1_dragon": float(
                        setup.get("confirmation_d1_dragon", 0.0) or 0.0
                    ),
                }
            )
    for order in strategy.get("pending_entry_execution", []):
        area = str(order.get("area", "main"))
        if area not in result or not order.get("code"):
            continue
        code = str(order["code"])
        quote = quotes.get(code, {})
        quote_price = float(quote.get("price", 0.0) or 0.0)
        open_price = float(quote.get("open", 0.0) or 0.0)
        quote_date = str(quote.get("server_time", ""))[:10] or live_trade_date
        trigger_date = str(order.get("entry_trigger_date", ""))
        execution_day = bool(quote_date and trigger_date and quote_date > trigger_date)
        ineligible = bool(
            is_st_name(order.get("name", ""))
            or is_st_name(quote.get("name", ""))
        )
        locked = bool(
            execution_day
            and not ineligible
            and open_price > 0
            and _quote_is_locked_limit(
                quote,
                code,
                order.get("market", quote.get("market", 0)),
                quote.get("name") or order.get("name", ""),
                "up",
            )
        )
        live_signal = evaluated_by_code.get(code)
        invalid_reason = ""
        preview_wait = int(order.get("execution_wait_bars", 0))
        if execution_day and not ineligible and not (
            open_price > 0 and not locked
        ):
            preview_wait += int(
                quote_date
                > str(order.get("last_execution_attempt_date", ""))
            )
            if live_signal is not None:
                if not live_signal.get("dragon_above_tiger"):
                    invalid_reason = "等待成交期间龙线不再高于虎线"
                elif signal_recalculated_away(
                    order,
                    live_signal,
                    int(order.get("setup_elapsed_bars", 0)) + preview_wait,
                ):
                    invalid_reason = "原龙腾跃虎信号被K线重算消失"
            if (
                not invalid_reason
                and preview_wait >= ENTRY_EXECUTION_MAX_WAIT_BARS
            ):
                invalid_reason = (
                    f"连续{ENTRY_EXECUTION_MAX_WAIT_BARS}个交易日"
                    + (
                        "一字涨停无法买入"
                        if locked
                        else "停牌或开盘价缺失，无法买入"
                    )
                )
        provisional_execution = bool(
            execution_day
            and not ineligible
            and not invalid_reason
            and open_price > 0
            and not locked
        )
        if ineligible:
            operation = "取消买入待收盘"
            detail = "股票名称含 ST；盘中不执行买入，收盘任务确认取消候选"
        elif invalid_reason:
            operation = "取消买入待收盘"
            detail = f"{invalid_reason}；盘中仅预览，收盘任务确认取消"
        elif locked:
            operation = "等待可成交开盘"
            detail = "当前仍封在一字涨停，盘中不假定可以买入；收盘后确认是否继续等待"
        elif provisional_execution:
            operation = "开盘买入待结算"
            detail = (
                f"今日开盘价 {open_price:.2f} 元可模拟执行；"
                "盘中仅预告，收盘任务写入正式持仓"
            )
        elif execution_day:
            operation = "暂停执行买入"
            detail = "今日开盘价尚未取得，不使用最新价或收盘价代替成交"
        else:
            operation = "下一交易日开盘买入"
            detail = "买点已由收盘确认，等待下一交易日开盘模拟执行"
        live_return = (
            (quote_price / open_price - 1.0) * 100.0
            if provisional_execution and quote_price > 0
            else 0.0
        )
        result[area].append(
            {
                "position_id": str(order.get("execution_id", "")),
                "code": code,
                "name": str(quote.get("name") or order.get("name", "")),
                "market": int(order.get("market", quote.get("market", 0))),
                "entry_trigger_date": trigger_date,
                "entry_trigger_close": float(order.get("entry_trigger_close", 0.0)),
                "entry_date": "",
                "entry_price": open_price if provisional_execution else 0.0,
                "holding_days": 0,
                "settled_date": trigger_date,
                "settled_price": float(order.get("entry_trigger_close", 0.0)),
                "settled_return_pct": 0.0,
                "live_price": quote_price,
                "live_return_pct": live_return,
                "server_time": str(quote.get("server_time", "")),
                "quote_available": quote_price > 0,
                "trend_ended": False,
                "pending_execution": True,
                "pending_entry_execution": True,
                "provisional_entry_execution": provisional_execution,
                "execution_blocked": bool(locked or ineligible or invalid_reason),
                "provisional_cancel": bool(ineligible or invalid_reason),
                "status": (
                    "待观察中"
                    if ineligible or invalid_reason
                    else "买点已确认"
                ),
                "operation": operation,
                "status_detail": detail,
                "exit_reason": (
                    "股票名称含 ST" if ineligible else invalid_reason
                ),
                "setup_cancelled": False,
            }
        )
    for order in strategy.get("pending_exit_execution", []):
        area = str(order.get("area", "main"))
        if area not in result or not order.get("code"):
            continue
        code = str(order["code"])
        quote = quotes.get(code, {})
        quote_price = float(quote.get("price", 0.0) or 0.0)
        open_price = float(quote.get("open", 0.0) or 0.0)
        quote_date = str(quote.get("server_time", ""))[:10]
        trigger_date = str(order.get("exit_trigger_date", ""))
        execution_day = bool(quote_date and trigger_date and quote_date > trigger_date)
        locked = bool(
            execution_day
            and open_price > 0
            and _quote_is_locked_limit(
                quote,
                code,
                order.get("market", quote.get("market", 0)),
                quote.get("name") or order.get("name", ""),
                "down",
            )
        )
        provisional_execution = bool(execution_day and open_price > 0 and not locked)
        if locked:
            operation = "等待可成交开盘"
            detail = "当前仍封在一字跌停，盘中不假定可以卖出；继续等待首次可成交开盘"
        elif provisional_execution:
            operation = "开盘卖出待结算"
            detail = (
                f"今日开盘价 {open_price:.2f} 元可模拟执行；"
                "盘中仅预告，收盘任务再结算收益与成功率"
            )
        elif execution_day:
            operation = "暂停执行卖出"
            detail = "今日开盘价尚未取得，不使用最新价或收盘价代替成交"
        else:
            operation = "下一交易日开盘卖出"
            detail = "卖点已由收盘确认，等待下一交易日开盘模拟执行"
        entry_price = float(order.get("entry_price", 0.0))
        live_return = (
            (quote_price / entry_price - 1.0) * 100.0
            if quote_price > 0 and entry_price > 0
            else float(order.get("return_pct", 0.0))
        )
        preview_exit_return = (
            (open_price / entry_price - 1.0) * 100.0
            if provisional_execution and entry_price > 0
            else None
        )
        live_holding_days = int(order.get("holding_days", 0)) + int(
            bool(quote_date and quote_date > str(order.get("last_date", "")))
        )
        result[area].append(
            {
                "position_id": str(order.get("position_id", "")),
                "code": code,
                "name": str(quote.get("name") or order.get("name", "")),
                "market": int(order.get("market", quote.get("market", 0))),
                "entry_date": str(order.get("entry_date", "")),
                "entry_price": entry_price,
                "holding_days": live_holding_days,
                "exit_trigger_date": trigger_date,
                "exit_trigger_close": float(order.get("exit_trigger_close", 0.0)),
                "settled_date": str(order.get("last_date", "")),
                "settled_price": float(order.get("last_close", 0.0)),
                "settled_return_pct": float(order.get("return_pct", 0.0)),
                "live_price": quote_price,
                "live_return_pct": live_return,
                "preview_exit_price": open_price if provisional_execution else None,
                "preview_exit_return_pct": preview_exit_return,
                "server_time": str(quote.get("server_time", "")),
                "quote_available": quote_price > 0,
                "trend_ended": False,
                "pending_execution": True,
                "pending_exit_execution": True,
                "provisional_exit_execution": provisional_execution,
                "execution_blocked": locked,
                "status": "卖点已确认",
                "operation": operation,
                "status_detail": detail,
                "exit_reason": str(order.get("exit_reason", "")),
                "setup_cancelled": False,
            }
        )
    return result


def market_state(now: datetime) -> tuple[str, str]:
    if now.weekday() >= 5:
        return "休市", "周末休市，页面保留最近一次已验证行情"
    hhmm = now.strftime("%H:%M")
    if "09:15" <= hhmm < "09:30":
        return "集合竞价", "主选与次选按最新行情预选；趋势状态实时判断，统计收盘结算"
    if "09:30" <= hhmm <= "11:30" or "13:00" <= hhmm <= "15:00":
        return "盘中行情", "主选与次选约每 5 分钟重算；趋势状态实时判断，统计收盘结算"
    if "11:30" < hhmm < "13:00":
        return "午间休市", "显示上午收盘行情，13:00 后继续刷新"
    if hhmm > "15:00":
        return "已收盘", "等待收盘完整扫描确认今日策略信号"
    return "未开盘", "显示最近一次已验证的收盘数据"


def chunks(items: Sequence[dict], size: int = 80) -> Iterable[Sequence[dict]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def parse_tencent_quotes(raw: str, targets: Sequence[dict]) -> dict[str, dict]:
    by_code = {str(item["code"]): item for item in targets}
    quotes: dict[str, dict] = {}
    for payload in re.findall(r'v_[^=]+="([^"]*)";', raw):
        fields = payload.split("~")
        if len(fields) < 36:
            continue
        code = fields[2]
        target = by_code.get(code)
        if target is None:
            continue
        try:
            amount_parts = fields[35].split("/")
            amount = float(amount_parts[2]) if len(amount_parts) >= 3 else 0.0
            timestamp = fields[30]
            server_time = (
                datetime.strptime(timestamp, "%Y%m%d%H%M%S")
                .replace(tzinfo=SHANGHAI)
                .isoformat(timespec="seconds")
            )
            quotes[code] = {
                "code": code,
                "name": str(target.get("name") or fields[1]),
                "market": int(target["market"]),
                "scope": target.get("scope", ""),
                "price": float(fields[3]),
                "pre_close": float(fields[4]),
                "open": float(fields[5]),
                "high": float(fields[33]),
                "low": float(fields[34]),
                "change_pct": float(fields[32]),
                "volume": float(fields[6]),
                "amount": amount,
                "server_time": server_time,
            }
        except (ValueError, IndexError):
            continue
    return quotes


def normalize_quote_time(value: object, now: datetime | None = None) -> str:
    """Normalize provider timestamps to an Asia/Shanghai ISO timestamp."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        return parsed.astimezone(SHANGHAI).isoformat(timespec="seconds")

    reference = now or datetime.now(SHANGHAI)
    reference = (
        reference.replace(tzinfo=SHANGHAI)
        if reference.tzinfo is None
        else reference.astimezone(SHANGHAI)
    )
    for pattern in ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M"):
        try:
            parsed_time = datetime.strptime(text, pattern).time()
            parsed = datetime.combine(
                reference.date(),
                parsed_time,
                tzinfo=SHANGHAI,
            )
            if parsed > reference + timedelta(minutes=10):
                parsed -= timedelta(days=1)
                while parsed.weekday() >= 5:
                    parsed -= timedelta(days=1)
            return parsed.isoformat(timespec="seconds")
        except ValueError:
            continue
    return ""


def fetch_tencent_quote_group(targets: Sequence[dict]) -> dict[str, dict]:
    symbols = [
        f"{'sh' if int(item['market']) == 1 else 'sz'}{item['code']}"
        for item in targets
    ]
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    request = Request(
        url,
        headers={
            "Referer": "https://finance.qq.com/",
            "User-Agent": "Mozilla/5.0 (compatible; ali-stock-daily-picks/1.0)",
        },
    )
    with urlopen(request, timeout=12) as response:
        raw = response.read().decode("gbk", errors="replace")
    return parse_tencent_quotes(raw, targets)


def fetch_tencent_quotes(targets: Sequence[dict]) -> dict[str, dict]:
    groups = list(chunks(targets))
    quotes: dict[str, dict] = {}
    workers = min(8, len(groups))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(fetch_tencent_quote_group, group)
            for group in groups
        ]
        for future in as_completed(futures):
            quotes.update(future.result())
    if not quotes:
        raise RuntimeError("腾讯行情接口未返回有效报价")
    return quotes


def fetch_xmtdx_quotes(targets: Sequence[dict]) -> tuple[dict[str, dict], str]:
    from xmtdx import Market, TdxClient

    if not targets:
        return {}, ""
    ranked = TdxClient.ping_all(timeout=2.5)
    if not ranked:
        raise RuntimeError("无法连接通达信行情服务器")

    last_error: Exception | None = None
    for host, _ in ranked[:8]:
        try:
            quotes: dict[str, dict] = {}
            with TdxClient(host, timeout=8, auto_reconnect=True) as client:
                for group in chunks(targets):
                    rows = client.get_security_quotes(
                        [(Market(int(item["market"])), item["code"]) for item in group]
                    )
                    by_code = {item["code"]: item for item in group}
                    for quote in rows:
                        target = by_code.get(str(quote.code), {})
                        price = float(quote.price)
                        pre_close = float(quote.pre_close)
                        change_pct = (
                            (price / pre_close - 1.0) * 100.0
                            if price > 0 and pre_close > 0
                            else 0.0
                        )
                        quotes[str(quote.code)] = {
                            "code": str(quote.code),
                            "name": target.get("name", ""),
                            "market": int(quote.market),
                            "scope": target.get("scope", ""),
                            "price": price,
                            "pre_close": pre_close,
                            "open": float(quote.open),
                            "high": float(quote.high),
                            "low": float(quote.low),
                            "change_pct": change_pct,
                            "volume": float(quote.vol),
                            "amount": float(quote.amount),
                            "server_time": normalize_quote_time(quote.server_time),
                        }
            if quotes:
                return quotes, host
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"行情服务器均不可用：{last_error}")


def fetch_quotes(
    targets: Sequence[dict],
) -> tuple[dict[str, dict], str, str]:
    if not targets:
        return {}, "", ""
    try:
        quotes = fetch_tencent_quotes(targets)
        if len(quotes) == len(targets):
            return quotes, "tencent", "qt.gtimg.cn"
    except Exception as exc:
        tencent_error = exc
    else:
        tencent_error = RuntimeError(
            f"腾讯行情仅返回 {len(quotes)}/{len(targets)} 只"
        )

    try:
        quotes, host = fetch_xmtdx_quotes(targets)
        return quotes, "xmtdx", host
    except Exception as xmtdx_error:
        raise RuntimeError(
            f"腾讯行情失败：{tencent_error}；通达信行情失败：{xmtdx_error}"
        ) from xmtdx_error


def coefficient_value(coefficients: Sequence[float], low: float, high: float) -> float:
    return (
        float(coefficients[0])
        + float(coefficients[1]) * low
        + float(coefficients[2]) * high
    )


def current_cci(typical_13: Sequence[float], high: float, low: float, close: float) -> float:
    window = [float(value) for value in typical_13[-13:]]
    window.append((high + low + close) / 3.0)
    if len(window) < 14:
        return 0.0
    mean = sum(window) / 14
    deviation = sum(abs(value - mean) for value in window) / 14
    return 0.0 if deviation == 0 else (window[-1] - mean) / (0.015 * deviation)


def _baseline_live_row(seed: dict, quote: dict, cfg: dict | None = None) -> dict:
    row = {
        "code": str(seed["code"]),
        "name": str(seed.get("name", quote.get("name", ""))),
        "market": int(seed["market"]),
        "price": float(quote.get("price", seed.get("previous_close", 0.0))),
        "change_pct": float(quote.get("change_pct", 0.0)),
        "server_time": str(quote.get("server_time", "")),
        "bottom_ok": bool(seed.get("bottom_ok")),
        "cross_ok": bool(seed.get("cross_ok")),
        "cross_age": int(seed.get("cross_age", -1)),
        "cross_lookback_days": int(
            (cfg or {}).get("cross_lookback_days", 11)
        ),
        "limit_up_ok": bool(seed.get("limit_up_ok")),
        "yellow_ok": bool(seed.get("yellow_ok")),
        "bottom_date": str(seed.get("bottom_date", "")),
        "bottom_price": float(seed.get("bottom_price", 0.0) or 0.0),
        "cross_date": str(seed.get("cross_date", "")),
        "limit_up_date": str(seed.get("limit_up_date", "")),
        "yellow_date": str(seed.get("yellow_date", "")),
        "yellow_count": int(seed.get("yellow_count", 0)),
        "matched_count": int(seed.get("matched_count", 0)),
        "observation_yellow_ok": bool(
            seed.get("observation_yellow_ok", seed.get("yellow_ok"))
        ),
        "observation_yellow_date": str(
            seed.get("observation_yellow_date", seed.get("yellow_date", ""))
        ),
        "observation_yellow_count": int(
            seed.get("observation_yellow_count", seed.get("yellow_count", 0))
        ),
        "observation_matched_count": int(
            seed.get("observation_matched_count", seed.get("matched_count", 0))
        ),
        "dragon_above_tiger": bool(seed.get("dragon_above_tiger")),
        "eligible": bool(seed.get("eligible")),
        "selected": bool(seed.get("selected")),
        "entry_breakout_high_5": float(
            seed.get("next_breakout_high_5", 0.0) or 0.0
        ),
        "dragon_value": float(seed.get("dragon_value", 0.0) or 0.0),
        "tiger_value": float(seed.get("tiger_value", 0.0) or 0.0),
        "yellow_line_value": float(seed.get("yellow_line_value", 0.0) or 0.0),
        "prior_three_gap_abs": [
            float(value) for value in seed.get("prior_three_gap_abs", [])
        ],
        "company_intro": str(seed.get("company_intro", "")),
        "industry": str(seed.get("industry", "")),
        "concepts": [str(value) for value in seed.get("concepts", [])],
    }
    return decorate_row(row, cfg or {}) if "line_gap_max_abs" in (cfg or {}) else row


def evaluate_live_seed(
    seed: dict,
    quote: dict,
    cfg: dict,
    close_trade_date: str,
) -> dict | None:
    """Re-evaluate one stock from today's OHLC without mutating settled state."""
    if (
        not seed.get("eligible")
        or is_st_name(seed.get("name", ""))
        or is_st_name(quote.get("name", ""))
    ):
        return None
    price = float(quote.get("price", 0.0))
    open_price = float(quote.get("open", 0.0))
    high = float(quote.get("high", 0.0))
    low = float(quote.get("low", 0.0))
    server_time = str(quote.get("server_time", ""))
    live_date = server_time[:10] if len(server_time) >= 10 else ""
    if (
        not live_date
        or live_date <= close_trade_date
        or live_date <= str(seed.get("base_date", ""))
    ):
        return _baseline_live_row(seed, quote, cfg)
    if min(price, open_price, high, low) <= 0:
        return None

    coefficients = seed["line_coefficients"]
    dragon_tail_coefficients = coefficients.get("dragon_tail")
    tiger_tail_coefficients = coefficients.get("tiger_tail")
    yellow_tail_coefficients = coefficients.get("yellow_tail")
    if dragon_tail_coefficients and tiger_tail_coefficients:
        dragon_tail = [
            coefficient_value(parts, low, high)
            for parts in dragon_tail_coefficients
        ]
        tiger_tail = [
            coefficient_value(parts, low, high)
            for parts in tiger_tail_coefficients
        ]
    else:
        dragon_tail = [
            coefficient_value(coefficients["previous_dragon"], low, high),
            coefficient_value(coefficients["dragon"], low, high),
        ]
        tiger_tail = [
            coefficient_value(coefficients["previous_tiger"], low, high),
            coefficient_value(coefficients["tiger"], low, high),
        ]
    if yellow_tail_coefficients:
        yellow_line_tail = [
            coefficient_value(parts, low, high)
            for parts in yellow_tail_coefficients
        ]
    else:
        yellow_line_tail = [float(seed.get("yellow_line_value", 0.0) or 0.0)]
    dragon = dragon_tail[-1]
    tiger = tiger_tail[-1]
    yellow_line = yellow_line_tail[-1]
    dragon_above_tiger = dragon > tiger
    prior_cross_age = int(seed.get("cross_age", -1))
    cross_age = prior_cross_age + 1 if prior_cross_age >= 0 else -1

    lookback_days = int(cfg["bottom_lookback_days"])
    bottom_age = int(seed.get("bottom_age", -1))
    candidate_age = int(seed.get("zig16_candidate_age", -1))
    candidate_value = float(seed.get("zig16_candidate_value", 0.0) or 0.0)
    candidate_date = str(seed.get("zig16_candidate_date", ""))
    candidate_state = int(seed.get("zig16_state", 0))
    candidate_signal_ok = bool(seed.get("zig16_candidate_signal_ok"))
    candidate_updated_today = bool(
        candidate_state == 2
        and candidate_value > 0
        and price <= candidate_value + 1e-8
    )
    live_candidate_value = price if candidate_updated_today else candidate_value
    live_candidate_date = live_date if candidate_updated_today else candidate_date
    live_candidate_age = 0 if candidate_updated_today else candidate_age + 1
    live_candidate_signal_ok = (
        bool(
            high > low + 0.04
            and current_cci(seed.get("typical_13", []), high, low, price) < -110
        )
        if candidate_updated_today
        else candidate_signal_ok
    )
    confirmed_candidate = bool(
        candidate_state == 2
        and candidate_value > 0
        and price >= candidate_value * 1.16 - 1e-8
        and candidate_signal_ok
        and candidate_age >= 0
        and candidate_age + 1 < lookback_days
    )
    provisional_candidate = bool(
        candidate_state == 2
        and not confirmed_candidate
        and live_candidate_value > 0
        and live_candidate_signal_ok
        and 0 <= live_candidate_age < lookback_days
    )
    seed_bottom_is_provisional = bool(
        candidate_state == 2
        and candidate_date
        and str(seed.get("bottom_date", "")) == candidate_date
    )
    prior_bottom = bool(
        bottom_age >= 0
        and bottom_age + 1 < lookback_days
        and not seed_bottom_is_provisional
    )
    bottom_ok = confirmed_candidate or provisional_candidate or prior_bottom
    bottom_date = (
        live_candidate_date
        if confirmed_candidate or provisional_candidate
        else str(seed.get("bottom_date", ""))
        if prior_bottom
        else ""
    )
    bottom_price = (
        live_candidate_value
        if confirmed_candidate or provisional_candidate
        else float(seed.get("bottom_price", 0.0) or 0.0)
        if prior_bottom
        else 0.0
    )

    yellow = dragon > min(open_price, price)
    yellow_count = 1 if yellow else 0
    yellow_ok = False
    yellow_date = live_date if yellow else ""
    observation_yellow_count = yellow_count
    observation_yellow_ok = yellow
    observation_yellow_date = live_date if yellow else ""
    if len(dragon_tail) >= 2:
        cross_flags = [False] + [
            dragon_tail[index] > tiger_tail[index]
            and dragon_tail[index - 1] <= tiger_tail[index - 1]
            for index in range(1, len(dragon_tail))
        ]
        history_tail_size = len(dragon_tail) - 1
        body_dates = [
            *list(seed.get("body_low_tail_dates", []))[-history_tail_size:],
            live_date,
        ]
        cross_date = next(
            (
                body_dates[index]
                for index in range(len(cross_flags) - 1, 0, -1)
                if cross_flags[index] and index < len(body_dates)
            ),
            "",
        )
        cross_ok = bool(cross_date and dragon_above_tiger)
        body_lows = [
            *[
                float(value)
                for value in seed.get("body_low_tail", [])
            ][-history_tail_size:],
            min(open_price, price),
        ]
        if len(body_lows) == len(dragon_tail) and len(body_dates) == len(dragon_tail):
            yellow_flags = [
                dragon_value > body_low
                for dragon_value, body_low in zip(dragon_tail, body_lows)
            ]
            observation_yellow_count = 0
            for flag in reversed(yellow_flags):
                if not flag:
                    break
                observation_yellow_count += 1
            observation_yellow_ok = (
                observation_yellow_count
                >= int(cfg["yellow_consecutive_days"])
            )
            observation_yellow_date = (
                live_date if observation_yellow_ok else ""
            )
            paired_cross, paired_yellow, yellow_count = cross_yellow_pair(
                cross_flags,
                yellow_flags,
                end_index=len(cross_flags) - 1,
                cross_lookback_days=int(cfg["cross_lookback_days"]),
                yellow_consecutive_days=int(cfg["yellow_consecutive_days"]),
                before_days=int(cfg.get("yellow_before_cross_days", 2)),
                after_days=int(cfg.get("yellow_after_cross_days", 2)),
            )
            yellow_ok = paired_cross >= 0
            yellow_date = (
                body_dates[paired_yellow] if paired_yellow >= 0 else ""
            )
            if paired_cross >= 0:
                cross_date = body_dates[paired_cross]
                cross_age = len(cross_flags) - 1 - paired_cross
        else:
            yellow_ok = bool(
                cross_ok
                and (
                    yellow
                    or (
                        seed.get("yellow_ok")
                        and int(seed.get("cross_age", -1)) + 1
                        < int(cfg["cross_lookback_days"])
                    )
                )
            )
            if not yellow and yellow_ok:
                yellow_count = int(seed.get("yellow_count", 0))
                yellow_date = str(seed.get("yellow_date", ""))
    else:
        new_cross = bool(
            dragon_above_tiger
            and dragon_tail[-2] <= tiger_tail[-2]
        )
        cross_age = int(seed.get("cross_age", -1))
        prior_cross = (
            cross_age >= 0
            and cross_age + 1 < int(cfg["cross_lookback_days"])
        )
        cross_ok = bool((new_cross or prior_cross) and dragon_above_tiger)
        cross_date = (
            live_date
            if new_cross
            else str(seed.get("cross_date", ""))
            if prior_cross and dragon_above_tiger
            else ""
        )
        cross_age = 0 if new_cross else cross_age if prior_cross else -1
        yellow_ok = bool(
            cross_ok
            and (
                yellow
                or (
                    seed.get("yellow_ok")
                    and int(seed.get("cross_age", -1)) + 1
                    < int(cfg["cross_lookback_days"])
                )
            )
        )
        if not yellow and yellow_ok:
            yellow_count = int(seed.get("yellow_count", 0))
            yellow_date = str(seed.get("yellow_date", ""))

    new_limit_up = price + 1e-8 >= float(seed["next_limit_price"])
    limit_age = int(seed.get("limit_up_age", -1))
    prior_limit_up = (
        limit_age >= 0
        and limit_age + 1 < int(cfg["limit_up_lookback_days"])
    )
    limit_up_ok = new_limit_up or prior_limit_up
    limit_up_date = (
        live_date
        if new_limit_up
        else str(seed.get("limit_up_date", ""))
        if prior_limit_up
        else ""
    )

    matched_count = sum((bottom_ok, cross_ok, limit_up_ok, yellow_ok))
    observation_matched_count = sum(
        (bottom_ok, cross_ok, limit_up_ok, observation_yellow_ok)
    )
    selected = bool(seed.get("eligible") and matched_count == 4)
    prior_three_gap_abs = [
        abs(float(dragon_tail[index]) - float(tiger_tail[index]))
        for index in range(max(0, len(dragon_tail) - 4), len(dragon_tail) - 1)
    ]
    row = {
        "code": str(seed["code"]),
        "name": str(seed.get("name", quote.get("name", ""))),
        "market": int(seed["market"]),
        "price": price,
        "change_pct": float(quote.get("change_pct", 0.0)),
        "server_time": server_time,
        "bottom_ok": bottom_ok,
        "cross_ok": cross_ok,
        "cross_age": cross_age,
        "cross_lookback_days": int(cfg["cross_lookback_days"]),
        "limit_up_ok": limit_up_ok,
        "yellow_ok": yellow_ok,
        "bottom_date": bottom_date,
        "bottom_price": bottom_price,
        "cross_date": cross_date,
        "limit_up_date": limit_up_date,
        "yellow_date": yellow_date,
        "yellow_count": yellow_count,
        "matched_count": matched_count,
        "observation_yellow_ok": observation_yellow_ok,
        "observation_yellow_date": observation_yellow_date,
        "observation_yellow_count": observation_yellow_count,
        "observation_matched_count": observation_matched_count,
        "dragon_above_tiger": dragon_above_tiger,
        "dragon_value": dragon,
        "tiger_value": tiger,
        "yellow_line_value": yellow_line,
        "prior_three_gap_abs": prior_three_gap_abs,
        "company_intro": str(seed.get("company_intro", "")),
        "industry": str(seed.get("industry", "")),
        "concepts": [str(value) for value in seed.get("concepts", [])],
        "date": live_date,
        "eligible": True,
        "selected": selected,
        "entry_breakout_high_5": float(
            seed.get("next_breakout_high_5", 0.0) or 0.0
        ),
    }
    return decorate_row(row, cfg) if "line_gap_max_abs" in cfg else row


def build_live_pools(
    payload: dict,
    quotes: dict[str, dict],
    excluded_codes: set[str] | None = None,
) -> dict:
    seeds = live_seeds(payload)
    if not seeds:
        return {
            FIRST_TIER: [],
            SECOND_TIER: [],
            THIRD_TIER: [],
            "main": [],
            "secondary": [],
            "available": False,
        }
    cfg = payload.get("config", {})
    close_trade_date = str(payload.get("trade_date", ""))
    rows = []
    for seed in seeds:
        quote = quotes.get(str(seed.get("code", "")))
        if quote is None:
            continue
        row = evaluate_live_seed(seed, quote, cfg, close_trade_date)
        if row is not None:
            rows.append(row)
    excluded = excluded_codes or set()
    rows = [row for row in rows if row["code"] not in excluded]
    if "line_gap_max_abs" in cfg:
        tiers = split_tiers(rows, cfg)
        return {
            FIRST_TIER: tiers[FIRST_TIER],
            SECOND_TIER: tiers[SECOND_TIER],
            THIRD_TIER: tiers[THIRD_TIER],
            "main": tiers[FIRST_TIER],
            "secondary": tiers[SECOND_TIER],
            "available": True,
        }
    main = [row for row in rows if row["selected"]]
    secondary = [
        row
        for row in rows
        if not row["selected"]
        and row["cross_ok"]
        and row["yellow_ok"]
        and (row["bottom_ok"] or row["limit_up_ok"])
    ]
    sort_key = lambda row: (
        row["matched_count"],
        row["cross_ok"],
        row["bottom_ok"],
        row["limit_up_ok"],
        row["yellow_count"],
        row["change_pct"],
    )
    main.sort(key=sort_key, reverse=True)
    secondary.sort(key=sort_key, reverse=True)
    return {"main": main, "secondary": secondary, "available": True}


def build_live_payload(payload: dict, now: datetime | None = None) -> dict:
    local_now = now or datetime.now(SHANGHAI)
    targets = collect_targets(payload)
    label, note = market_state(local_now)
    quotes, source, host = fetch_quotes(targets)
    live_dates = sorted(
        {
            str(item.get("server_time", ""))[:10]
            for item in quotes.values()
            if len(str(item.get("server_time", ""))) >= 10
        }
    )
    live_trade_date = live_dates[-1] if live_dates else ""
    live_tracking = build_live_tracking(
        payload,
        quotes,
        live_trade_date=live_trade_date,
    )
    live_pools = build_live_pools(payload, quotes, set())
    stored_history = load_history(HISTORY_PATH)
    history_changed = False
    if live_trade_date:
        stored_history, history_changed = record_intraday_pools(
            stored_history,
            live_trade_date,
            live_pools,
            quotes,
            local_now.isoformat(timespec="seconds"),
        )
    history = refresh_history(
        stored_history,
        quotes,
        live_trade_date or str(payload.get("trade_date", "")),
        local_now.isoformat(timespec="seconds"),
    )
    quote_times = [
        datetime.fromisoformat(str(item["server_time"]))
        for item in quotes.values()
        if "T" in str(item.get("server_time", ""))
    ]
    latest_quote_time = max(quote_times) if quote_times else None
    quote_age_seconds = (
        max(0, int((local_now - latest_quote_time).total_seconds()))
        if latest_quote_time
        else None
    )
    stale = not bool(quotes) or (
        label == "盘中行情"
        and quote_age_seconds is not None
        and quote_age_seconds > 600
    )
    display_codes = {
        item["code"]
        for item in (
            list(live_pools.get("main", []))
            + list(live_pools.get("secondary", []))
            + list(live_pools.get(THIRD_TIER, []))
        )
    }
    display_codes.update(
        item["code"]
        for item in collect_display_targets(payload)
    )
    display_quotes = {
        code: quote
        for code, quote in quotes.items()
        if code in display_codes
    }
    selection_mode = (
        "intraday"
        if live_trade_date and live_trade_date > str(payload.get("trade_date", ""))
        else "close"
    )
    return {
        "generated_at": local_now.isoformat(timespec="seconds"),
        "generated_at_display": local_now.strftime("%Y-%m-%d %H:%M:%S"),
        "market_label": label,
        "note": note,
        "is_stale": stale,
        "source": source,
        "source_host": host,
        "latest_quote_time": (
            latest_quote_time.isoformat(timespec="seconds")
            if latest_quote_time
            else ""
        ),
        "quote_age_seconds": quote_age_seconds,
        "close_trade_date": str(payload.get("trade_date", "")),
        "live_trade_date": live_trade_date,
        "selection_mode": selection_mode,
        "live_pools": live_pools,
        "history": history,
        "live_tracking": live_tracking,
        "tracking_codes": collect_tracking_codes(payload, live_tracking),
        "target_count": len(targets),
        "quote_count": len(quotes),
        "quotes": display_quotes,
        "_history_changed": history_changed,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="卢氏龙虎趋势池盘中行情刷新")
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        payload = json.loads(args.result.read_text(encoding="utf-8"))
        live = build_live_payload(payload)
        from company_metadata import enrich_live_pools

        metadata_errors = enrich_live_pools(live.get("live_pools", {}))
        if metadata_errors:
            print(
                f"公司资料补充失败 {len(metadata_errors)} 只，已优先使用本地缓存",
                flush=True,
            )
        history_changed = bool(live.pop("_history_changed", False))
        if history_changed:
            write_history(HISTORY_PATH, live["history"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(live, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"盘中行情完成：目标 {live['target_count']} 只，"
            f"成功 {live['quote_count']} 只，时间 {live['generated_at_display']}"
        )
        return 0
    except Exception as exc:
        print(f"盘中行情失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
