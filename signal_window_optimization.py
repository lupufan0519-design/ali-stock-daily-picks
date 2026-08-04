from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from array import array
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from rolling_validation import (
    CausalLineState,
    ExecutionAssumptions,
    completed_trade_date,
    execution_assumptions,
    fetch_histories,
    next_open_fill,
    replay_signals,
    research_meta,
    truncate_histories,
)
from screener import Bar, Stock, cached_universe, has_yellow_segment, is_st_name, load_config
from strategy_contract import (
    ENTRY_DELAY_BARS,
    ENTRY_EXECUTION_MAX_WAIT_BARS,
    ENTRY_LABEL,
    ENTRY_MAX_PULLBACK_PCT,
    ENTRY_REQUIRE_CLOSE_ABOVE_DRAGON,
    ENTRY_REQUIRE_DRAGON_NONFALLING,
    ENTRY_REQUIRE_SIGNAL_VALID,
    EXECUTION_SCOPE,
    EXIT_MAX_HOLDING_BARS,
    EXIT_ON_DRAGON_TIGER_END,
    EXIT_ON_TRUE_ERASURE,
    EXIT_PROFIT_ACTIVATION_PCT,
    EXIT_LABEL,
    EXIT_TRAILING_DRAWDOWN_PCT,
    EXIT_WEAKENING_CONFIRMATIONS,
    EXIT_WEAKENING_POINTS,
    FROZEN_CANDIDATE_ID,
    LIVE_STRATEGY_ID,
    strategy_contract,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "results" / "signal_window_optimization.json"
YELLOW_BEFORE_DAYS = 2
YELLOW_AFTER_DAYS = 7
CROSS_LOOKBACK_DAYS = YELLOW_AFTER_DAYS + 1
MAX_HOLD_BARS = EXIT_MAX_HOLDING_BARS
# 10 closes to confirm + following-open entry + 60 close observations +
# following-open exit. Every candidate sees the exact same completed horizon.
COMMON_FUTURE_BARS = 72
FORWARD_HORIZONS = (5, 10, 20, 40, 60)
# Backward-compatible names retained for readers of the existing research
# schema. Their values come exclusively from the shared live contract.
FROZEN_LIVE_STRATEGY_ID = LIVE_STRATEGY_ID
FROZEN_LIVE_CANDIDATE_ID = FROZEN_CANDIDATE_ID
FROZEN_ENTRY_ID, FROZEN_EXIT_ID = FROZEN_CANDIDATE_ID.split("__", 1)
FORWARD_SELECTION_POLICY = (
    "开发期与2024-2025验证期用于策略研究；2026结果已被反复查看并参与本次人工冻结，"
    "因此不再属于盲测。真正的forward验证只从本次冻结批次截止日之后的新交易日开始。"
)


ENTRY_METHODS = (
    {"id": "signal_close", "label": "信号日收盘确认，下一可交易日开盘买入", "kind": "close", "delay": 0},
    {"id": "next_close", "label": "信号保持到下一交易日收盘，再于随后可交易日开盘买入", "kind": "close", "delay": 1},
    {"id": "persist_2", "label": "信号保持2个交易日，再于随后可交易日开盘买入", "kind": "close", "delay": 2},
    {"id": "persist_3", "label": "信号保持3个交易日，再于随后可交易日开盘买入", "kind": "close", "delay": 3},
    {
        "id": "low_risk_1",
        "label": "信号后第1日仍有效、收盘站上龙线且较信号价回撤不超过3%，下一可交易日开盘买入",
        "kind": "timed_filter",
        "delay": 1,
        "max_pullback": 3.0,
        "require_above_dragon": True,
    },
    {
        "id": "low_risk_2",
        "label": ENTRY_LABEL,
        "kind": "timed_filter",
        "delay": ENTRY_DELAY_BARS,
        "max_pullback": ENTRY_MAX_PULLBACK_PCT,
        "require_above_dragon": ENTRY_REQUIRE_CLOSE_ABOVE_DRAGON,
        "require_dragon_nonfalling": ENTRY_REQUIRE_DRAGON_NONFALLING,
    },
    {
        "id": "low_risk_3",
        "label": "信号后第3日仍有效、收盘站上龙线且龙线未转跌，下一可交易日开盘买入",
        "kind": "timed_filter",
        "delay": 3,
        "max_pullback": 3.0,
        "require_above_dragon": True,
        "require_dragon_nonfalling": True,
    },
    {
        "id": "confirm_0_5_3d",
        "label": "3日内收盘较信号价上涨0.5%",
        "kind": "threshold",
        "threshold": 0.5,
        "max_wait": 3,
    },
    {
        "id": "confirm_1_3d",
        "label": "3日内收盘较信号价上涨1%",
        "kind": "threshold",
        "threshold": 1.0,
        "max_wait": 3,
    },
    {
        "id": "confirm_1_5d",
        "label": "5日内收盘较信号价上涨1%",
        "kind": "threshold",
        "threshold": 1.0,
        "max_wait": 5,
    },
    {"id": "confirm_1", "label": "10日内收盘较信号价上涨1%", "kind": "threshold", "threshold": 1.0},
    {"id": "confirm_2", "label": "10日内收盘较信号价上涨2%", "kind": "threshold", "threshold": 2.0},
    {"id": "confirm_3", "label": "10日内收盘较信号价上涨3%", "kind": "threshold", "threshold": 3.0},
    {"id": "confirm_5", "label": "10日内收盘较信号价上涨5%", "kind": "threshold", "threshold": 5.0},
    {"id": "confirm_8", "label": "10日内收盘较信号价上涨8%", "kind": "threshold", "threshold": 8.0},
    {
        "id": "break_signal_high_3d",
        "label": "3日内收盘突破信号日最高价",
        "kind": "signal_high",
        "max_wait": 3,
    },
    {
        "id": "break_signal_high_5d",
        "label": "5日内收盘突破信号日最高价",
        "kind": "signal_high",
        "max_wait": 5,
    },
    {"id": "break_signal_high", "label": "10日内收盘突破信号日最高价", "kind": "signal_high"},
    {"id": "break_3day_high", "label": "10日内收盘突破此前3日最高价", "kind": "recent_high", "lookback": 3},
    {"id": "break_5day_high", "label": "10日内收盘突破此前5日最高价", "kind": "recent_high", "lookback": 5},
    {"id": "reclaim_dragon", "label": "10日内收盘重新站上龙线且龙线转升", "kind": "dragon_reclaim"},
)

EARLY_WAVE_ENTRY_IDS = frozenset(
    {
        "signal_close",
        "next_close",
        "persist_2",
        "persist_3",
        "low_risk_1",
        "low_risk_2",
        "low_risk_3",
        "confirm_0_5_3d",
        "confirm_1_3d",
        "confirm_1_5d",
        "confirm_1",
        "break_signal_high_3d",
        "break_signal_high_5d",
        "break_signal_high",
    }
)


def exit_rules() -> tuple[dict, ...]:
    rules: list[dict] = [
        {
            "id": f"hold_{bars}",
            "label": f"持有{bars}日；龙线不再高于虎线则提前卖出",
            "kind": "fixed",
            "bars": bars,
        }
        for bars in (1, 2, 3, 5, 8, 10, 13, 20, 30, 40, 60)
    ]
    rules.extend(
        [
            {
                "id": "relationship_end",
                "label": "龙线不再高于虎线时卖出；标签自然到期或被重算不单独卖出",
                "kind": "relationship",
            },
            {
                "id": "erasure_or_relationship_end",
                "label": "龙腾跃虎标签被重算消失，或龙线不再高于虎线时卖出",
                "kind": "relationship",
                "exit_on_erasure": True,
            },
            {
                "id": "weakening_1",
                "label": "龙虎线首次同步转弱时卖出；最迟龙虎关系结束",
                "kind": "weakening",
                "confirm": 1,
            },
            {
                "id": "weakening_2",
                "label": "龙虎线连续2日同步转弱时卖出；最迟龙虎关系结束",
                "kind": "weakening",
                "confirm": 2,
            },
        ]
    )
    for period in (5, 10, 20):
        for confirm in (1, 2):
            rules.append(
                {
                    "id": f"ma_{period}_{confirm}",
                    "label": f"连续{confirm}日收盘低于{period}日均线时卖出；最迟龙虎关系结束",
                    "kind": "ma",
                    "period": period,
                    "confirm": confirm,
                }
            )
    for activation in (0.0, 3.0, 5.0, 8.0, 10.0, 15.0):
        for drawdown in (2.0, 3.0, 5.0, 8.0, 10.0, 12.0, 15.0, 20.0):
            rules.append(
                {
                    "id": f"trail_{activation:g}_{drawdown:g}",
                    "label": (
                        ("买入后立即" if activation == 0 else f"浮盈达到{activation:g}%后")
                        + f"，较最高收盘回撤{drawdown:g}%卖出；最迟龙虎关系结束或60日"
                    ),
                    "kind": "trailing",
                    "activation": activation,
                    "drawdown": drawdown,
                }
            )
    for target in (3.0, 5.0, 8.0, 10.0, 15.0, 20.0, 30.0):
        rules.append(
            {
                "id": f"target_{target:g}",
                "label": f"收盘浮盈首次达到{target:g}%止盈；未达到则最迟龙虎关系结束",
                "kind": "target",
                "target": target,
            }
        )
    for target in (5.0, 10.0, 15.0, 20.0):
        for stop in (5.0, 8.0, 10.0):
            rules.append(
                {
                    "id": f"target_{target:g}_stop_{stop:g}",
                    "label": f"收盘浮盈达到{target:g}%止盈，或亏损达到{stop:g}%止损；最迟龙虎关系结束",
                    "kind": "target",
                    "target": target,
                    "stop": stop,
                }
            )
    wave_trailing_grid = {
        5.0: (2.0, 3.0, 5.0, 8.0),
        8.0: (3.0, 5.0, 8.0, 10.0, 12.0),
        10.0: (5.0, 8.0, 10.0),
        15.0: (8.0, 10.0, 12.0),
    }
    for activation, drawdowns in wave_trailing_grid.items():
        for drawdown in drawdowns:
            rules.append(
                {
                    "id": f"wave_erasure_trail_{activation:g}_{drawdown:g}",
                    "label": (
                        "信号重算消失优先退出；"
                        f"浮盈达到{activation:g}%后较最高收盘回撤{drawdown:g}%，"
                        "或龙虎关系结束"
                    ),
                    "kind": "trailing",
                    "activation": activation,
                    "drawdown": drawdown,
                    "exit_on_erasure": True,
                }
            )
    for activation, drawdown in (
        (8.0, 3.0),
        (8.0, 5.0),
        (10.0, 5.0),
        (10.0, 10.0),
    ):
        rule_id = f"wave_erasure_hybrid_or_{activation:g}_{drawdown:g}_weakening"
        rules.append(
            {
                "id": rule_id,
                "label": EXIT_LABEL
                if rule_id == FROZEN_EXIT_ID
                else (
                    "信号重算消失优先退出；"
                    f"浮盈达到{activation:g}%后回撤{drawdown:g}%或龙虎线同步转弱，"
                    "二者先到先卖；最迟龙虎关系结束"
                ),
                "kind": "hybrid",
                "activation": (
                    EXIT_PROFIT_ACTIVATION_PCT
                    if rule_id == FROZEN_EXIT_ID
                    else activation
                ),
                "drawdown": (
                    EXIT_TRAILING_DRAWDOWN_PCT
                    if rule_id == FROZEN_EXIT_ID
                    else drawdown
                ),
                "weakening_confirm": (
                    EXIT_WEAKENING_CONFIRMATIONS
                    if rule_id == FROZEN_EXIT_ID
                    else 1
                ),
                "combine": "either",
                "exit_on_erasure": (
                    EXIT_ON_TRUE_ERASURE if rule_id == FROZEN_EXIT_ID else True
                ),
            }
        )
    for activation, drawdown in ((8.0, 5.0), (10.0, 5.0)):
        rules.append(
            {
                "id": (
                    f"wave_erasure_hybrid_and_{activation:g}_{drawdown:g}_weakening"
                ),
                "label": (
                    "信号重算消失优先退出；"
                    f"浮盈达到{activation:g}%后回撤{drawdown:g}%且龙虎线已同步转弱，"
                    "两项均出现后卖出；最迟龙虎关系结束"
                ),
                "kind": "hybrid",
                "activation": activation,
                "drawdown": drawdown,
                "weakening_confirm": 1,
                "combine": "all",
                "exit_on_erasure": True,
            }
        )
    rules.extend(
        [
            {
                "id": "wave_erasure_weakening_1",
                "label": "信号重算消失优先退出；龙虎线首次同步转弱，或龙虎关系结束",
                "kind": "weakening",
                "confirm": 1,
                "exit_on_erasure": True,
            },
            {
                "id": "wave_erasure_weakening_2",
                "label": "信号重算消失优先退出；龙虎线连续2日同步转弱，或龙虎关系结束",
                "kind": "weakening",
                "confirm": 2,
                "exit_on_erasure": True,
            },
            {
                "id": "wave_erasure_ma_5_10",
                "label": "信号重算消失优先退出；连续2日收盘跌破10日均线且5日均线转弱，或龙虎关系结束",
                "kind": "wave_end",
                "fast_period": 5,
                "slow_period": 10,
                "ma_confirm": 2,
                "minimum_holding_bars": 3,
                "exit_on_erasure": True,
            },
            {
                "id": "wave_erasure_ma_5_20",
                "label": "信号重算消失优先退出；连续2日收盘跌破20日均线且5日均线转弱，或龙虎关系结束",
                "kind": "wave_end",
                "fast_period": 5,
                "slow_period": 20,
                "ma_confirm": 2,
                "minimum_holding_bars": 5,
                "exit_on_erasure": True,
            },
            {
                "id": "wave_erasure_structure_5",
                "label": "信号重算消失优先退出；连续2日收盘跌破此前5日最低收盘且龙线转弱，或龙虎关系结束",
                "kind": "wave_end",
                "structure_lookback": 5,
                "structure_confirm": 2,
                "minimum_holding_bars": 3,
                "exit_on_erasure": True,
            },
            {
                "id": "wave_erasure_adaptive_5_8",
                "label": "信号重算消失优先退出；浮盈5%后回撤8%，或均线与低点结构共同转弱，最迟龙虎关系结束",
                "kind": "wave_end",
                "activation": 5.0,
                "drawdown": 8.0,
                "trailing_confirm": 1,
                "fast_period": 5,
                "slow_period": 10,
                "ma_confirm": 2,
                "structure_lookback": 5,
                "structure_confirm": 2,
                "minimum_holding_bars": 3,
                "exit_on_erasure": True,
            },
            {
                "id": "wave_erasure_adaptive_8_10",
                "label": "信号重算消失优先退出；浮盈8%后回撤10%，或中期均线与低点结构转弱，最迟龙虎关系结束",
                "kind": "wave_end",
                "activation": 8.0,
                "drawdown": 10.0,
                "trailing_confirm": 2,
                "fast_period": 5,
                "slow_period": 20,
                "ma_confirm": 2,
                "structure_lookback": 8,
                "structure_confirm": 2,
                "require_ma_and_structure": True,
                "minimum_holding_bars": 5,
                "exit_on_erasure": True,
            },
        ]
    )
    return tuple(rules)


EXIT_RULES = exit_rules()
LONG_WAVE_EXIT_IDS = frozenset(
    str(rule["id"])
    for rule in EXIT_RULES
    if str(rule["id"]).startswith("wave_erasure_")
)


@dataclass
class Samples:
    returns: array = field(default_factory=lambda: array("f"))
    holding: array = field(default_factory=lambda: array("H"))
    development: array = field(default_factory=lambda: array("f"))
    development_holding: array = field(default_factory=lambda: array("H"))
    validation: array = field(default_factory=lambda: array("f"))
    validation_holding: array = field(default_factory=lambda: array("H"))
    holdout: array = field(default_factory=lambda: array("f"))
    holdout_holding: array = field(default_factory=lambda: array("H"))
    by_completed_year: dict[str, array] = field(default_factory=dict)
    holding_by_completed_year: dict[str, array] = field(default_factory=dict)

    def add(
        self,
        value: float,
        holding_bars: int,
        entry_date: str,
        exit_date: str,
    ) -> None:
        self.returns.append(float(value))
        normalized_holding = max(0, int(holding_bars))
        self.holding.append(normalized_holding)
        completed_year = exit_date[:4]
        self.by_completed_year.setdefault(completed_year, array("f")).append(
            float(value)
        )
        self.holding_by_completed_year.setdefault(
            completed_year,
            array("H"),
        ).append(normalized_holding)

        # A period may only score a trade whose entry and exit were both known
        # before that period ended. Trades spanning 2024-01-01 or 2026-01-01
        # remain in ``returns`` but are deliberately absent from period buckets.
        if entry_date < "2024-01-01" and exit_date < "2024-01-01":
            self.development.append(float(value))
            self.development_holding.append(normalized_holding)
        elif entry_date >= "2024-01-01" and exit_date < "2026-01-01":
            self.validation.append(float(value))
            self.validation_holding.append(normalized_holding)
        elif entry_date >= "2026-01-01":
            self.holdout.append(float(value))
            self.holdout_holding.append(normalized_holding)


@dataclass
class CohortSamples:
    combined: Samples = field(default_factory=Samples)
    main: Samples = field(default_factory=Samples)
    secondary: Samples = field(default_factory=Samples)

    def add(
        self,
        value: float,
        holding_bars: int,
        entry_date: str,
        exit_date: str,
        entry_area: str,
    ) -> None:
        self.combined.add(value, holding_bars, entry_date, exit_date)
        if entry_area == "main":
            self.main.add(value, holding_bars, entry_date, exit_date)
        elif entry_area == "secondary":
            self.secondary.add(value, holding_bars, entry_date, exit_date)


@dataclass
class WaveSamples:
    peak_high_returns: array = field(default_factory=lambda: array("f"))
    peak_close_returns: array = field(default_factory=lambda: array("f"))
    days_to_peak_high: array = field(default_factory=lambda: array("H"))
    wave_lengths: array = field(default_factory=lambda: array("H"))

    def add(
        self,
        peak_high_return: float,
        peak_close_return: float,
        days_to_peak: int,
        wave_length: int,
    ) -> None:
        self.peak_high_returns.append(float(peak_high_return))
        self.peak_close_returns.append(float(peak_close_return))
        self.days_to_peak_high.append(max(0, int(days_to_peak)))
        self.wave_lengths.append(max(0, int(wave_length)))


@dataclass
class WaveCaptureSamples:
    pre_exit_peak_close_returns: array = field(default_factory=lambda: array("f"))
    peak_close_returns: array = field(default_factory=lambda: array("f"))
    peak_givebacks: array = field(default_factory=lambda: array("f"))
    capture_ratios: array = field(default_factory=lambda: array("f"))

    def add(
        self,
        net_return: float,
        peak_close_return: float,
        full_wave_peak_close_return: float | None = None,
    ) -> None:
        full_wave_peak = (
            float(peak_close_return)
            if full_wave_peak_close_return is None
            else float(full_wave_peak_close_return)
        )
        self.pre_exit_peak_close_returns.append(float(peak_close_return))
        self.peak_close_returns.append(full_wave_peak)
        self.peak_givebacks.append(float(full_wave_peak - net_return))
        if full_wave_peak > 0:
            self.capture_ratios.append(float(net_return / full_wave_peak * 100.0))


@dataclass
class CohortWaveCaptureSamples:
    combined: WaveCaptureSamples = field(default_factory=WaveCaptureSamples)
    main: WaveCaptureSamples = field(default_factory=WaveCaptureSamples)
    secondary: WaveCaptureSamples = field(default_factory=WaveCaptureSamples)

    def add(
        self,
        net_return: float,
        pre_exit_peak_close_return: float,
        full_wave_peak_close_return: float,
        entry_area: str,
    ) -> None:
        self.combined.add(
            net_return,
            pre_exit_peak_close_return,
            full_wave_peak_close_return,
        )
        if entry_area == "main":
            self.main.add(
                net_return,
                pre_exit_peak_close_return,
                full_wave_peak_close_return,
            )
        elif entry_area == "secondary":
            self.secondary.add(
                net_return,
                pre_exit_peak_close_return,
                full_wave_peak_close_return,
            )


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def stats(values: Sequence[float], holding: Sequence[int] | None = None) -> dict:
    numbers = [float(value) for value in values]
    if not numbers:
        return {
            "sample_count": 0,
            "average_pct": 0.0,
            "median_pct": 0.0,
            "positive_rate_pct": 0.0,
            "geometric_average_pct": 0.0,
            "profit_factor": None,
            "average_ci95_lower_pct": 0.0,
            "p10_pct": 0.0,
            "p25_pct": 0.0,
            "p75_pct": 0.0,
            "average_excluding_abs_50pct_outliers_pct": 0.0,
            "median_holding_bars": 0.0,
        }
    gains = sum(value for value in numbers if value > 0)
    losses = abs(sum(value for value in numbers if value <= 0))
    regular = [value for value in numbers if abs(value) <= 50.0]
    logs = [math.log1p(value / 100.0) for value in numbers if value > -100.0]
    mean_value = statistics.fmean(numbers)
    standard_error = (
        statistics.stdev(numbers) / math.sqrt(len(numbers))
        if len(numbers) > 1
        else 0.0
    )
    return {
        "sample_count": len(numbers),
        "average_pct": round(mean_value, 4),
        "median_pct": round(statistics.median(numbers), 4),
        "positive_rate_pct": round(sum(value > 0 for value in numbers) / len(numbers) * 100.0, 2),
        "geometric_average_pct": round(math.expm1(statistics.fmean(logs)) * 100.0, 4) if logs else 0.0,
        "profit_factor": round(gains / losses, 4) if losses else None,
        "average_ci95_lower_pct": round(mean_value - 1.96 * standard_error, 4),
        "p10_pct": round(percentile(numbers, 0.10), 4),
        "p25_pct": round(percentile(numbers, 0.25), 4),
        "p75_pct": round(percentile(numbers, 0.75), 4),
        "average_excluding_abs_50pct_outliers_pct": round(statistics.fmean(regular), 4) if regular else 0.0,
        "median_holding_bars": round(statistics.median(holding), 2) if holding else 0.0,
    }


def wave_stats(samples: WaveSamples) -> dict:
    highs = [float(value) for value in samples.peak_high_returns]
    closes = [float(value) for value in samples.peak_close_returns]
    if not highs:
        return {"sample_count": 0}

    def rate(threshold: float) -> float:
        return round(sum(value >= threshold for value in highs) / len(highs) * 100.0, 2)

    return {
        "sample_count": len(highs),
        "success_definition": "信号确认后的本轮波段最高价高于信号确认日收盘价",
        "ever_rise_rate_pct": rate(0.000001),
        "ever_reach_3pct_rate_pct": rate(3.0),
        "ever_reach_5pct_rate_pct": rate(5.0),
        "ever_reach_10pct_rate_pct": rate(10.0),
        "ever_reach_20pct_rate_pct": rate(20.0),
        "average_peak_high_return_pct": round(statistics.fmean(highs), 4),
        "median_peak_high_return_pct": round(statistics.median(highs), 4),
        "p25_peak_high_return_pct": round(percentile(highs, 0.25), 4),
        "p75_peak_high_return_pct": round(percentile(highs, 0.75), 4),
        "average_peak_close_return_pct": round(statistics.fmean(closes), 4),
        "median_peak_close_return_pct": round(statistics.median(closes), 4),
        "median_days_to_peak_high": round(statistics.median(samples.days_to_peak_high), 2),
        "median_wave_length_bars": round(statistics.median(samples.wave_lengths), 2),
    }


def wave_capture_stats(samples: WaveCaptureSamples) -> dict:
    pre_exit_peaks = [
        float(value) for value in samples.pre_exit_peak_close_returns
    ]
    peaks = [float(value) for value in samples.peak_close_returns]
    givebacks = [float(value) for value in samples.peak_givebacks]
    captures = [float(value) for value in samples.capture_ratios]
    if not peaks:
        return {"sample_count": 0}
    return {
        "sample_count": len(peaks),
        "definition": (
            "完整波段最高收盘浮盈从实际买入开盘起算，到龙虎关系结束或60日上限；"
            "卖前最高浮盈只统计到本策略卖出触发收盘；峰值回吐=完整波段最高浮盈-扣费净收益；"
            "兑现比例仅统计完整波段曾有正浮盈的交易，属于事后效率上限，不参与买卖触发"
        ),
        "average_pre_exit_peak_close_return_pct": round(
            statistics.fmean(pre_exit_peaks), 4
        ),
        "median_pre_exit_peak_close_return_pct": round(
            statistics.median(pre_exit_peaks), 4
        ),
        "average_peak_close_return_pct": round(statistics.fmean(peaks), 4),
        "median_peak_close_return_pct": round(statistics.median(peaks), 4),
        "average_peak_giveback_pct": round(statistics.fmean(givebacks), 4),
        "median_peak_giveback_pct": round(statistics.median(givebacks), 4),
        "capture_sample_count": len(captures),
        "median_net_capture_ratio_pct": (
            round(statistics.median(captures), 2) if captures else 0.0
        ),
    }


def signal_indices(points: Sequence, cohort: str = "base") -> list[int]:
    """Record causal signal appearances without duplicating one bull lineage.

    ``pool`` starts when a stock first enters either main or secondary. A later
    secondary-to-main promotion stays in the same transaction and is therefore
    not counted again.  The lineage is released only after dragon is no longer
    above tiger; a drifting ``cross_date`` while the relationship remains bullish
    is a recalculation of the same cross, not a new opportunity.
    """
    if cohort not in {"base", "pool", "main", "secondary"}:
        raise ValueError(f"未知信号样本口径: {cohort}")
    indices: list[int] = []
    previous = False
    pool_lineage_active = False
    for index, point in enumerate(points):
        if cohort == "pool":
            relationship_alive = bool(point.dragon > point.tiger)
            if not relationship_alive:
                pool_lineage_active = False
            current = bool(point.area) and relationship_alive
            if current and not pool_lineage_active:
                indices.append(index)
                pool_lineage_active = True
            continue
        current = (
            bool(point.base_signal)
            if cohort == "base"
            else point.area == cohort
        )
        if current and not previous:
            indices.append(index)
        previous = current
    return indices


def signal_erased(points: Sequence, setup_index: int, index: int) -> bool:
    setup = points[setup_index]
    remaining = max(0, int(setup.cross_lookback_days) - int(setup.cross_age) - 1)
    elapsed = index - setup_index
    return bool(
        elapsed <= remaining
        and not points[index].cross_ok
        and points[index].dragon > points[index].tiger
    )


def append_wave_sample(
    target: WaveSamples,
    points: Sequence,
    bars: Sequence[Bar],
    setup_index: int,
) -> tuple[bool, int] | None:
    """Measure the next bull wave from the known signal to its later high."""
    if setup_index + MAX_HOLD_BARS >= len(points):
        return None
    end_index = setup_index + MAX_HOLD_BARS
    erased = False
    for index in range(setup_index + 1, end_index + 1):
        erased = erased or signal_erased(points, setup_index, index)
        if points[index].dragon <= points[index].tiger:
            end_index = index
            break
    entry_price = float(points[setup_index].close)
    future_indices = range(setup_index + 1, end_index + 1)
    peak_high_index = max(future_indices, key=lambda index: float(bars[index].high))
    peak_close_index = max(future_indices, key=lambda index: float(points[index].close))
    target.add(
        (float(bars[peak_high_index].high) / entry_price - 1.0) * 100.0,
        (float(points[peak_close_index].close) / entry_price - 1.0) * 100.0,
        peak_high_index - setup_index,
        end_index - setup_index,
    )
    return erased, end_index


def risk_exit_index(
    points: Sequence,
    setup_index: int,
    start_index: int,
    *,
    exit_on_erasure: bool = False,
    exit_on_relationship_end: bool = True,
    include_start: bool = False,
) -> int:
    end = min(len(points) - 1, start_index + MAX_HOLD_BARS)
    first = start_index if include_start else start_index + 1
    for index in range(first, end + 1):
        if exit_on_erasure and signal_erased(points, setup_index, index):
            return index
        if exit_on_relationship_end and points[index].dragon <= points[index].tiger:
            return index
    return end


def entry_for_method(
    points: Sequence,
    bars: Sequence[Bar],
    setup_index: int,
    method: dict,
    *,
    stock: Stock | None = None,
    execution: ExecutionAssumptions | None = None,
    include_trigger: bool = False,
) -> tuple[int, float] | tuple[int, float, int, float] | None:
    """Resolve a causal entry trigger and, in production, its executable fill.

    Without ``stock``/``execution`` this keeps the legacy trigger-price return
    used by low-level signal tests. Production optimization always supplies
    both and turns every close confirmation into a next-tradable-open fill.
    """
    kind = str(method["kind"])
    require_signal_valid = bool(
        ENTRY_REQUIRE_SIGNAL_VALID
        if str(method.get("id", "")) == FROZEN_ENTRY_ID
        else True
    )
    trigger_index = -1
    legacy_index = -1
    legacy_price = 0.0
    if kind in {"close", "open", "timed_filter"}:
        index = setup_index + int(method["delay"])
        if index >= len(points):
            return None
        # A next-open order can only use information known at the prior close.
        # ``cross_date`` can drift when the causal XMA tail is recalculated.
        # While cross_ok remains true and dragon stays above tiger this is the
        # same active setup, not a new independent cross. A real new cycle must
        # first pass through relationship loss, which is rejected below.
        visible_end = index if kind == "open" else index + 1
        for offset in range(setup_index + 1, visible_end):
            if (
                (require_signal_valid and signal_erased(points, setup_index, offset))
                or points[offset].dragon <= points[offset].tiger
            ):
                return None
        if kind == "timed_filter":
            close = float(points[index].close)
            setup_close = float(points[setup_index].close)
            if (
                method.get("require_above_dragon")
                and close < float(points[index].dragon)
            ):
                return None
            if (
                method.get("require_dragon_nonfalling")
                and index > 0
                and float(points[index].dragon) < float(points[index - 1].dragon)
            ):
                return None
            max_pullback = method.get("max_pullback")
            if (
                max_pullback is not None
                and close
                < setup_close * (1.0 - float(max_pullback) / 100.0)
            ):
                return None
        trigger_index = setup_index if kind == "open" else index
        legacy_index = index
        legacy_price = float(bars[index].open if kind == "open" else points[index].close)
    else:
        signal_close = float(points[setup_index].close)
        signal_high = float(bars[setup_index].high)
        max_wait = int(method.get("max_wait", 10))
        for index in range(
            setup_index + 1,
            min(len(points), setup_index + max_wait + 1),
        ):
            # The end-of-day setup must still exist on the confirmation close.
            # This is what correctly cancels 海南华铁 on 2025-02-12.
            if (
                (require_signal_valid and signal_erased(points, setup_index, index))
                or points[index].dragon <= points[index].tiger
            ):
                return None
            close = float(points[index].close)
            ready = False
            if kind == "threshold":
                ready = close >= signal_close * (1.0 + float(method["threshold"]) / 100.0)
            elif kind == "signal_high":
                ready = close > signal_high
            elif kind == "recent_high":
                lookback = int(method["lookback"])
                start = max(0, index - lookback)
                ready = close > max(float(bar.high) for bar in bars[start:index])
            elif kind == "dragon_reclaim":
                ready = (
                    close > float(points[index].dragon)
                    and float(points[index].dragon) > float(points[index - 1].dragon)
                )
            else:
                raise ValueError(f"未知买点类型: {kind}")
            if ready:
                trigger_index = index
                legacy_index = index
                legacy_price = close
                break
        if trigger_index < 0:
            return None

    if stock is None or execution is None:
        if legacy_price <= 0:
            return None
        result = (legacy_index, legacy_price, trigger_index, legacy_price)
        return result if include_trigger else result[:2]

    def setup_still_valid(index: int) -> bool:
        return (
            (not require_signal_valid or not signal_erased(points, setup_index, index))
            and points[index].dragon > points[index].tiger
        )

    fill = next_open_fill(
        stock,
        bars,
        trigger_index,
        "buy",
        execution,
        can_continue_after_close=setup_still_valid,
    )
    if fill is None:
        return None
    result = (fill.index, fill.effective_price, trigger_index, fill.raw_price)
    return result if include_trigger else result[:2]


def weakening(points: Sequence, index: int) -> bool:
    if (
        index + 1 < EXIT_WEAKENING_POINTS
        or points[index].dragon <= points[index].tiger
    ):
        return False
    latest = points[index - EXIT_WEAKENING_POINTS + 1 : index + 1]
    dragons = [point.dragon for point in latest]
    spreads = [point.dragon - point.tiger for point in latest]
    return all(left > right for left, right in zip(dragons, dragons[1:])) and all(
        left > right for left, right in zip(spreads, spreads[1:])
    )


def moving_average(points: Sequence, index: int, period: int) -> float | None:
    if index + 1 < period:
        return None
    return statistics.fmean(point.close for point in points[index - period + 1 : index + 1])


def exit_for_rule(
    points: Sequence,
    setup_index: int,
    entry_index: int,
    entry_price: float,
    hard_end: int,
    rule: dict,
) -> int:
    kind = str(rule["kind"])
    if kind == "relationship":
        return hard_end
    if kind == "fixed":
        return min(hard_end, entry_index + int(rule["bars"]))

    weakening_streak = 0
    ma_streak = 0
    structure_streak = 0
    trailing_streak = 0
    trailing_seen = False
    weakening_seen = False
    peak_close = max(entry_price, float(points[entry_index].close))
    activated = float(rule.get("activation", 0.0)) <= 0
    # The entry order fills at the open, so the same day's close is the first
    # causal moment at which an exit may be confirmed. This mirrors the live
    # tracker, including delayed fills whose lines have weakened while blocked.
    for index in range(entry_index, hard_end + 1):
        close = float(points[index].close)
        peak_close = max(peak_close, close)
        if kind == "weakening":
            weakening_streak = weakening_streak + 1 if weakening(points, index) else 0
            if weakening_streak >= int(rule["confirm"]):
                return index
        elif kind == "ma":
            average = moving_average(points, index, int(rule["period"]))
            ma_streak = ma_streak + 1 if average is not None and close < average else 0
            if ma_streak >= int(rule["confirm"]):
                return index
        elif kind == "trailing":
            if peak_close / entry_price - 1.0 >= float(rule["activation"]) / 100.0:
                activated = True
            if activated and close / peak_close - 1.0 <= -float(rule["drawdown"]) / 100.0:
                return index
        elif kind == "target":
            current_return = (close / entry_price - 1.0) * 100.0
            if current_return >= float(rule["target"]):
                return index
            if rule.get("stop") is not None and current_return <= -float(rule["stop"]):
                return index
        elif kind == "hybrid":
            if peak_close / entry_price - 1.0 >= float(rule["activation"]) / 100.0:
                activated = True
            trailing_hit = bool(
                activated
                and close / peak_close - 1.0
                <= -float(rule["drawdown"]) / 100.0
            )
            weakening_streak = (
                weakening_streak + 1 if weakening(points, index) else 0
            )
            weakening_hit = weakening_streak >= int(
                rule.get("weakening_confirm", 1)
            )
            if str(rule.get("combine", "either")) == "either":
                if trailing_hit or weakening_hit:
                    return index
            else:
                trailing_seen = trailing_seen or trailing_hit
                weakening_seen = weakening_seen or weakening_hit
                if trailing_seen and weakening_seen:
                    return index
        elif kind == "wave_end":
            activation = rule.get("activation")
            drawdown = rule.get("drawdown")
            if (
                activation is not None
                and peak_close / entry_price - 1.0
                >= float(activation) / 100.0
            ):
                activated = True
            trailing_breach = bool(
                activated
                and drawdown is not None
                and close / peak_close - 1.0
                <= -float(drawdown) / 100.0
            )
            trailing_streak = trailing_streak + 1 if trailing_breach else 0

            fast_period = int(rule.get("fast_period", 0))
            slow_period = int(rule.get("slow_period", 0))
            fast_average = (
                moving_average(points, index, fast_period)
                if fast_period > 0
                else None
            )
            slow_average = (
                moving_average(points, index, slow_period)
                if slow_period > 0
                else None
            )
            ma_weak = bool(
                fast_average is not None
                and slow_average is not None
                and close < slow_average
                and fast_average <= slow_average
            )
            ma_streak = ma_streak + 1 if ma_weak else 0

            structure_lookback = int(rule.get("structure_lookback", 0))
            structure_weak = bool(
                structure_lookback > 0
                and index >= structure_lookback
                and close
                < min(
                    float(point.close)
                    for point in points[index - structure_lookback : index]
                )
                and float(points[index].dragon)
                < float(points[index - 1].dragon)
            )
            structure_streak = structure_streak + 1 if structure_weak else 0

            if index - entry_index < int(rule.get("minimum_holding_bars", 0)):
                continue
            if trailing_streak >= int(rule.get("trailing_confirm", 1)):
                return index
            ma_finished = bool(
                int(rule.get("ma_confirm", 0)) > 0
                and ma_streak >= int(rule["ma_confirm"])
            )
            structure_finished = bool(
                int(rule.get("structure_confirm", 0)) > 0
                and structure_streak >= int(rule["structure_confirm"])
            )
            if rule.get("require_ma_and_structure"):
                if ma_finished and structure_finished:
                    return index
            elif ma_finished or structure_finished:
                return index
    return hard_end


def exit_reason_for_trade(
    points: Sequence,
    setup_index: int,
    entry_index: int,
    entry_price: float,
    exit_trigger_index: int,
    rule: dict,
) -> str:
    """Describe the close-known condition that actually ended a trade."""
    if signal_erased(points, setup_index, exit_trigger_index):
        return "signal_recalculated_away"
    if points[exit_trigger_index].dragon <= points[exit_trigger_index].tiger:
        return "dragon_tiger_relationship_end"

    kind = str(rule["kind"])
    peak_close = max(
        entry_price,
        *(
            float(points[index].close)
            for index in range(entry_index, exit_trigger_index + 1)
        ),
    )
    close = float(points[exit_trigger_index].close)
    activation = float(rule.get("activation", 0.0))
    drawdown = float(rule.get("drawdown", 0.0))
    trailing_hit = bool(
        peak_close / entry_price - 1.0 >= activation / 100.0
        and close / peak_close - 1.0 <= -drawdown / 100.0
    )
    weakening_confirm = int(rule.get("weakening_confirm", rule.get("confirm", 1)))
    weakening_hit = bool(
        weakening_confirm > 0
        and exit_trigger_index - weakening_confirm + 1 >= entry_index
        and all(
            weakening(points, index)
            for index in range(
                exit_trigger_index - weakening_confirm + 1,
                exit_trigger_index + 1,
            )
        )
    )
    if kind == "hybrid":
        if trailing_hit and weakening_hit:
            return "profit_trailing_drawdown_and_dragon_tiger_weakening"
        if trailing_hit:
            return "profit_trailing_drawdown"
        if weakening_hit:
            return "dragon_tiger_weakening"
    elif kind == "trailing" and trailing_hit:
        return "profit_trailing_drawdown"
    elif kind == "weakening" and weakening_hit:
        return "dragon_tiger_weakening"
    elif kind == "fixed":
        return "fixed_holding_period"
    elif kind == "target":
        current_return = (close / entry_price - 1.0) * 100.0
        if current_return >= float(rule["target"]):
            return "profit_target"
        if (
            rule.get("stop") is not None
            and current_return <= -float(rule["stop"])
        ):
            return "stop_loss"
    if exit_trigger_index - entry_index >= MAX_HOLD_BARS:
        return "maximum_holding_period"
    return "rule_condition"


def joint_trade_for_setup(
    stock: Stock,
    bars: Sequence[Bar],
    points: Sequence,
    setup_index: int,
    entry_method: dict,
    exit_rule: dict,
    assumptions: ExecutionAssumptions,
    *,
    entry_result: tuple[int, float, int, float] | None = None,
) -> dict | None:
    """Run one entry and one exit through the same causal execution chain."""
    entry = entry_result or entry_for_method(
        points,
        bars,
        setup_index,
        entry_method,
        stock=stock,
        execution=assumptions,
        include_trigger=True,
    )
    if entry is None:
        return None
    entry_index, entry_effective, entry_trigger_index, entry_raw = entry
    relationship_end = risk_exit_index(
        points,
        setup_index,
        entry_index,
        exit_on_erasure=False,
        exit_on_relationship_end=(
            EXIT_ON_DRAGON_TIGER_END
            if str(exit_rule.get("id", "")) == FROZEN_EXIT_ID
            else True
        ),
        include_start=True,
    )
    erasure_end = risk_exit_index(
        points,
        setup_index,
        entry_index,
        exit_on_erasure=True,
        exit_on_relationship_end=(
            EXIT_ON_DRAGON_TIGER_END
            if str(exit_rule.get("id", "")) == FROZEN_EXIT_ID
            else True
        ),
        include_start=True,
    )
    hard_end = erasure_end if exit_rule.get("exit_on_erasure") else relationship_end
    exit_trigger_index = exit_for_rule(
        points,
        setup_index,
        entry_index,
        entry_raw,
        hard_end,
        exit_rule,
    )
    exit_fill = next_open_fill(
        stock,
        bars,
        exit_trigger_index,
        "sell",
        assumptions,
    )
    if exit_fill is None:
        return None
    exit_reason = exit_reason_for_trade(
        points,
        setup_index,
        entry_index,
        entry_raw,
        exit_trigger_index,
        exit_rule,
    )
    return {
        "setup_index": setup_index,
        "entry_area": points[setup_index].area or "base",
        "entry_trigger_index": entry_trigger_index,
        "entry_index": entry_index,
        "entry_raw_price": float(entry_raw),
        "entry_effective_price": float(entry_effective),
        "exit_trigger_index": exit_trigger_index,
        "exit_index": exit_fill.index,
        "exit_raw_price": float(exit_fill.raw_price),
        "exit_effective_price": float(exit_fill.effective_price),
        "return_pct": (exit_fill.effective_price / entry_effective - 1.0) * 100.0,
        "holding_bars": exit_fill.index - entry_index,
        "entry_deferred_bars": entry_index - entry_trigger_index - 1,
        "exit_deferred_bars": exit_fill.deferred_bars,
        "entry_method_id": str(entry_method["id"]),
        "entry_method_label": str(entry_method["label"]),
        "exit_rule_id": str(exit_rule["id"]),
        "exit_rule_label": str(exit_rule["label"]),
        "exit_reason": exit_reason,
    }


def _case_chart_payload(
    bars: Sequence[Bar],
    points: Sequence,
    start_index: int,
    end_index: int,
    *,
    signal_index: int,
    cross_date: str,
) -> dict:
    start = max(0, start_index)
    end = min(len(points) - 1, end_index)
    indices = list(range(start, end + 1))
    snapshot = CausalLineState()
    for bar in bars[: signal_index + 1]:
        snapshot.append(bar)
    chart_dragon = [
        float(snapshot.dragon[index])
        if index <= signal_index
        else float(points[index].dragon)
        for index in indices
    ]
    chart_tiger = [
        float(snapshot.tiger[index])
        if index <= signal_index
        else float(points[index].tiger)
        for index in indices
    ]
    formula_yellow_indices = {
        index
        for index, dragon in zip(indices, chart_dragon)
        if has_yellow_segment(bars[index], dragon)
    }
    cross_index = next(
        (index for index in range(0, signal_index + 1) if bars[index].date == cross_date),
        -1,
    )
    qualified_yellow_dates = []
    if cross_index >= 0:
        pair_start = max(0, cross_index - YELLOW_BEFORE_DAYS)
        pair_end = min(signal_index, cross_index + YELLOW_AFTER_DAYS)
        qualified_yellow_dates = [
            bars[index].date
            for index in range(pair_start, pair_end + 1)
            if index in formula_yellow_indices
        ]
    return {
        "bars": [
            {
                "date": bars[index].date,
                "open": round(float(bars[index].open), 4),
                "high": round(float(bars[index].high), 4),
                "low": round(float(bars[index].low), 4),
                "close": round(float(bars[index].close), 4),
            }
            for index in indices
        ],
        "wave_dragon": [round(value, 4) for value in chart_dragon],
        "wave_tiger": [round(value, 4) for value in chart_tiger],
        "yellow_dates": qualified_yellow_dates,
        "qualified_yellow_dates": qualified_yellow_dates,
        "line_semantics": (
            "信号形成日前使用信号当日可见的龙虎线历史快照，"
            "信号形成日后按每天当时可见数据逐日重算"
        ),
    }


def trade_case_payload(
    stock: Stock,
    bars: Sequence[Bar],
    points: Sequence,
    trade: dict,
    entry_method: dict,
    exit_rule: dict,
) -> dict:
    setup_index = int(trade["setup_index"])
    entry_index = int(trade["entry_index"])
    exit_index = int(trade["exit_index"])
    exit_trigger_index = int(trade["exit_trigger_index"])
    peak_index = max(
        range(entry_index, exit_trigger_index + 1),
        key=lambda index: float(points[index].close),
    )
    peak_return = (
        float(points[peak_index].close) / float(trade["entry_raw_price"]) - 1.0
    ) * 100.0
    return {
        "outcome": "trade",
        "candidate_id": f"{entry_method['id']}__{exit_rule['id']}",
        "execution_scope": EXECUTION_SCOPE,
        "code": stock.code,
        "name": stock.name,
        "source": "通达信前复权日线",
        "entry_area": points[setup_index].area,
        "cross_date": points[setup_index].cross_date,
        "signal_setup_date": points[setup_index].date,
        "signal_date": points[setup_index].date,
        "signal_price": round(float(points[setup_index].close), 4),
        "entry_trigger_date": points[int(trade["entry_trigger_index"])].date,
        "entry_date": points[entry_index].date,
        "entry_raw_open": round(float(trade["entry_raw_price"]), 4),
        "entry_price": round(float(trade["entry_effective_price"]), 6),
        "exit_trigger_date": points[exit_trigger_index].date,
        "exit_date": points[exit_index].date,
        "exit_raw_open": round(float(trade["exit_raw_price"]), 4),
        "exit_price": round(float(trade["exit_effective_price"]), 6),
        "exit_return_pct": round(float(trade["return_pct"]), 4),
        "return_pct": round(float(trade["return_pct"]), 4),
        "holding_bars": int(trade["holding_bars"]),
        "peak_date": points[peak_index].date,
        "peak_close": round(float(points[peak_index].close), 4),
        "peak_return_pct": round(peak_return, 4),
        "entry_method_id": entry_method["id"],
        "entry_rule_id": entry_method["id"],
        "entry_rule": dict(entry_method),
        "exit_rule_id": exit_rule["id"],
        "exit_rule": dict(exit_rule),
        "activation": float(exit_rule.get("activation", 0.0)),
        "drawdown": float(exit_rule.get("drawdown", 0.0)),
        "exit_reason": str(trade["exit_reason"]),
        "method": f"{entry_method['label']}；{exit_rule['label']}",
        "chart_caption": (
            f"{points[setup_index].date}收盘形成正式选区事件；"
            f"{points[int(trade['entry_trigger_index'])].date}收盘确认买点，"
            f"{points[entry_index].date}开盘按成交模型买入；"
            f"{points[exit_trigger_index].date}收盘确认卖点，"
            f"{points[exit_index].date}开盘卖出。净收益已计配置费用与滑点。"
        ),
        "case_notes": [
            "买卖点来自与全市场联合验证完全相同的逐日状态机",
            "信号触发日和实际成交日分开标注，避免把收盘后信息用于当日成交",
        ],
        **_case_chart_payload(
            bars,
            points,
            setup_index - 10,
            exit_index + 10,
            signal_index=setup_index,
            cross_date=str(points[setup_index].cross_date),
        ),
    }


def cancelled_case_payload(
    stock: Stock,
    bars: Sequence[Bar],
    points: Sequence,
    setup_index: int,
    cancel_index: int,
) -> dict:
    return {
        "outcome": "cancelled",
        "candidate_id": FROZEN_CANDIDATE_ID,
        "execution_scope": EXECUTION_SCOPE,
        "entry_rule_id": FROZEN_ENTRY_ID,
        "exit_rule_id": FROZEN_EXIT_ID,
        "code": stock.code,
        "name": stock.name,
        "source": "通达信前复权日线",
        "entry_area": points[setup_index].area,
        "cross_date": points[setup_index].cross_date,
        "signal_setup_date": points[setup_index].date,
        "signal_price": round(float(points[setup_index].close), 4),
        "cancel_date": points[cancel_index].date,
        "cancel_price": round(float(points[cancel_index].close), 4),
        "cancel_reason": "买点确认前龙腾跃虎已被逐日重算消失，候选取消且没有买卖成交",
        "chart_caption": (
            f"{points[setup_index].date}收盘首次进入{points[setup_index].area}；"
            f"{points[cancel_index].date}收盘重算后龙腾跃虎消失，"
            "状态机先取消候选，因此没有建议买点和卖点。"
        ),
        "case_notes": [
            "价格突破与信号有效性使用同一收盘快照，先校验信号再确认买点",
            "未成交案例不进入成功率、收益率或持有期统计",
        ],
        **_case_chart_payload(
            bars,
            points,
            setup_index - 10,
            cancel_index + 20,
            signal_index=setup_index,
            cross_date=str(points[setup_index].cross_date),
        ),
    }


def rally_summary(points: Sequence, indices: Sequence[int]) -> dict:
    result: dict[str, dict] = {}
    for horizon in FORWARD_HORIZONS:
        close_returns: list[float] = []
        maximum_returns: list[float] = []
        days_to_peak: list[int] = []
        for index in indices:
            if index + horizon >= len(points):
                continue
            entry = float(points[index].close)
            future = [
                (float(points[index + offset].close) / entry - 1.0) * 100.0
                for offset in range(1, horizon + 1)
            ]
            close_returns.append(future[-1])
            maximum = max(future)
            maximum_returns.append(maximum)
            days_to_peak.append(future.index(maximum) + 1)
        result[str(horizon)] = {
            "sample_count": len(close_returns),
            "end_close_average_pct": round(statistics.fmean(close_returns), 4) if close_returns else 0.0,
            "end_close_median_pct": round(statistics.median(close_returns), 4) if close_returns else 0.0,
            "end_close_positive_rate_pct": round(sum(value > 0 for value in close_returns) / len(close_returns) * 100.0, 2) if close_returns else 0.0,
            "ever_rise_rate_pct": round(sum(value > 0 for value in maximum_returns) / len(maximum_returns) * 100.0, 2) if maximum_returns else 0.0,
            "ever_reach_3pct_rate_pct": round(sum(value >= 3 for value in maximum_returns) / len(maximum_returns) * 100.0, 2) if maximum_returns else 0.0,
            "ever_reach_5pct_rate_pct": round(sum(value >= 5 for value in maximum_returns) / len(maximum_returns) * 100.0, 2) if maximum_returns else 0.0,
            "ever_reach_10pct_rate_pct": round(sum(value >= 10 for value in maximum_returns) / len(maximum_returns) * 100.0, 2) if maximum_returns else 0.0,
            "maximum_close_average_pct": round(statistics.fmean(maximum_returns), 4) if maximum_returns else 0.0,
            "maximum_close_median_pct": round(statistics.median(maximum_returns), 4) if maximum_returns else 0.0,
            "median_days_to_peak": round(statistics.median(days_to_peak), 2) if days_to_peak else 0.0,
        }
    return result


def candidate_summary(key: tuple[str, str], samples: Samples) -> dict:
    entry_id, exit_id = key
    entry = next(item for item in ENTRY_METHODS if item["id"] == entry_id)
    exit_rule = next(item for item in EXIT_RULES if item["id"] == exit_id)
    by_completed_year = {
        year: stats(
            values,
            samples.holding_by_completed_year.get(year),
        )
        for year, values in sorted(samples.by_completed_year.items())
    }
    positive_completed_years = [
        year
        for year, year_stats in by_completed_year.items()
        if float(year_stats["geometric_average_pct"]) > 0.0
    ]
    period_bucket_count = (
        len(samples.development)
        + len(samples.validation)
        + len(samples.holdout)
    )
    return {
        "id": f"{entry_id}__{exit_id}",
        "entry_id": entry_id,
        "entry_label": entry["label"],
        "exit_id": exit_id,
        "exit_label": exit_rule["label"],
        "overall": stats(samples.returns, samples.holding),
        "development_before_2024": stats(
            samples.development,
            samples.development_holding,
        ),
        "validation_2024_2025": stats(
            samples.validation,
            samples.validation_holding,
        ),
        "holdout_2026": stats(
            samples.holdout,
            samples.holdout_holding,
        ),
        "period_boundary_spanning_trade_count": (
            len(samples.returns) - period_bucket_count
        ),
        "by_completed_year": by_completed_year,
        "positive_completed_years": positive_completed_years,
        "positive_completed_year_count": len(positive_completed_years),
        "positive_completed_years_before_2026": [
            year for year in positive_completed_years if year < "2026"
        ],
        "positive_completed_year_count_before_2026": sum(
            year < "2026" for year in positive_completed_years
        ),
        "completed_year_selection_use": "report_only",
    }


def pre_holdout_sample_count(row: dict) -> int:
    return int(row["development_before_2024"]["sample_count"]) + int(
        row["validation_2024_2025"]["sample_count"]
    )


def period_floor(row: dict, key: str) -> float:
    return min(
        float(row["development_before_2024"][key]),
        float(row["validation_2024_2025"][key]),
    )


def stable_candidate_pool(rows: Sequence[dict]) -> list[dict]:
    """Freeze candidate eligibility without reading holdout/2026 fields."""
    eligible = [
        row
        for row in rows
        if pre_holdout_sample_count(row) >= 400
        and row["development_before_2024"]["sample_count"] >= 200
        and row["validation_2024_2025"]["sample_count"] >= 200
        and row["development_before_2024"]["geometric_average_pct"] > 0
        and row["validation_2024_2025"]["geometric_average_pct"] > 0
    ]
    high_sample = [row for row in rows if pre_holdout_sample_count(row) >= 400]
    return eligible or high_sample or list(rows)


def balanced_candidate(rows: Sequence[dict]) -> dict:
    stable = stable_candidate_pool(rows)
    return max(
        stable,
        key=lambda row: (
            period_floor(row, "geometric_average_pct")
            + 0.12 * (period_floor(row, "positive_rate_pct") - 50.0),
            period_floor(row, "average_excluding_abs_50pct_outliers_pct"),
            period_floor(row, "positive_rate_pct"),
            str(row["id"]),
        ),
    )


def user_long_wave_summary(rows: Sequence[dict]) -> dict:
    """Summarize the user's early-entry/long-wave idea without holdout tuning."""
    family = [
        row
        for row in rows
        if str(row["entry_id"]) in EARLY_WAVE_ENTRY_IDS
        and str(row["exit_id"]) in LONG_WAVE_EXIT_IDS
    ]
    if not family:
        return {"candidate_count": 0}
    stable = stable_candidate_pool(family)
    balanced = balanced_candidate(family)
    success_first = max(
        stable,
        key=lambda row: (
            period_floor(row, "positive_rate_pct"),
            period_floor(row, "geometric_average_pct"),
            period_floor(row, "average_excluding_abs_50pct_outliers_pct"),
        ),
    )
    return_first = max(
        stable,
        key=lambda row: (
            period_floor(row, "average_excluding_abs_50pct_outliers_pct"),
            period_floor(row, "geometric_average_pct"),
            period_floor(row, "positive_rate_pct"),
        ),
    )
    return {
        "candidate_count": len(family),
        "definition": (
            "信号形成收盘后尽早或经1至3日因果确认，于下一可交易日开盘买入；"
            "买入后信号重算消失优先卖出，其余规则跟随龙虎关系、最高收盘回撤、"
            "短中期均线与最低收盘结构判断长上涨波段结束"
        ),
        "selection_guard": (
            "仅使用2024年前开发期与2024-2025验证期选参；"
            "2026留出结果不参与资格判断或排序"
        ),
        "balanced_id": balanced["id"],
        "balanced": balanced,
        "success_first_id": success_first["id"],
        "success_first": success_first,
        "return_first_id": return_first["id"],
        "return_first": return_first,
        "top_20_by_balanced_score": sorted(
            stable,
            key=lambda row: (
                period_floor(row, "geometric_average_pct")
                + 0.12 * (period_floor(row, "positive_rate_pct") - 50.0),
                period_floor(row, "average_excluding_abs_50pct_outliers_pct"),
                period_floor(row, "positive_rate_pct"),
            ),
            reverse=True,
        )[:20],
    }


def aggregate(
    cfg: dict,
    stocks: Sequence[Stock],
    histories: Sequence[tuple[Stock, list[Bar]]],
    errors: Sequence[str],
    requested_bars: int,
    *,
    include_retrospective: bool = True,
    include_area_candidates: bool = False,
    meta: dict | None = None,
    execution: ExecutionAssumptions | None = None,
) -> dict:
    assumptions = execution or execution_assumptions(cfg)
    meta = dict(meta or {})
    live_contract = strategy_contract()
    freeze_cutoff = str(meta.get("completed_trade_date", ""))
    meta.update(
        {
            "live_strategy_id": LIVE_STRATEGY_ID,
            "frozen_candidate_id": FROZEN_CANDIDATE_ID,
            "execution_scope": EXECUTION_SCOPE,
            "live_strategy_contract": live_contract,
            "selection_policy": FORWARD_SELECTION_POLICY,
            "forward_evaluation": {
                "historical_2026_is_blind_holdout": False,
                "starts_strictly_after_completed_trade_date": freeze_cutoff,
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
        }
    )
    accumulators = {
        (entry["id"], exit_rule["id"]): CohortSamples()
        for entry in ENTRY_METHODS
        for exit_rule in EXIT_RULES
    }
    base_research_accumulators = {
        (entry["id"], exit_rule["id"]): Samples()
        for entry in ENTRY_METHODS
        for exit_rule in EXIT_RULES
    }
    base_lineage_accumulators = {
        (entry["id"], exit_rule["id"]): {
            "causal_recalculated_away": Samples(),
            "causal_persistent": Samples(),
        }
        for entry in ENTRY_METHODS
        for exit_rule in EXIT_RULES
    }
    long_wave_capture_accumulators = {
        (entry["id"], exit_rule["id"]): CohortWaveCaptureSamples()
        for entry in ENTRY_METHODS
        if str(entry["id"]) in EARLY_WAVE_ENTRY_IDS
        for exit_rule in EXIT_RULES
        if str(exit_rule["id"]) in LONG_WAVE_EXIT_IDS
    }
    representative_case: tuple[
        float,
        Stock,
        Sequence[Bar],
        Sequence,
        dict,
        dict,
        dict,
    ] | None = None
    cancelled_case: dict | None = None
    causal_rally_rows = {str(horizon): [] for horizon in FORWARD_HORIZONS}
    retrospective_rally_rows = {str(horizon): [] for horizon in FORWARD_HORIZONS}
    causal_wave_all = WaveSamples()
    causal_wave_persistent = WaveSamples()
    causal_wave_erased = WaveSamples()
    retrospective_wave = WaveSamples()
    causal_signal_count = 0
    pool_signal_count = 0
    retrospective_signal_count = 0
    common_cohort_count = 0
    common_cohort_by_area = {"main": 0, "secondary": 0}
    base_common_cohort_count = 0
    erased_count = 0
    entry_counts = {str(method["id"]): 0 for method in ENTRY_METHODS}
    base_entry_counts = {str(method["id"]): 0 for method in ENTRY_METHODS}
    base_lineage_setup_counts = {
        "causal_recalculated_away": 0,
        "causal_persistent": 0,
    }
    base_lineage_entry_counts = {
        str(method["id"]): {
            "causal_recalculated_away": 0,
            "causal_persistent": 0,
        }
        for method in ENTRY_METHODS
    }
    date_min = ""
    date_max = ""
    last_mature_signal_date = ""

    for stock_index, (stock, bars) in enumerate(histories, start=1):
        if len(bars) < int(cfg["minimum_history_bars"]):
            continue
        causal = replay_signals(
            stock,
            bars,
            cfg,
            mode="causal",
            yellow_before_days=YELLOW_BEFORE_DAYS,
            yellow_after_days=YELLOW_AFTER_DAYS,
            cross_lookback_days=CROSS_LOOKBACK_DAYS,
        )
        retrospective = (
            replay_signals(
                stock,
                bars,
                cfg,
                mode="retrospective",
                yellow_before_days=YELLOW_BEFORE_DAYS,
                yellow_after_days=YELLOW_AFTER_DAYS,
                cross_lookback_days=CROSS_LOOKBACK_DAYS,
            )
            if include_retrospective
            else []
        )
        causal_indices = signal_indices(causal, "base")
        pool_indices = signal_indices(causal, "pool")
        retrospective_indices = signal_indices(retrospective)
        causal_signal_count += len(causal_indices)
        pool_signal_count += len(pool_indices)
        retrospective_signal_count += len(retrospective_indices)

        if stock.code == "603300" and cancelled_case is None:
            hainan_setup = next(
                (
                    index
                    for index, point in enumerate(causal)
                    if point.date == "2025-02-11" and bool(point.area)
                ),
                -1,
            )
            if hainan_setup >= 0 and hainan_setup + 1 < len(causal):
                hainan_cancel = hainan_setup + 1
                if signal_erased(causal, hainan_setup, hainan_cancel):
                    cancelled_case = cancelled_case_payload(
                        stock,
                        bars,
                        causal,
                        hainan_setup,
                        hainan_cancel,
                    )

        for setup_index in causal_indices:
            all_before = len(causal_wave_all.peak_high_returns)
            measured = append_wave_sample(causal_wave_all, causal, bars, setup_index)
            if measured is None:
                continue
            was_erased, _ = measured
            peak_high_return = causal_wave_all.peak_high_returns[all_before]
            peak_close_return = causal_wave_all.peak_close_returns[all_before]
            days_to_peak = causal_wave_all.days_to_peak_high[all_before]
            wave_length = causal_wave_all.wave_lengths[all_before]
            (causal_wave_erased if was_erased else causal_wave_persistent).add(
                peak_high_return,
                peak_close_return,
                days_to_peak,
                wave_length,
            )
        for setup_index in retrospective_indices:
            append_wave_sample(retrospective_wave, retrospective, bars, setup_index)

        causal_summary = rally_summary(causal, causal_indices)
        retrospective_summary = rally_summary(retrospective, retrospective_indices)
        for horizon in FORWARD_HORIZONS:
            causal_rally_rows[str(horizon)].append(causal_summary[str(horizon)])
            retrospective_rally_rows[str(horizon)].append(retrospective_summary[str(horizon)])

        def replay_joint(
            setup_indices: Sequence[int],
            *,
            formal_pool: bool,
        ) -> None:
            nonlocal common_cohort_count, base_common_cohort_count, erased_count
            nonlocal representative_case, last_mature_signal_date
            for setup_index in setup_indices:
                if setup_index + COMMON_FUTURE_BARS >= len(causal):
                    continue
                setup_area = causal[setup_index].area if formal_pool else "base"
                remaining = max(
                    0,
                    int(causal[setup_index].cross_lookback_days)
                    - int(causal[setup_index].cross_age)
                    - 1,
                )
                was_erased = any(
                    signal_erased(causal, setup_index, index)
                    for index in range(
                        setup_index + 1,
                        min(len(causal), setup_index + remaining + 1),
                    )
                )
                if formal_pool:
                    common_cohort_count += 1
                    common_cohort_by_area[setup_area] += 1
                    last_mature_signal_date = max(
                        last_mature_signal_date,
                        str(causal[setup_index].date),
                    )
                    if was_erased:
                        erased_count += 1
                else:
                    base_common_cohort_count += 1
                    base_lineage_setup_counts[
                        "causal_recalculated_away"
                        if was_erased
                        else "causal_persistent"
                    ] += 1

                for method in ENTRY_METHODS:
                    entry = entry_for_method(
                        causal,
                        bars,
                        setup_index,
                        method,
                        stock=stock,
                        execution=assumptions,
                        include_trigger=True,
                    )
                    if entry is None:
                        continue
                    if formal_pool:
                        entry_counts[str(method["id"])] += 1
                    else:
                        base_entry_counts[str(method["id"])] += 1
                        base_lineage_entry_counts[str(method["id"])][
                            "causal_recalculated_away"
                            if was_erased
                            else "causal_persistent"
                        ] += 1
                    for exit_rule in EXIT_RULES:
                        trade = joint_trade_for_setup(
                            stock,
                            bars,
                            causal,
                            setup_index,
                            method,
                            exit_rule,
                            assumptions,
                            entry_result=entry,
                        )
                        if trade is None:
                            continue
                        key = (str(method["id"]), str(exit_rule["id"]))
                        if formal_pool:
                            accumulators[key].add(
                                float(trade["return_pct"]),
                                int(trade["holding_bars"]),
                                causal[int(trade["entry_index"])].date,
                                causal[int(trade["exit_index"])].date,
                                setup_area,
                            )
                            if key in long_wave_capture_accumulators:
                                entry_index = int(trade["entry_index"])
                                exit_trigger_index = int(trade["exit_trigger_index"])
                                pre_exit_peak_close = max(
                                    float(causal[index].close)
                                    for index in range(
                                        entry_index,
                                        exit_trigger_index + 1,
                                    )
                                )
                                relationship_end_index = risk_exit_index(
                                    causal,
                                    setup_index,
                                    entry_index,
                                    exit_on_erasure=False,
                                    include_start=True,
                                )
                                full_wave_peak_close = max(
                                    float(causal[index].close)
                                    for index in range(
                                        entry_index,
                                        relationship_end_index + 1,
                                    )
                                )
                                pre_exit_peak_close_return = (
                                    pre_exit_peak_close
                                    / float(trade["entry_raw_price"])
                                    - 1.0
                                ) * 100.0
                                full_wave_peak_close_return = (
                                    full_wave_peak_close
                                    / float(trade["entry_raw_price"])
                                    - 1.0
                                ) * 100.0
                                long_wave_capture_accumulators[key].add(
                                    float(trade["return_pct"]),
                                    pre_exit_peak_close_return,
                                    full_wave_peak_close_return,
                                    setup_area,
                                )
                        else:
                            base_research_accumulators[key].add(
                                float(trade["return_pct"]),
                                int(trade["holding_bars"]),
                                causal[int(trade["entry_index"])].date,
                                causal[int(trade["exit_index"])].date,
                            )
                            lineage_key = (
                                "causal_recalculated_away"
                                if was_erased
                                else "causal_persistent"
                            )
                            base_lineage_accumulators[key][lineage_key].add(
                                float(trade["return_pct"]),
                                int(trade["holding_bars"]),
                                causal[int(trade["entry_index"])].date,
                                causal[int(trade["exit_index"])].date,
                            )
                        if (
                            formal_pool
                            and setup_area == EXECUTION_SCOPE
                            and key == (FROZEN_ENTRY_ID, FROZEN_EXIT_ID)
                        ):
                            net_return = float(trade["return_pct"])
                            holding = int(trade["holding_bars"])
                            score = (
                                (0.0 if net_return > 0 else 100.0)
                                + abs(net_return - 15.0)
                                + abs(holding - 15) * 0.15
                            )
                            if representative_case is None or score < representative_case[0]:
                                representative_case = (
                                    score,
                                    stock,
                                    bars,
                                    causal,
                                    dict(trade),
                                    dict(method),
                                    dict(exit_rule),
                                )

        replay_joint(pool_indices, formal_pool=True)
        replay_joint(causal_indices, formal_pool=False)
        if bars:
            date_min = min(date_min or bars[0].date, bars[0].date)
            date_max = max(date_max, bars[-1].date)
        if stock_index % 250 == 0:
            print(
                f"买卖组合回放：{stock_index}/{len(histories)}，"
                f"因果信号 {causal_signal_count} 次",
                flush=True,
            )

    def combine_rally(rows: Sequence[dict]) -> dict:
        count = sum(int(row["sample_count"]) for row in rows)
        if not count:
            return {"sample_count": 0}
        weighted_keys = (
            "end_close_average_pct",
            "end_close_positive_rate_pct",
            "ever_rise_rate_pct",
            "ever_reach_3pct_rate_pct",
            "ever_reach_5pct_rate_pct",
            "ever_reach_10pct_rate_pct",
            "maximum_close_average_pct",
            "median_days_to_peak",
        )
        result = {"sample_count": count}
        for key in weighted_keys:
            result[key] = round(
                sum(float(row[key]) * int(row["sample_count"]) for row in rows)
                / count,
                4,
            )
        return result

    candidates = [
        candidate_summary(key, samples.combined)
        for key, samples in accumulators.items()
    ]
    for row in candidates:
        key = (str(row["entry_id"]), str(row["exit_id"]))
        if key in long_wave_capture_accumulators:
            row["wave_capture"] = wave_capture_stats(
                long_wave_capture_accumulators[key].combined
            )
        entry_count = int(row["overall"]["sample_count"])
        row["entry_count"] = entry_count
        row["entry_rate_pct"] = round(
            entry_count / common_cohort_count * 100.0,
            2,
        ) if common_cohort_count else 0.0
    area_candidates: dict[str, list[dict]] = {}
    for area in ("main", "secondary"):
        rows = [
            candidate_summary(key, getattr(samples, area))
            for key, samples in accumulators.items()
        ]
        denominator = common_cohort_by_area[area]
        for row in rows:
            key = (str(row["entry_id"]), str(row["exit_id"]))
            if key in long_wave_capture_accumulators:
                row["wave_capture"] = wave_capture_stats(
                    getattr(long_wave_capture_accumulators[key], area)
                )
            entry_count = int(row["overall"]["sample_count"])
            row["entry_count"] = entry_count
            row["entry_rate_pct"] = (
                round(entry_count / denominator * 100.0, 2)
                if denominator
                else 0.0
            )
        area_candidates[area] = rows
    base_candidates = [
        candidate_summary(key, samples)
        for key, samples in base_research_accumulators.items()
    ]
    for row in base_candidates:
        entry_count = int(row["overall"]["sample_count"])
        row["entry_count"] = entry_count
        row["entry_rate_pct"] = (
            round(entry_count / base_common_cohort_count * 100.0, 2)
            if base_common_cohort_count
            else 0.0
        )
    signal_close_candidates = [
        row for row in candidates if row["entry_id"] == "signal_close"
    ]
    eligible = [
        row
        for row in candidates
        if pre_holdout_sample_count(row) >= 400
        if row["development_before_2024"]["sample_count"] >= 200
        and row["validation_2024_2025"]["sample_count"] >= 200
        and row["development_before_2024"]["geometric_average_pct"] > 0
        and row["validation_2024_2025"]["geometric_average_pct"] > 0
    ]
    high_sample_candidates = [
        row
        for row in candidates
        if pre_holdout_sample_count(row) >= 400
    ] or candidates
    highest_overall = max(
        high_sample_candidates,
        key=lambda row: row["overall"]["average_pct"],
    )

    stable_pool = eligible or high_sample_candidates

    return_first = max(
        stable_pool,
        key=lambda row: (
            period_floor(row, "average_excluding_abs_50pct_outliers_pct"),
            period_floor(row, "geometric_average_pct"),
            period_floor(row, "positive_rate_pct"),
        ),
    )
    success_first = max(
        stable_pool,
        key=lambda row: (
            period_floor(row, "positive_rate_pct"),
            period_floor(row, "geometric_average_pct"),
            period_floor(row, "average_excluding_abs_50pct_outliers_pct"),
        ),
    )
    balanced = balanced_candidate(candidates)
    frozen_live = next(
        row for row in candidates if row["id"] == FROZEN_LIVE_CANDIDATE_ID
    )
    top = sorted(
        candidates,
        key=lambda row: row["overall"]["average_pct"],
        reverse=True,
    )[:30]
    top_success = sorted(
        stable_pool,
        key=lambda row: (
            period_floor(row, "positive_rate_pct"),
            period_floor(row, "geometric_average_pct"),
        ),
        reverse=True,
    )[:30]
    top_balanced = sorted(
        stable_pool,
        key=lambda row: (
            period_floor(row, "geometric_average_pct")
            + 0.12 * (period_floor(row, "positive_rate_pct") - 50.0),
            period_floor(row, "average_excluding_abs_50pct_outliers_pct"),
        ),
        reverse=True,
    )[:30]
    best_by_entry: dict[str, dict] = {}
    for entry in ENTRY_METHODS:
        entry_rows = [
            row for row in stable_pool
            if row["entry_id"] == str(entry["id"])
        ]
        if not entry_rows:
            continue
        best_by_entry[str(entry["id"])] = {
            "entry_label": str(entry["label"]),
            "entry_rate_pct": float(entry_rows[0]["entry_rate_pct"]),
            "success_first": max(
                entry_rows,
                key=lambda row: (
                    period_floor(row, "positive_rate_pct"),
                    period_floor(row, "geometric_average_pct"),
                ),
            ),
            "return_first": max(
                entry_rows,
                key=lambda row: (
                    period_floor(row, "average_excluding_abs_50pct_outliers_pct"),
                    period_floor(row, "geometric_average_pct"),
                ),
            ),
            "balanced": max(
                entry_rows,
                key=lambda row: (
                    period_floor(row, "geometric_average_pct")
                    + 0.12 * (period_floor(row, "positive_rate_pct") - 50.0),
                    period_floor(row, "positive_rate_pct"),
                ),
            ),
        }

    def summarize_cohort(
        rows: list[dict],
        setup_count: int,
        *,
        include_all: bool = False,
        frozen_id: str | None = None,
    ) -> dict:
        stable_rows = stable_candidate_pool(rows)
        selected = (
            next(row for row in rows if row["id"] == frozen_id)
            if frozen_id
            else balanced_candidate(rows)
        )
        success_choice = max(
            stable_rows,
            key=lambda row: (
                period_floor(row, "positive_rate_pct"),
                period_floor(row, "geometric_average_pct"),
            ),
        )
        return_choice = max(
            stable_rows,
            key=lambda row: (
                period_floor(row, "average_excluding_abs_50pct_outliers_pct"),
                period_floor(row, "geometric_average_pct"),
            ),
        )
        result = {
            "setup_count": setup_count,
            "candidate_count": len(rows),
            "selected_strategy_id": selected["id"],
            "selected_strategy": selected,
            "success_first_id": success_choice["id"],
            "success_first": success_choice,
            "return_first_id": return_choice["id"],
            "return_first": return_choice,
            "user_long_wave_research": user_long_wave_summary(rows),
            "top_30_by_balanced_score": sorted(
                stable_rows,
                key=lambda row: (
                    period_floor(row, "geometric_average_pct")
                    + 0.12 * (period_floor(row, "positive_rate_pct") - 50.0),
                    period_floor(row, "average_excluding_abs_50pct_outliers_pct"),
                ),
                reverse=True,
            )[:30],
        }
        if include_all:
            result["all_candidates"] = rows
        return result

    main_optimization = summarize_cohort(
        area_candidates["main"],
        common_cohort_by_area["main"],
        include_all=include_area_candidates,
        frozen_id=frozen_live["id"],
    )
    secondary_optimization = summarize_cohort(
        area_candidates["secondary"],
        common_cohort_by_area["secondary"],
        include_all=include_area_candidates,
        frozen_id=frozen_live["id"],
    )
    main_automatic = next(
        row for row in area_candidates["main"] if row["id"] == balanced["id"]
    )
    secondary_automatic = next(
        row for row in area_candidates["secondary"] if row["id"] == balanced["id"]
    )
    main_frozen_live = next(
        row
        for row in area_candidates["main"]
        if row["id"] == FROZEN_CANDIDATE_ID
    )
    secondary_frozen_live = next(
        row
        for row in area_candidates["secondary"]
        if row["id"] == FROZEN_CANDIDATE_ID
    )
    for area_summary, automatic_row in (
        (main_optimization, main_automatic),
        (secondary_optimization, secondary_automatic),
    ):
        area_summary["frozen_live_strategy_id"] = FROZEN_LIVE_STRATEGY_ID
        area_summary["frozen_candidate_id"] = FROZEN_LIVE_CANDIDATE_ID
        area_summary["frozen_live_strategy"] = area_summary["selected_strategy"]
        area_summary["automatic_recommended_id"] = balanced["id"]
        area_summary["automatic_recommended"] = automatic_row
    base_optimization = summarize_cohort(
        base_candidates,
        base_common_cohort_count,
    )
    selected_key = (
        str(frozen_live["entry_id"]),
        str(frozen_live["exit_id"]),
    )
    representative_payload = (
        trade_case_payload(
            representative_case[1],
            representative_case[2],
            representative_case[3],
            representative_case[4],
            representative_case[5],
            representative_case[6],
        )
        if representative_case is not None
        else None
    )
    cases = [representative_payload] if representative_payload is not None else []
    if cancelled_case is not None:
        cases.append(cancelled_case)
    lineage_execution = {}
    for lineage_key in ("causal_recalculated_away", "causal_persistent"):
        samples = base_lineage_accumulators[selected_key][lineage_key]
        setup_count = base_lineage_setup_counts[lineage_key]
        entry_count = base_lineage_entry_counts[str(frozen_live["entry_id"])][lineage_key]
        completed_count = len(samples.returns)
        lineage_execution[lineage_key] = {
            "setup_count": setup_count,
            "entry_filled_count": entry_count,
            "entry_fill_rate_pct": round(entry_count / setup_count * 100.0, 2)
            if setup_count else 0.0,
            "completed_trade_count": completed_count,
            "completion_rate_pct": round(completed_count / setup_count * 100.0, 2)
            if setup_count else 0.0,
            "selected_strategy_net_returns": stats(samples.returns, samples.holding),
        }
    trend_case = {
        "schema_version": 3,
        "run_id": (meta or {}).get("run_id", ""),
        "config_hash": (meta or {}).get("config_hash", ""),
        "completed_trade_date": (meta or {}).get("completed_trade_date", ""),
        "selected_strategy_id": FROZEN_LIVE_STRATEGY_ID,
        "frozen_live_strategy_id": FROZEN_LIVE_STRATEGY_ID,
        "frozen_candidate_id": FROZEN_LIVE_CANDIDATE_ID,
        "candidate_id": FROZEN_CANDIDATE_ID,
        "execution_scope": EXECUTION_SCOPE,
        "strategy_contract": live_contract,
        "entry_rule_id": FROZEN_ENTRY_ID,
        "entry_rule": dict(
            next(item for item in ENTRY_METHODS if item["id"] == FROZEN_ENTRY_ID)
        ),
        "exit_rule_id": FROZEN_EXIT_ID,
        "exit_rule": dict(
            next(item for item in EXIT_RULES if item["id"] == FROZEN_EXIT_ID)
        ),
        "activation": EXIT_PROFIT_ACTIVATION_PCT,
        "drawdown": EXIT_TRAILING_DRAWDOWN_PCT,
        "exit_reason": (
            str(representative_payload["exit_reason"])
            if representative_payload is not None
            else ""
        ),
        "automatic_recommended_id": balanced["id"],
        "primary_case": representative_payload,
        "cancelled_cases": [cancelled_case] if cancelled_case is not None else [],
        "cases": cases,
        "signal_lineage_execution": lineage_execution,
    }

    return {
        "schema_version": 3,
        "meta": meta or {},
        "run_id": (meta or {}).get("run_id", ""),
        "config_hash": (meta or {}).get("config_hash", ""),
        "completed_trade_date": (meta or {}).get("completed_trade_date", date_max),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "live_strategy": {
            **live_contract,
            "contract": live_contract,
            "status": "人工冻结；仅次选区生成买卖操作，主选区只作覆盖观察",
            "scope_policy": "secondary_only; main_coverage_observation_only",
            "metrics": secondary_frozen_live,
            "main_coverage_metrics": main_frozen_live,
            "automatic_recommended_id": balanced["id"],
            "automatic_recommended_is_live": False,
        },
        "definition": {
            "universe": "验证时仍上市的沪深A股，按当前名称排除ST与*ST",
            "signal": "逐日重算龙腾跃虎；黄柱可位于交叉前2个交易日至交叉后7个交易日，至少1根；正式事件在无选区到首次进入主选或次选时记一次，次选升级主选不重复",
            "yellow_formula": "龙线高于开盘价与收盘价中的较低者，K线实体位于龙线下方的部分显示黄色",
            "causal_basis": "每个交易日只使用当日及此前行情重算XMA，供实盘评估",
            "retrospective_basis": (
                "另用完整历史序列居中XMA复现事后图形，仅解释肉眼所见，不参与买卖规则选择"
                if include_retrospective
                else "本轮跳过；事后图形对照沿用独立完整回测，不参与买卖规则选择"
            ),
            "execution": "买卖条件均在收盘确认，下一可交易日开盘成交；一字涨停买入订单等待期间若信号消失则取消，一字跌停卖出订单持续顺延；收益已扣配置的佣金假设、经手费、证管费、卖方印花税和滑点",
            "common_trade_cohort": f"为公平比较买卖组合，只使用信号后至少仍有{COMMON_FUTURE_BARS}根K线的共同样本",
            "wave_peak": "主统计从信号条件首次同时成立日的收盘价开始，到龙线首次不再高于虎线前后的本轮波段最高价；最长观察60个交易日，最高点必须发生在信号确认后",
            "selection": FORWARD_SELECTION_POLICY,
            "live_execution_scope": (
                "冻结策略只对次选来源给出买卖操作；主选来源保留相同规则的覆盖统计，"
                "但不计入实盘建议或正式策略绩效。"
            ),
        },
        "coverage": {
            "requested_stock_count": len(stocks),
            "analyzed_stock_count": len(histories),
            "error_count": len(errors),
            "requested_bars": requested_bars,
            "start_date": date_min,
            "end_date": date_max,
        },
        "signals": {
            "causal_total_count": causal_signal_count,
            "pool_total_count": pool_signal_count,
            "retrospective_chart_total_count": retrospective_signal_count,
            "common_trade_cohort_count": common_cohort_count,
            "common_trade_cohort_by_entry_area": common_cohort_by_area,
            "last_mature_signal_date": last_mature_signal_date,
            "maturity_future_bars": COMMON_FUTURE_BARS,
            "base_research_common_trade_cohort_count": base_common_cohort_count,
            "recalculated_away_count": erased_count,
            "recalculated_away_rate_pct": round(erased_count / common_cohort_count * 100.0, 2) if common_cohort_count else 0.0,
            "entry_confirmation_counts": entry_counts,
            "base_research_entry_confirmation_counts": base_entry_counts,
        },
        "causal_forward_rally": {
            horizon: combine_rally(rows)
            for horizon, rows in causal_rally_rows.items()
        },
        "retrospective_chart_forward_rally": {
            horizon: combine_rally(rows)
            for horizon, rows in retrospective_rally_rows.items()
        },
        "signal_to_wave_peak": {
            "causal_all_signals": wave_stats(causal_wave_all),
            "causal_persistent_signals": wave_stats(causal_wave_persistent),
            "causal_recalculated_away_signals": wave_stats(causal_wave_erased),
            "retrospective_chart_signals": wave_stats(retrospective_wave),
        },
        "signal_lineage": {
            "definition": (
                "逐日实盘信号按自然显示期内是否被尾部重算消失分组；"
                "波段统计从信号后开始，买卖统计使用与正式combined相同且已冻结的联合策略。"
                "完整历史图口径只解释事后图形，不参与选参"
            ),
            "causal_recalculated_away": {
                "share_of_measured_causal_signals_pct": round(
                    len(causal_wave_erased.peak_high_returns)
                    / len(causal_wave_all.peak_high_returns)
                    * 100.0,
                    2,
                ) if causal_wave_all.peak_high_returns else 0.0,
                "wave": wave_stats(causal_wave_erased),
                "selected_strategy_execution": trend_case[
                    "signal_lineage_execution"
                ]["causal_recalculated_away"],
            },
            "causal_persistent": {
                "share_of_measured_causal_signals_pct": round(
                    len(causal_wave_persistent.peak_high_returns)
                    / len(causal_wave_all.peak_high_returns)
                    * 100.0,
                    2,
                ) if causal_wave_all.peak_high_returns else 0.0,
                "wave": wave_stats(causal_wave_persistent),
                "selected_strategy_execution": trend_case[
                    "signal_lineage_execution"
                ]["causal_persistent"],
            },
            "retrospective_chart_only": {
                "warning": "完整历史图使用事后居中XMA，仅用于解释当前图形仍可见的交叉，不参与策略选择",
                "wave": wave_stats(retrospective_wave),
            },
        },
        "optimization": {
            "candidate_count": len(candidates),
            "user_long_wave_research": user_long_wave_summary(candidates),
            "automatic_recommended_id": balanced["id"],
            "automatic_recommended": balanced,
            "frozen_live_strategy_id": FROZEN_LIVE_STRATEGY_ID,
            "frozen_candidate_id": FROZEN_LIVE_CANDIDATE_ID,
            "frozen_live_strategy": frozen_live,
            "highest_overall_average_id": highest_overall["id"],
            "stable_recommended_id": balanced["id"],
            "highest_overall_average": highest_overall,
            "stable_recommended": balanced,
            "return_first_id": return_first["id"],
            "return_first": return_first,
            "success_first_id": success_first["id"],
            "success_first": success_first,
            "balanced_id": balanced["id"],
            "balanced": balanced,
            "top_30_by_overall_average": top,
            "top_30_by_stable_success": top_success,
            "top_30_by_balanced_score": top_balanced,
            "best_by_entry": best_by_entry,
            "top_signal_close_exit_rules": sorted(
                signal_close_candidates,
                key=lambda row: row["overall"]["average_pct"],
                reverse=True,
            )[:20],
            "research_comparators": [
                row
                for row in candidates
                if row["id"] == "break_5day_high__trail_3_2"
            ],
            **({"all_candidates": candidates} if include_area_candidates else {}),
        },
        "cohorts": {
            "combined": {
                "definition": "首次进入主选区或次选区形成的研究覆盖事件；次选升级主选仍属于原交易。合计口径仅用于对照，不是冻结策略的实盘执行范围",
                "setup_count": common_cohort_count,
                "entry_area_counts": common_cohort_by_area,
                "execution_scope": "research_coverage_only",
                "live_action_enabled": False,
                "selected_strategy_id": FROZEN_LIVE_STRATEGY_ID,
                "selected_strategy": frozen_live,
                "frozen_live_strategy_id": FROZEN_LIVE_STRATEGY_ID,
                "frozen_candidate_id": FROZEN_LIVE_CANDIDATE_ID,
                "frozen_live_strategy": frozen_live,
                "automatic_recommended_id": balanced["id"],
                "automatic_recommended": balanced,
                "optimization": {
                    "candidate_count": len(candidates),
                    "user_long_wave_research": user_long_wave_summary(candidates),
                    "selected_strategy_id": FROZEN_LIVE_STRATEGY_ID,
                    "selected_strategy": frozen_live,
                    "frozen_live_strategy_id": FROZEN_LIVE_STRATEGY_ID,
                    "frozen_candidate_id": FROZEN_LIVE_CANDIDATE_ID,
                    "frozen_live_strategy": frozen_live,
                    "automatic_recommended_id": balanced["id"],
                    "automatic_recommended": balanced,
                    "success_first_id": success_first["id"],
                    "success_first": success_first,
                    "return_first_id": return_first["id"],
                    "return_first": return_first,
                    "top_30_by_balanced_score": top_balanced,
                },
            },
            "main": {
                "definition": "正式事件首次出现时即位于主选区；不含次选后的升级。仅保留冻结候选的覆盖观察统计，不生成买卖操作，也不计入正式实盘策略绩效",
                **main_optimization,
                "execution_scope": "coverage_observation_only",
                "live_action_enabled": False,
                "strategy_role": "coverage_observation",
                "selected_strategy_id": FROZEN_LIVE_STRATEGY_ID,
                "selected_strategy": main_optimization["frozen_live_strategy"],
                "optimization": main_optimization,
            },
            "secondary": {
                "definition": "正式事件首次出现时位于次选区；后续升级仍归入次选来源。冻结策略只在本口径生成买卖操作并计算正式策略绩效",
                **secondary_optimization,
                "execution_scope": EXECUTION_SCOPE,
                "live_action_enabled": True,
                "strategy_role": "live_execution",
                "selected_strategy_id": FROZEN_LIVE_STRATEGY_ID,
                "selected_strategy": secondary_optimization["frozen_live_strategy"],
                "optimization": secondary_optimization,
            },
            "base_research": {
                "definition": "仅满足龙腾跃虎与窗口黄柱的广义研究样本，不属于主选区或次选区正式绩效",
                **base_optimization,
                "optimization": base_optimization,
            },
        },
        "trend_case": trend_case,
    }


def parse_codes(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {value.strip() for value in raw.split(",") if value.strip()}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="龙腾跃虎前2日至后7日黄柱的全A股买卖优化")
    parser.add_argument("--bars", type=int, default=1600)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--codes", help="仅验证指定股票代码，逗号分隔")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--case-output",
        type=Path,
        default=ROOT / "results" / "trend_case.json",
        help="由同一状态机自动生成的合法成交/取消案例",
    )
    parser.add_argument("--completed-trade-date", help="最后完整交易日，默认读取 strategy/state.json")
    parser.add_argument("--run-id", help="与页面研究结果绑定的运行批次号")
    parser.add_argument("--commission-bps", type=float, help="券商佣金，单边基点")
    parser.add_argument("--exchange-fee-bps", type=float, help="经手费，单边基点")
    parser.add_argument("--regulatory-fee-bps", type=float, help="证管费，单边基点")
    parser.add_argument("--stamp-duty-bps", type=float, help="卖方印花税，基点")
    parser.add_argument("--slippage-bps", type=float, help="滑点，单边基点")
    parser.add_argument(
        "--entry-execution-max-wait-bars",
        type=int,
        default=ENTRY_EXECUTION_MAX_WAIT_BARS,
        help=(
            "涨停/停牌导致买不到时最多等待的交易日；正式策略固定为"
            f"{ENTRY_EXECUTION_MAX_WAIT_BARS}日"
        ),
    )
    parser.add_argument(
        "--causal-only",
        action="store_true",
        help="只重放实盘因果信号，跳过不参与规则选择的事后图形对照",
    )
    parser.add_argument(
        "--include-area-candidates",
        action="store_true",
        help="研究模式：在JSON中保留总体、主选和次选的全部候选，正式页面默认只保留精选项",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.bars < 200:
        parser.error("--bars 至少为 200")
    if args.entry_execution_max_wait_bars != ENTRY_EXECUTION_MAX_WAIT_BARS:
        parser.error(
            "--entry-execution-max-wait-bars 与冻结生产合同不一致；"
            "如需研究新值，请先建立新的策略ID和合同"
        )

    cfg = load_config(ROOT / "config.json")
    cfg["yellow_consecutive_days"] = 1
    defaults = execution_assumptions(cfg)
    assumptions = ExecutionAssumptions(
        commission_bps_per_side=(
            defaults.commission_bps_per_side
            if args.commission_bps is None
            else args.commission_bps
        ),
        exchange_fee_bps_per_side=(
            defaults.exchange_fee_bps_per_side
            if args.exchange_fee_bps is None
            else args.exchange_fee_bps
        ),
        regulatory_fee_bps_per_side=(
            defaults.regulatory_fee_bps_per_side
            if args.regulatory_fee_bps is None
            else args.regulatory_fee_bps
        ),
        stamp_duty_bps_sell=(
            defaults.stamp_duty_bps_sell
            if args.stamp_duty_bps is None
            else args.stamp_duty_bps
        ),
        slippage_bps_per_side=(
            defaults.slippage_bps_per_side
            if args.slippage_bps is None
            else args.slippage_bps
        ),
        entry_execution_max_wait_bars=ENTRY_EXECUTION_MAX_WAIT_BARS,
    )
    cutoff = args.completed_trade_date or completed_trade_date(ROOT)
    universe = [stock for stock in cached_universe() if not is_st_name(stock.name)]
    codes = parse_codes(args.codes)
    if codes:
        universe = [stock for stock in universe if stock.code in codes]
    if not universe:
        raise RuntimeError("验证股票范围为空")

    started = time.monotonic()
    histories, errors = fetch_histories(
        universe,
        args.bars,
        args.workers or int(cfg["workers"]),
    )
    histories = truncate_histories(histories, cutoff)
    meta = research_meta(
        cfg,
        cutoff,
        assumptions,
        run_id=args.run_id,
    )
    result = aggregate(
        cfg,
        universe,
        histories,
        errors,
        args.bars,
        include_retrospective=not args.causal_only,
        include_area_candidates=args.include_area_candidates,
        meta=meta,
        execution=assumptions,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.case_output.parent.mkdir(parents=True, exist_ok=True)
    args.case_output.write_text(
        json.dumps(result["trend_case"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"窗口优化完成：分析 {len(histories)}/{len(universe)} 只，"
        f"失败 {len(errors)} 只，用时 {time.monotonic() - started:.1f} 秒",
        flush=True,
    )
    print(f"结果：{args.output}", flush=True)
    print(f"案例：{args.case_output}", flush=True)
    return 1 if len(errors) > 10 else 0


if __name__ == "__main__":
    raise SystemExit(main())
