from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Sequence

from rolling_validation import (
    ExecutionAssumptions,
    completed_trade_date,
    execution_assumptions,
    fetch_histories,
    replay_signals,
    research_meta,
    truncate_histories,
)
from screener import Bar, Stock, cached_universe, is_st_name, load_config
from strategy_contract import (
    EXECUTION_SCOPE,
    FROZEN_CANDIDATE_ID,
    LIVE_STRATEGY_ID,
    strategy_contract,
)
from signal_window_optimization import (
    COMMON_FUTURE_BARS,
    CROSS_LOOKBACK_DAYS,
    ENTRY_METHODS,
    EXIT_RULES,
    FORWARD_SELECTION_POLICY,
    YELLOW_AFTER_DAYS,
    YELLOW_BEFORE_DAYS,
    entry_for_method,
    joint_trade_for_setup,
    signal_indices,
    stats,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "results" / "strategy_portfolio_validation.json"
DEFAULT_CANDIDATES = (
    FROZEN_CANDIDATE_ID,
    "low_risk_2__wave_erasure_hybrid_or_8_3_weakening",
    "low_risk_2__wave_erasure_trail_10_10",
    "break_5day_high__trail_3_2",
)
MAX_POSITIONS = (5, 10, 20)
FIXED_ORDER_SEEDS = (11, 29, 47, 71, 101, 149, 211)
INITIAL_CAPITAL = 1_000_000.0


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    entry_method: dict
    exit_rule: dict


@dataclass(frozen=True)
class TradeRecord:
    candidate_id: str
    code: str
    name: str
    area: str
    setup_date: str
    entry_date: str
    exit_date: str | None
    entry_raw_price: float
    entry_effective_price: float
    exit_raw_price: float | None
    exit_effective_price: float | None
    return_pct: float | None
    holding_bars: int | None
    mature_sample: bool = True

    @property
    def is_completed(self) -> bool:
        return (
            self.exit_date is not None
            and self.exit_raw_price is not None
            and self.exit_effective_price is not None
            and self.return_pct is not None
            and self.holding_bars is not None
        )

    @property
    def uid(self) -> str:
        return "|".join(
            (
                self.candidate_id,
                self.code,
                self.setup_date,
                self.entry_date,
                self.exit_date or "OPEN",
            )
        )


@dataclass
class Position:
    trade_uid: str
    code: str
    units: float
    invested_cash: float
    entry_date: str
    exit_date: str | None


def parse_candidate_ids(raw: str | None) -> list[str]:
    values = [value.strip() for value in (raw or "").split(",") if value.strip()]
    if not values:
        values = list(DEFAULT_CANDIDATES)
    return list(dict.fromkeys(values))


def resolve_candidates(candidate_ids: Sequence[str]) -> list[Candidate]:
    entries = {str(item["id"]): item for item in ENTRY_METHODS}
    exits = {str(item["id"]): item for item in EXIT_RULES}
    resolved: list[Candidate] = []
    for candidate_id in candidate_ids:
        if "__" not in candidate_id:
            raise ValueError(f"候选ID必须为 买点ID__卖点ID: {candidate_id}")
        entry_id, exit_id = candidate_id.split("__", 1)
        if entry_id not in entries:
            raise ValueError(f"未知买点ID: {entry_id}")
        if exit_id not in exits:
            raise ValueError(f"未知卖点ID: {exit_id}")
        resolved.append(Candidate(candidate_id, entries[entry_id], exits[exit_id]))
    return resolved


def variable_cost_bps(assumptions: ExecutionAssumptions) -> float:
    """Costs that a broker/slippage stress scenario is allowed to scale."""
    return assumptions.commission_bps_per_side + assumptions.slippage_bps_per_side


def cost_scenario(
    assumptions: ExecutionAssumptions,
    multiplier: float,
) -> dict:
    if multiplier < 0:
        raise ValueError("cost multiplier 不得小于0")
    variable = variable_cost_bps(assumptions) * multiplier
    fixed_each_side = (
        assumptions.exchange_fee_bps_per_side
        + assumptions.regulatory_fee_bps_per_side
    )
    buy_bps = fixed_each_side + variable
    sell_bps = fixed_each_side + variable + assumptions.stamp_duty_bps_sell
    return {
        "multiplier": float(multiplier),
        "buy_cost_bps": float(buy_bps),
        "sell_cost_bps": float(sell_bps),
        "scaled_components": "broker commission and slippage only",
        "unscaled_components": "exchange fee, regulatory fee and sell-side stamp duty",
    }


def reprice_trade(
    trade: TradeRecord,
    assumptions: ExecutionAssumptions,
    multiplier: float,
) -> tuple[float, float, float]:
    if not trade.is_completed:
        raise ValueError("未结束持仓不能按完整交易重计收益")
    scenario = cost_scenario(assumptions, multiplier)
    entry_effective = trade.entry_raw_price * (
        1.0 + float(scenario["buy_cost_bps"]) / 10_000.0
    )
    exit_effective = float(trade.exit_raw_price) * (
        1.0 - float(scenario["sell_cost_bps"]) / 10_000.0
    )
    return (
        entry_effective,
        exit_effective,
        (exit_effective / entry_effective - 1.0) * 100.0,
    )


def scenario_key(multiplier: float) -> str:
    text = f"{multiplier:g}".replace(".", "_")
    return f"cost_{text}x"


def collect_candidate_trades(
    cfg: dict,
    histories: Sequence[tuple[Stock, list[Bar]]],
    candidates: Sequence[Candidate],
    assumptions: ExecutionAssumptions,
    *,
    cutoff: str | None = None,
) -> tuple[dict[str, list[TradeRecord]], dict, dict[str, list[Bar]], list[str]]:
    """Replay causal entries without conditioning admission on a future exit.

    Mature completed records feed the comparable single-trade statistics. Every
    filled entry, including a recent tail entry or an exit that remains blocked
    through the cutoff, feeds the portfolio curve and occupies capacity until it
    is actually sold.
    """
    result = {candidate.candidate_id: [] for candidate in candidates}
    diagnostics = {
        "formal_setup_detected_count": 0,
        "formal_setup_count": 0,
        "formal_setup_by_area": {"main": 0, "secondary": 0},
        "candidate_entry_count": {candidate.candidate_id: 0 for candidate in candidates},
        "candidate_completed_trade_count": {
            candidate.candidate_id: 0 for candidate in candidates
        },
        "candidate_portfolio_entry_count": {
            candidate.candidate_id: 0 for candidate in candidates
        },
        "candidate_portfolio_completed_at_cutoff_count": {
            candidate.candidate_id: 0 for candidate in candidates
        },
        "candidate_portfolio_open_at_cutoff_count": {
            candidate.candidate_id: 0 for candidate in candidates
        },
        "unmatured_tail_setup_count": 0,
    }
    bars_by_code: dict[str, list[Bar]] = {}
    calendar: set[str] = set()
    minimum_history = int(cfg["minimum_history_bars"])

    for stock_number, (stock, bars) in enumerate(histories, start=1):
        if cutoff is not None:
            bars = [bar for bar in bars if bar.date <= cutoff]
        if bars:
            bars_by_code[stock.code] = bars
            calendar.update(bar.date for bar in bars)
        if len(bars) < minimum_history:
            continue
        points = replay_signals(
            stock,
            bars,
            cfg,
            mode="causal",
            yellow_before_days=YELLOW_BEFORE_DAYS,
            yellow_after_days=YELLOW_AFTER_DAYS,
            cross_lookback_days=CROSS_LOOKBACK_DAYS,
        )
        for setup_index in signal_indices(points, "pool"):
            area = str(points[setup_index].area)
            if area not in {"main", "secondary"}:
                continue
            diagnostics["formal_setup_detected_count"] += 1
            mature_sample = setup_index + COMMON_FUTURE_BARS < len(points)
            if not mature_sample:
                diagnostics["unmatured_tail_setup_count"] += 1
            else:
                diagnostics["formal_setup_count"] += 1
                diagnostics["formal_setup_by_area"][area] += 1

            entry_cache: dict[str, tuple[int, float, int, float] | None] = {}
            for candidate in candidates:
                entry_id = str(candidate.entry_method["id"])
                if entry_id not in entry_cache:
                    entry_cache[entry_id] = entry_for_method(
                        points,
                        bars,
                        setup_index,
                        candidate.entry_method,
                        stock=stock,
                        execution=assumptions,
                        include_trigger=True,
                    )
                entry = entry_cache[entry_id]
                if entry is None:
                    continue
                diagnostics["candidate_portfolio_entry_count"][
                    candidate.candidate_id
                ] += 1
                if mature_sample:
                    diagnostics["candidate_entry_count"][candidate.candidate_id] += 1
                trade = joint_trade_for_setup(
                    stock,
                    bars,
                    points,
                    setup_index,
                    candidate.entry_method,
                    candidate.exit_rule,
                    assumptions,
                    entry_result=entry,
                )
                if trade is None:
                    entry_index, entry_effective, _, entry_raw = entry
                    record = TradeRecord(
                        candidate_id=candidate.candidate_id,
                        code=stock.code,
                        name=stock.name,
                        area=area,
                        setup_date=bars[setup_index].date,
                        entry_date=bars[int(entry_index)].date,
                        exit_date=None,
                        entry_raw_price=float(entry_raw),
                        entry_effective_price=float(entry_effective),
                        exit_raw_price=None,
                        exit_effective_price=None,
                        return_pct=None,
                        holding_bars=None,
                        mature_sample=mature_sample,
                    )
                    diagnostics["candidate_portfolio_open_at_cutoff_count"][
                        candidate.candidate_id
                    ] += 1
                else:
                    entry_index = int(trade["entry_index"])
                    exit_index = int(trade["exit_index"])
                    record = TradeRecord(
                        candidate_id=candidate.candidate_id,
                        code=stock.code,
                        name=stock.name,
                        area=area,
                        setup_date=bars[setup_index].date,
                        entry_date=bars[entry_index].date,
                        exit_date=bars[exit_index].date,
                        entry_raw_price=float(trade["entry_raw_price"]),
                        entry_effective_price=float(trade["entry_effective_price"]),
                        exit_raw_price=float(trade["exit_raw_price"]),
                        exit_effective_price=float(trade["exit_effective_price"]),
                        return_pct=float(trade["return_pct"]),
                        holding_bars=int(trade["holding_bars"]),
                        mature_sample=mature_sample,
                    )
                    diagnostics["candidate_portfolio_completed_at_cutoff_count"][
                        candidate.candidate_id
                    ] += 1
                    if mature_sample:
                        diagnostics["candidate_completed_trade_count"][
                            candidate.candidate_id
                        ] += 1
                result[candidate.candidate_id].append(record)
        if stock_number % 250 == 0:
            print(
                f"组合候选逐笔回放: {stock_number}/{len(histories)}，"
                f"正式信号 {diagnostics['formal_setup_count']} 次",
                flush=True,
            )

    for candidate_id, records in result.items():
        causal_keys: set[tuple[str, str, str]] = set()
        for record in records:
            causal_key = (record.code, record.setup_date, record.entry_date)
            if causal_key in causal_keys:
                raise RuntimeError(
                    "组合出现重复因果入场键: "
                    f"{candidate_id} {'|'.join(causal_key)}"
                )
            causal_keys.add(causal_key)
        records.sort(
            key=lambda item: (
                item.entry_date,
                item.code,
                item.setup_date,
            )
        )
    return result, diagnostics, bars_by_code, sorted(calendar)


def _period_trade_filter(trade: TradeRecord, period: str) -> bool:
    if not trade.is_completed:
        return False
    exit_date = str(trade.exit_date)
    if period == "overall":
        return True
    if period == "development":
        return trade.entry_date < "2024-01-01" and exit_date < "2024-01-01"
    if period == "validation":
        return trade.entry_date >= "2024-01-01" and exit_date < "2026-01-01"
    if period == "holdout_2026":
        return trade.entry_date >= "2026-01-01" and exit_date >= "2026-01-01"
    raise ValueError(f"未知逐笔分期: {period}")


def candidate_trade_statistics(
    trades: Sequence[TradeRecord],
    assumptions: ExecutionAssumptions,
    multiplier: float,
) -> dict:
    completed = [
        trade for trade in trades if trade.mature_sample and trade.is_completed
    ]
    priced = {
        trade.uid: reprice_trade(trade, assumptions, multiplier)[2]
        for trade in completed
    }
    output: dict[str, dict] = {}
    for area in ("combined", "main", "secondary"):
        area_trades = [
            trade for trade in completed if area == "combined" or trade.area == area
        ]
        area_result: dict[str, dict] = {}
        for period in ("overall", "development", "validation", "holdout_2026"):
            period_trades = [
                trade for trade in area_trades if _period_trade_filter(trade, period)
            ]
            area_result[period] = stats(
                [priced[trade.uid] for trade in period_trades],
            [int(trade.holding_bars) for trade in period_trades],
            )
        area_result["cross_boundary_excluded_count"] = len(area_trades) - sum(
            int(area_result[period]["sample_count"])
            for period in ("development", "validation", "holdout_2026")
        )
        output[area] = area_result
    return output


def trades_for_execution_scope(
    trades: Sequence[TradeRecord],
    scope: str = EXECUTION_SCOPE,
) -> list[TradeRecord]:
    if scope == "combined":
        return list(trades)
    if scope not in {"main", "secondary"}:
        raise ValueError(f"未知组合执行范围: {scope}")
    return [trade for trade in trades if trade.area == scope]


def stable_order_key(seed: int, trade: TradeRecord) -> str:
    # Capacity priority must only use fields known when the entry order exists.
    # Excluding candidate_id also guarantees that exit-rule comparators receive
    # the same same-day stock ordering when their entry signals are identical.
    payload = "|".join(
        (str(seed), trade.code, trade.setup_date, trade.entry_date)
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def market_updates(
    bars_by_code: dict[str, list[Bar]],
    codes: set[str],
) -> dict[str, dict[str, float]]:
    updates: dict[str, dict[str, float]] = {}
    for code in sorted(codes):
        for bar in bars_by_code.get(code, []):
            updates.setdefault(bar.date, {})[code] = float(bar.close)
    return updates


def _drawdown_metrics(points: Sequence[dict]) -> dict:
    if not points:
        return {
            "max_drawdown_pct": 0.0,
            "drawdown_peak_date": "",
            "drawdown_trough_date": "",
        }
    peak_value = float(points[0]["equity"])
    peak_date = str(points[0]["date"])
    worst = 0.0
    worst_peak = peak_date
    worst_trough = peak_date
    for point in points[1:]:
        equity = float(point["equity"])
        point_date = str(point["date"])
        if equity > peak_value:
            peak_value = equity
            peak_date = point_date
        drawdown = (equity / peak_value - 1.0) * 100.0 if peak_value else 0.0
        if drawdown < worst:
            worst = drawdown
            worst_peak = peak_date
            worst_trough = point_date
    return {
        "max_drawdown_pct": round(worst, 4),
        "drawdown_peak_date": worst_peak,
        "drawdown_trough_date": worst_trough,
    }


def _curve_metrics(points: Sequence[dict]) -> dict:
    if len(points) < 2:
        return {
            "available": False,
            "start_date": str(points[0]["date"]) if points else "",
            "end_date": str(points[-1]["date"]) if points else "",
            "start_equity": round(float(points[0]["equity"]), 4) if points else 0.0,
            "end_equity": round(float(points[-1]["equity"]), 4) if points else 0.0,
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            **_drawdown_metrics(points),
        }
    start = points[0]
    end = points[-1]
    start_equity = float(start["equity"])
    end_equity = float(end["equity"])
    total_return = (end_equity / start_equity - 1.0) if start_equity else 0.0
    elapsed_days = max(
        0,
        (date.fromisoformat(str(end["date"])) - date.fromisoformat(str(start["date"]))).days,
    )
    cagr = (
        math.pow(end_equity / start_equity, 365.2425 / elapsed_days) - 1.0
        if elapsed_days > 0 and start_equity > 0 and end_equity > 0
        else 0.0
    )
    return {
        "available": True,
        "start_date": str(start["date"]),
        "end_date": str(end["date"]),
        "start_equity": round(start_equity, 4),
        "end_equity": round(end_equity, 4),
        "total_return_pct": round(total_return * 100.0, 4),
        "cagr_pct": round(cagr * 100.0, 4),
        **_drawdown_metrics(points),
    }


def _curve_through(points: Sequence[dict], boundary: str) -> list[dict]:
    return [point for point in points if str(point["date"]) <= boundary]


def _curve_after_boundary(
    points: Sequence[dict],
    boundary: str,
    end_boundary: str,
) -> list[dict]:
    before = _curve_through(points, boundary)
    if not before:
        return []
    baseline = before[-1]
    return [baseline] + [
        point
        for point in points
        if boundary < str(point["date"]) <= end_boundary
    ]


def portfolio_period_metrics(points: Sequence[dict], cutoff: str) -> dict:
    """Slice one precomputed equity curve; never revalue a prior boundary."""
    development = _curve_through(points, "2023-12-31")
    validation = _curve_after_boundary(points, "2023-12-31", "2025-12-31")
    holdout = _curve_after_boundary(points, "2025-12-31", cutoff)
    return {
        "overall": _curve_metrics(points),
        "development": _curve_metrics(development),
        "validation": _curve_metrics(validation),
        "holdout_2026": _curve_metrics(holdout),
        "boundary_policy": (
            "All periods are slices of one continuous marked-to-market curve. "
            "Open positions use the last close on or before each boundary."
        ),
    }


def simulate_portfolio(
    trades: Sequence[TradeRecord],
    bars_by_code: dict[str, list[Bar]],
    calendar: Sequence[str],
    assumptions: ExecutionAssumptions,
    *,
    max_positions: int,
    seed: int,
    cutoff: str,
    cost_multiplier: float = 1.0,
    initial_capital: float = INITIAL_CAPITAL,
    include_curve: bool = False,
    close_updates: dict[str, dict[str, float]] | None = None,
) -> dict:
    if max_positions <= 0:
        raise ValueError("max_positions 必须大于0")
    eligible = [trade for trade in trades if trade.entry_date <= cutoff]
    entry_events: dict[str, list[TradeRecord]] = {}
    exit_events: dict[str, list[TradeRecord]] = {}
    prices: dict[str, tuple[float, float | None, float | None]] = {}
    for trade in eligible:
        scenario = cost_scenario(assumptions, cost_multiplier)
        entry_effective = trade.entry_raw_price * (
            1.0 + float(scenario["buy_cost_bps"]) / 10_000.0
        )
        if trade.is_completed:
            prices[trade.uid] = reprice_trade(
                trade,
                assumptions,
                cost_multiplier,
            )
        else:
            prices[trade.uid] = (entry_effective, None, None)
        entry_events.setdefault(trade.entry_date, []).append(trade)
        if trade.is_completed:
            exit_events.setdefault(str(trade.exit_date), []).append(trade)
    for same_day in entry_events.values():
        same_day.sort(key=lambda trade: stable_order_key(seed, trade))
    for same_day in exit_events.values():
        same_day.sort(key=lambda trade: trade.uid)

    relevant_codes = {trade.code for trade in eligible}
    updates = (
        close_updates
        if close_updates is not None
        else market_updates(bars_by_code, relevant_codes)
    )
    available_dates = [value for value in calendar if value <= cutoff]
    if available_dates:
        baseline_date = (
            date.fromisoformat(available_dates[0]) - timedelta(days=1)
        ).isoformat()
    elif eligible:
        baseline_date = (
            date.fromisoformat(min(trade.entry_date for trade in eligible))
            - timedelta(days=1)
        ).isoformat()
    else:
        baseline_date = cutoff

    positions: dict[str, Position] = {}
    last_close: dict[str, float] = {}
    cash = float(initial_capital)
    accepted = 0
    completed = 0
    wins = 0
    capacity_rejections = 0
    overlapping_stock_rejections = 0
    cash_rejections = 0
    accepted_ids: list[str] = []
    curve: list[dict] = [
        {
            "date": baseline_date,
            "equity": float(initial_capital),
            "exposure_pct": 0.0,
            "holdings": 0,
        }
    ]

    loop_dates = available_dates
    for current_date in loop_dates:
        # Exit at the open first. This releases a slot and cash for an entry at
        # the same open without leverage or an artificial one-day delay.
        for trade in exit_events.get(current_date, []):
            position = positions.get(trade.code)
            if position is None or position.trade_uid != trade.uid:
                continue
            _, exit_effective, trade_return = prices[trade.uid]
            if exit_effective is None or trade_return is None:
                raise RuntimeError("未结束持仓不能进入卖出事件")
            cash += position.units * exit_effective
            completed += 1
            wins += int(trade_return > 0.0)
            del positions[trade.code]

        marked_before_entries = sum(
            position.units
            * last_close.get(code, prices[position.trade_uid][0])
            for code, position in positions.items()
        )
        equity_before_entries = cash + marked_before_entries
        slot_cash = equity_before_entries / max_positions

        for trade in entry_events.get(current_date, []):
            if trade.code in positions:
                overlapping_stock_rejections += 1
                continue
            if len(positions) >= max_positions:
                capacity_rejections += 1
                continue
            allocation = min(slot_cash, cash)
            if allocation <= 1e-9:
                cash_rejections += 1
                continue
            entry_effective, _, _ = prices[trade.uid]
            positions[trade.code] = Position(
                trade_uid=trade.uid,
                code=trade.code,
                units=allocation / entry_effective,
                invested_cash=allocation,
                entry_date=trade.entry_date,
                exit_date=trade.exit_date,
            )
            cash -= allocation
            accepted += 1
            accepted_ids.append(trade.uid)

        # Closing marks become known only after all open-price events and
        # position sizing have completed, preventing same-day close lookahead.
        last_close.update(updates.get(current_date, {}))
        marked_value = sum(
            position.units
            * last_close.get(code, prices[position.trade_uid][0])
            for code, position in positions.items()
        )
        equity = cash + marked_value
        curve.append(
            {
                "date": current_date,
                "equity": equity,
                "exposure_pct": (marked_value / equity * 100.0) if equity else 0.0,
                "holdings": len(positions),
            }
        )

    period_metrics = portfolio_period_metrics(curve, cutoff)
    accepted_fingerprint = hashlib.sha256(
        "\n".join(accepted_ids).encode("utf-8")
    ).hexdigest()
    result = {
        "seed": seed,
        "max_positions": max_positions,
        "cost_multiplier": cost_multiplier,
        "accepted_entries": accepted,
        "completed_trades": completed,
        "wins": wins,
        "win_rate_pct": round(wins / completed * 100.0, 2) if completed else 0.0,
        "open_positions_at_cutoff": len(positions),
        "open_position_market_value_at_cutoff": round(
            sum(
                position.units
                * last_close.get(code, prices[position.trade_uid][0])
                for code, position in positions.items()
            ),
            4,
        ),
        "capacity_rejections": capacity_rejections,
        "overlapping_stock_rejections": overlapping_stock_rejections,
        "cash_rejections": cash_rejections,
        "accepted_trade_fingerprint": accepted_fingerprint,
        "average_exposure_pct": round(
            statistics.fmean(float(point["exposure_pct"]) for point in curve), 4
        ),
        "max_exposure_pct": round(
            max(float(point["exposure_pct"]) for point in curve), 4
        ),
        "average_holdings": round(
            statistics.fmean(int(point["holdings"]) for point in curve), 4
        ),
        "max_holdings": max(int(point["holdings"]) for point in curve),
        "periods": period_metrics,
    }
    if include_curve:
        result["equity_curve"] = curve
    return result


def seed_summary(runs: Sequence[dict]) -> dict:
    ordered = sorted(
        runs,
        key=lambda run: (
            float(run["periods"]["overall"]["total_return_pct"]),
            int(run["seed"]),
        ),
    )
    if not ordered:
        return {}
    median = ordered[len(ordered) // 2]
    compact_keys = (
        "seed",
        "accepted_entries",
        "completed_trades",
        "wins",
        "win_rate_pct",
        "open_positions_at_cutoff",
        "open_position_market_value_at_cutoff",
        "capacity_rejections",
        "overlapping_stock_rejections",
        "average_exposure_pct",
        "max_exposure_pct",
        "average_holdings",
        "max_holdings",
        "accepted_trade_fingerprint",
        "periods",
    )

    def compact(run: dict) -> dict:
        return {key: run[key] for key in compact_keys}

    totals = [float(run["periods"]["overall"]["total_return_pct"]) for run in ordered]
    cagrs = [float(run["periods"]["overall"]["cagr_pct"]) for run in ordered]
    return {
        "ranking_metric": "overall total_return_pct",
        "worst": compact(ordered[0]),
        "median": compact(median),
        "best": compact(ordered[-1]),
        "total_return_range_pct": round(max(totals) - min(totals), 4),
        "cagr_range_pct": round(max(cagrs) - min(cagrs), 4),
    }


def trade_payload(
    trade: TradeRecord,
    assumptions: ExecutionAssumptions,
    multipliers: Sequence[float],
) -> dict:
    payload = asdict(trade)
    payload["is_completed"] = trade.is_completed
    scenarios: dict[str, dict] = {}
    for multiplier in multipliers:
        cost = cost_scenario(assumptions, multiplier)
        entry_effective = trade.entry_raw_price * (
            1.0 + float(cost["buy_cost_bps"]) / 10_000.0
        )
        if trade.is_completed:
            _, exit_effective, return_pct = reprice_trade(
                trade,
                assumptions,
                multiplier,
            )
        else:
            exit_effective = None
            return_pct = None
        scenarios[scenario_key(multiplier)] = {
            "entry_effective_price": round(entry_effective, 6),
            "exit_effective_price": (
                round(exit_effective, 6) if exit_effective is not None else None
            ),
            "return_pct": round(return_pct, 6) if return_pct is not None else None,
        }
    payload["cost_scenarios"] = scenarios
    return payload


def build_report(
    cfg: dict,
    histories: Sequence[tuple[Stock, list[Bar]]],
    errors: Sequence[str],
    requested_bars: int,
    cutoff: str,
    candidates: Sequence[Candidate],
    assumptions: ExecutionAssumptions,
    cost_multipliers: Sequence[float],
    *,
    include_trades: bool = True,
) -> dict:
    trades_by_candidate, diagnostics, bars_by_code, calendar = collect_candidate_trades(
        cfg,
        histories,
        candidates,
        assumptions,
        cutoff=cutoff,
    )
    meta = research_meta(cfg, cutoff, assumptions)
    live_contract = strategy_contract()
    meta.update(
        {
            "schema_version": 1,
            "requested_bars": requested_bars,
            "analyzed_stock_count": len(histories),
            "error_count": len(errors),
            "live_strategy_id": LIVE_STRATEGY_ID,
            "frozen_candidate_id": FROZEN_CANDIDATE_ID,
            "execution_scope": EXECUTION_SCOPE,
            "live_strategy_contract": live_contract,
            "selection_policy": FORWARD_SELECTION_POLICY,
            "forward_evaluation": {
                "historical_2026_is_blind_holdout": False,
                "starts_strictly_after_completed_trade_date": cutoff,
                "definition": (
                    "2026历史结果已被反复查看；只有本次冻结之后新产生且此前未见的"
                    "交易日，才计为真正forward。"
                ),
                "period_key_semantics": {
                    "holdout_2026": (
                        "历史兼容字段名，展示时必须称为2026历史观察段；"
                        "它不是盲测或未见留出集"
                    )
                },
            },
            "cost_scenarios": {
                scenario_key(multiplier): cost_scenario(assumptions, multiplier)
                for multiplier in cost_multipliers
            },
            "portfolio_policy": {
                "initial_capital": INITIAL_CAPITAL,
                "max_positions": list(MAX_POSITIONS),
                "execution_scope": EXECUTION_SCOPE,
                "scope_note": (
                    "正式组合净值只使用次选来源交易；主选仅保留coverage观察，"
                    "不参与正式实盘策略绩效。"
                ),
                "same_day_event_order": "exits before entries",
                "position_sizing": (
                    "cash plus open positions marked at their latest available "
                    "close before that open, divided by max_positions"
                ),
                "constraints": [
                    "no leverage",
                    "one open position per stock",
                    "capacity-rejected entries are never retried",
                ],
                "entry_priority": (
                    "stable SHA256(code, setup, entry, fixed seed), using only "
                    "information known at entry and shared across exit comparators; "
                    "report worst/median/best across fixed seeds"
                ),
                "entry_priority_fields": [
                    "fixed_seed",
                    "code",
                    "setup_date",
                    "entry_date",
                ],
                "entry_priority_uses_future_information": False,
                "entry_priority_shared_across_exit_comparators": True,
                "trade_statistics_maturity_future_bars": COMMON_FUTURE_BARS,
                "portfolio_includes_all_filled_entries_through_cutoff": True,
                "portfolio_entry_admission_independent_of_future_exit": True,
                "portfolio_keeps_unexited_positions_open_at_cutoff": True,
                "marking": "daily raw close; carry last close through suspension",
                "periods": (
                    "one continuous curve, with open positions marked at the last "
                    "close on or before 2023-12-31 and 2025-12-31"
                ),
                "sample_completion": (
                    f"single-trade statistics require {COMMON_FUTURE_BARS} subsequent "
                    "bars, matching the joint candidate comparison; the portfolio "
                    "curve instead admits every filled entry through the cutoff and "
                    "keeps an untriggered or unfilled exit open and marked to market"
                ),
                "reported_scopes": ["combined", "main", "secondary"],
                "official_portfolio_scope": EXECUTION_SCOPE,
            },
        }
    )
    report_candidates: dict[str, dict] = {}
    for candidate in candidates:
        candidate_id = candidate.candidate_id
        trades = trades_by_candidate[candidate_id]
        mature_completed = [
            trade
            for trade in trades
            if trade.mature_sample and trade.is_completed
        ]
        scoped_mature_completed = trades_for_execution_scope(mature_completed)
        scenario_outputs: dict[str, dict] = {}
        relevant_bars = {
            code: bars_by_code[code]
            for code in {trade.code for trade in trades}
            if code in bars_by_code
        }
        relevant_codes = {trade.code for trade in trades}
        close_updates = market_updates(relevant_bars, relevant_codes)
        for multiplier in cost_multipliers:
            key = scenario_key(multiplier)
            trades_by_scope = {
                "combined": trades,
                "main": [trade for trade in trades if trade.area == "main"],
                "secondary": trades_for_execution_scope(trades),
            }
            portfolio_scopes: dict[str, dict] = {}
            for scope, scoped_trades in trades_by_scope.items():
                slot_outputs: dict[str, dict] = {}
                for max_positions in MAX_POSITIONS:
                    runs = [
                        simulate_portfolio(
                            scoped_trades,
                            relevant_bars,
                            calendar,
                            assumptions,
                            max_positions=max_positions,
                            seed=seed,
                            cutoff=cutoff,
                            cost_multiplier=multiplier,
                            close_updates=close_updates,
                        )
                        for seed in FIXED_ORDER_SEEDS
                    ]
                    slot_outputs[str(max_positions)] = {
                        "runs": runs,
                        "seed_summary": seed_summary(runs),
                    }
                portfolio_scopes[scope] = slot_outputs
            scenario_outputs[key] = {
                "trade_statistics": candidate_trade_statistics(
                    trades,
                    assumptions,
                    multiplier,
                ),
                "portfolios": portfolio_scopes[EXECUTION_SCOPE],
                "portfolios_by_area": portfolio_scopes,
            }
        candidate_payload = {
            "entry_method": dict(candidate.entry_method),
            "exit_rule": dict(candidate.exit_rule),
            "completed_trade_count": len(mature_completed),
            "execution_scope": EXECUTION_SCOPE,
            "execution_scope_completed_trade_count": len(scoped_mature_completed),
            "portfolio_entry_opportunity_count": len(trades),
            "portfolio_completed_exit_count": sum(
                trade.is_completed for trade in trades
            ),
            "portfolio_open_before_capacity_count": sum(
                not trade.is_completed for trade in trades
            ),
            "scenarios": scenario_outputs,
            "trades_omitted": not include_trades,
        }
        if include_trades:
            candidate_payload["trades"] = [
                trade_payload(trade, assumptions, cost_multipliers) for trade in trades
            ]
        report_candidates[candidate_id] = candidate_payload
    return {
        "meta": meta,
        "diagnostics": diagnostics,
        "errors": list(errors),
        "candidates": report_candidates,
    }


def parse_cost_multipliers(values: Sequence[float] | None) -> list[float]:
    # Base and double commission/slippage stress are always present. Repeated
    # CLI values can add another sensitivity point without another data fetch.
    multipliers = [1.0, 2.0, *(values or [])]
    if any(value < 0 for value in multipliers):
        raise ValueError("--cost-multiplier 不得小于0")
    return sorted(set(float(value) for value in multipliers))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="候选买卖策略的全A股连续净值与等槽位容量验证"
    )
    parser.add_argument(
        "--candidates",
        default=",".join(DEFAULT_CANDIDATES),
        help="候选ID，逗号分隔，格式为 买点ID__卖点ID",
    )
    parser.add_argument("--bars", type=int, default=1600)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--completed-trade-date")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--omit-trades",
        action="store_true",
        help="正式发布文件不保存逐笔明细，只保留逐笔汇总和组合指标",
    )
    parser.add_argument(
        "--cost-multiplier",
        type=float,
        action="append",
        help="额外的佣金+滑点倍数；默认仍会同时输出1倍和2倍",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.bars < 200:
        parser.error("--bars 至少为200")

    candidates = resolve_candidates(parse_candidate_ids(args.candidates))
    cost_multipliers = parse_cost_multipliers(args.cost_multiplier)
    cfg = load_config(ROOT / "config.json")
    cfg["yellow_consecutive_days"] = 1
    assumptions = execution_assumptions(cfg)
    cutoff = args.completed_trade_date or completed_trade_date(ROOT)
    universe = [stock for stock in cached_universe() if not is_st_name(stock.name)]
    if not universe:
        raise RuntimeError("验证股票范围为空")

    started = time.monotonic()
    histories, errors = fetch_histories(
        universe,
        args.bars,
        args.workers or int(cfg["workers"]),
    )
    histories = truncate_histories(histories, cutoff)
    report = build_report(
        cfg,
        histories,
        errors,
        args.bars,
        cutoff,
        candidates,
        assumptions,
        cost_multipliers,
        include_trades=not args.omit_trades,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"组合验证完成: {len(histories)}/{len(universe)}只，失败{len(errors)}只，"
        f"耗时{time.monotonic() - started:.1f}秒",
        flush=True,
    )
    print(f"结果: {args.output}", flush=True)
    return 1 if len(errors) > 10 else 0


if __name__ == "__main__":
    raise SystemExit(main())
