from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from screener import (
    Bar,
    Stock,
    cached_universe,
    convert_bars,
    cross_yellow_pair,
    forward_adjust_bars,
    has_yellow_segment,
    is_cross_up,
    is_st_name,
    limit_up_price,
    line_series,
    load_config,
    price_limit_rate,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "results" / "rolling_validation.json"
MAX_PAGE_BARS = 640
MAX_VALIDATION_ERRORS = 10
BASE_CROSS_LOOKBACK_DAYS = 5
YELLOW_WINDOW_VARIANTS = (
    ("nearby_2", "上穿前2日至后2日", 2, 2),
    ("post_2", "上穿当天至后2日", 0, 2),
    ("post_3", "上穿当天至后3日", 0, 3),
    ("pre2_post3", "上穿前2日至后3日", 2, 3),
    ("post_5", "上穿当天至后5日", 0, 5),
    ("pre2_post5", "上穿前2日至后5日", 2, 5),
    ("post_8", "上穿当天至后8日", 0, 8),
    ("pre2_post8", "上穿前2日至后8日", 2, 8),
    ("post_10", "上穿当天至后10日", 0, 10),
    ("pre2_post10", "上穿前2日至后10日", 2, 10),
)


class CausalLineState:
    """逐日重放双重 XMA 和 EMA，任何一天都不读取其后的行情。"""

    def __init__(self, period: int = 25) -> None:
        self.period = period
        self.left = (period - 1) // 2
        self.right = period // 2
        self.alpha = 2.0 / (period + 1.0)
        self.low: list[float] = []
        self.high: list[float] = []
        self.low_prefix: list[float] = [0.0]
        self.high_prefix: list[float] = [0.0]
        self.low_first: list[float] = []
        self.high_first: list[float] = []
        self.low_second: list[float] = []
        self.high_second: list[float] = []
        self.dragon: list[float] = []
        self.tiger: list[float] = []

    @staticmethod
    def _ensure(values: list[float], length: int) -> None:
        if len(values) < length:
            values.extend(0.0 for _ in range(length - len(values)))

    def _raw_mean(
        self,
        prefix: Sequence[float],
        index: int,
        length: int,
    ) -> float:
        start = max(0, index - self.left)
        end = min(length, index + self.right + 1)
        return (prefix[end] - prefix[start]) / (end - start)

    def _recompute_second(
        self,
        first: Sequence[float],
        second: list[float],
        start: int,
        end_index: int,
    ) -> None:
        left_edge = max(0, start - self.left)
        right_edge = min(end_index + 1, start + self.right + 1)
        window_sum = sum(first[left_edge:right_edge])
        for index in range(start, end_index + 1):
            if index > start:
                new_left = max(0, index - self.left)
                new_right = min(end_index + 1, index + self.right + 1)
                while left_edge < new_left:
                    window_sum -= first[left_edge]
                    left_edge += 1
                while right_edge < new_right:
                    window_sum += first[right_edge]
                    right_edge += 1
            second[index] = window_sum / (right_edge - left_edge)

    def append(self, bar: Bar) -> tuple[float, float]:
        self.low.append(float(bar.low))
        self.high.append(float(bar.high))
        self.low_prefix.append(self.low_prefix[-1] + float(bar.low))
        self.high_prefix.append(self.high_prefix[-1] + float(bar.high))

        length = len(self.low)
        end_index = length - 1
        first_start = max(0, end_index - self.right)
        second_start = max(0, end_index - self.right * 2)
        for values in (
            self.low_first,
            self.high_first,
            self.low_second,
            self.high_second,
            self.dragon,
            self.tiger,
        ):
            self._ensure(values, length)

        for index in range(first_start, length):
            self.low_first[index] = self._raw_mean(
                self.low_prefix, index, length
            )
            self.high_first[index] = self._raw_mean(
                self.high_prefix, index, length
            )

        self._recompute_second(
            self.low_first,
            self.low_second,
            second_start,
            end_index,
        )
        self._recompute_second(
            self.high_first,
            self.high_second,
            second_start,
            end_index,
        )
        for index in range(second_start, length):
            self.dragon[index] = (
                2.0 * self.low_second[index] - self.high_second[index]
            )

        for index in range(second_start, length):
            if index == 0:
                self.tiger[index] = self.dragon[index]
            else:
                self.tiger[index] = (
                    self.alpha * self.dragon[index]
                    + (1.0 - self.alpha) * self.tiger[index - 1]
                )
        return self.dragon[-1], self.tiger[-1]


@dataclass(frozen=True)
class SignalPoint:
    date: str
    close: float
    dragon: float
    tiger: float
    area: str
    base_signal: bool
    endpoint_cross: bool


def _cci_at(bars: Sequence[Bar], index: int, period: int = 14) -> float:
    if index < period - 1:
        return math.nan
    window = [
        (bar.high + bar.low + bar.close) / 3.0
        for bar in bars[index - period + 1 : index + 1]
    ]
    mean = sum(window) / period
    deviation = sum(abs(value - mean) for value in window) / period
    if deviation == 0:
        return 0.0
    return (window[-1] - mean) / (0.015 * deviation)


def replay_signal_variants(
    stock: Stock,
    bars: Sequence[Bar],
    cfg: dict,
    *,
    variants: Sequence[tuple[str, int, int, int | None]],
    mode: str = "causal",
) -> dict[str, list[SignalPoint]]:
    if mode not in {"causal", "retrospective"}:
        raise ValueError(f"未知重放模式: {mode}")
    if not variants:
        return {}
    normalized = {
        variant_id: (
            int(before_days),
            int(after_days),
            int(cross_lookback_days)
            if cross_lookback_days is not None
            else int(cfg["cross_lookback_days"]),
        )
        for variant_id, before_days, after_days, cross_lookback_days in variants
    }
    state = CausalLineState()
    retrospective_dragon: Sequence[float] = ()
    retrospective_tiger: Sequence[float] = ()
    if mode == "retrospective":
        retrospective_dragon, retrospective_tiger = line_series(bars)
    bottom_flags: list[bool] = []
    limit_flags: list[bool] = []
    points_by_variant: dict[str, list[SignalPoint]] = {
        variant_id: [] for variant_id in normalized
    }
    rate = price_limit_rate(stock)

    for index, bar in enumerate(bars):
        if mode == "causal":
            dragon_now, tiger_now = state.append(bar)
            dragon_values = state.dragon
            tiger_values = state.tiger
        else:
            dragon_now = retrospective_dragon[index]
            tiger_now = retrospective_tiger[index]
            dragon_values = retrospective_dragon
            tiger_values = retrospective_tiger
        close_start = max(0, index - 15)
        bottom_flags.append(
            index >= 13
            and bar.close <= min(
                item.close for item in bars[close_start : index + 1]
            )
            and bar.high > bar.low + 0.04
            and _cci_at(bars, index) < -110
        )
        limit_flags.append(
            index > 0
            and bar.close + 1e-8
            >= limit_up_price(bars[index - 1].close, rate)
        )

        available_length = index + 1
        bottom_ok = any(bottom_flags[-cfg["bottom_lookback_days"] :])
        limit_ok = any(limit_flags[-cfg["limit_up_lookback_days"] :])
        shared_pair_start = min(
            max(
                0,
                index
                - effective_cross_lookback
                - before_days
                - cfg["yellow_consecutive_days"],
            )
            for before_days, _, effective_cross_lookback in normalized.values()
        )
        shared_cross_flags = [
            is_cross_up(dragon_values, tiger_values, line_index)
            if line_index > 0
            else False
            for line_index in range(shared_pair_start, index + 1)
        ]
        shared_yellow_flags = [
            has_yellow_segment(bars[line_index], dragon_values[line_index])
            for line_index in range(shared_pair_start, index + 1)
        ]
        eligible_day = (
            index + 1 >= cfg["minimum_history_bars"] and bar.volume > 0
        )
        endpoint_cross = (
            index + 1 >= cfg["minimum_history_bars"]
            and is_cross_up(dragon_values, tiger_values, index)
        )
        for variant_id, (
            before_days,
            after_days,
            effective_cross_lookback,
        ) in normalized.items():
            cross_start = max(
                1,
                available_length - effective_cross_lookback,
            )
            cross_ok = (
                any(
                    is_cross_up(dragon_values, tiger_values, signal_index)
                    for signal_index in range(cross_start, available_length)
                )
                and dragon_now > tiger_now
            )
            pair_start = max(
                0,
                index
                - effective_cross_lookback
                - before_days
                - cfg["yellow_consecutive_days"],
            )
            offset = pair_start - shared_pair_start
            pair_cross_flags = shared_cross_flags[offset:]
            pair_yellow_flags = shared_yellow_flags[offset:]
            paired_cross, _, _ = cross_yellow_pair(
                pair_cross_flags,
                pair_yellow_flags,
                end_index=len(pair_cross_flags) - 1,
                cross_lookback_days=effective_cross_lookback,
                yellow_consecutive_days=cfg["yellow_consecutive_days"],
                before_days=before_days,
                after_days=after_days,
            )
            yellow_ok = paired_cross >= 0
            base_signal = eligible_day and cross_ok and yellow_ok
            area = ""
            if eligible_day:
                if bottom_ok and cross_ok and limit_ok and yellow_ok:
                    area = "main"
                elif cross_ok and yellow_ok and (bottom_ok or limit_ok):
                    area = "secondary"
            points_by_variant[variant_id].append(
                SignalPoint(
                    date=bar.date,
                    close=float(bar.close),
                    dragon=float(dragon_now),
                    tiger=float(tiger_now),
                    area=area,
                    base_signal=base_signal,
                    endpoint_cross=endpoint_cross,
                )
            )
    return points_by_variant


def replay_signals(
    stock: Stock,
    bars: Sequence[Bar],
    cfg: dict,
    *,
    mode: str = "causal",
    yellow_before_days: int | None = None,
    yellow_after_days: int | None = None,
    cross_lookback_days: int | None = None,
) -> list[SignalPoint]:
    return replay_signal_variants(
        stock,
        bars,
        cfg,
        variants=(
            (
                "single",
                int(
                    cfg.get("yellow_before_cross_days", 2)
                    if yellow_before_days is None
                    else yellow_before_days
                ),
                int(
                    cfg.get("yellow_after_cross_days", 2)
                    if yellow_after_days is None
                    else yellow_after_days
                ),
                cross_lookback_days,
            ),
        ),
        mode=mode,
    )["single"]


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def return_stats(values: Sequence[float]) -> dict:
    numbers = [float(value) for value in values]
    if not numbers:
        return {
            "sample_count": 0,
            "average_pct": 0.0,
            "median_pct": 0.0,
            "positive_rate_pct": 0.0,
            "negative_count": 0,
            "minimum_pct": 0.0,
            "maximum_pct": 0.0,
            "p25_pct": 0.0,
            "p75_pct": 0.0,
            "outlier_count": 0,
            "average_excluding_outliers_pct": 0.0,
        }
    regular = [value for value in numbers if abs(value) <= 50.0]
    return {
        "sample_count": len(numbers),
        "average_pct": round(statistics.fmean(numbers), 4),
        "median_pct": round(statistics.median(numbers), 4),
        "positive_rate_pct": round(
            sum(value > 0 for value in numbers) / len(numbers) * 100.0,
            2,
        ),
        "negative_count": sum(value <= 0 for value in numbers),
        "minimum_pct": round(min(numbers), 4),
        "maximum_pct": round(max(numbers), 4),
        "p25_pct": round(_percentile(numbers, 0.25), 4),
        "p75_pct": round(_percentile(numbers, 0.75), 4),
        "outlier_count": len(numbers) - len(regular),
        "average_excluding_outliers_pct": round(
            statistics.fmean(regular),
            4,
        )
        if regular
        else 0.0,
    }


def base_entry_indices(points: Sequence[SignalPoint]) -> list[int]:
    indices: list[int] = []
    armed = True
    for index, point in enumerate(points):
        if point.dragon <= point.tiger:
            armed = True
        if armed and point.base_signal:
            indices.append(index)
            armed = False
    return indices


def forward_returns(
    stock: Stock,
    points: Sequence[SignalPoint],
    horizons: Sequence[int] = (1, 3, 5, 10, 20, 40, 60),
) -> list[dict]:
    rows: list[dict] = []
    for index in base_entry_indices(points):
        point = points[index]
        row = {
            "code": stock.code,
            "name": stock.name,
            "signal_date": point.date,
            "returns": {},
            "max_close_returns": {},
            "peak_days": {},
            "first_positive_days": {},
            "first_threshold_days": {},
        }
        for horizon in horizons:
            if index + horizon >= len(points):
                continue
            future_returns = [
                (points[index + offset].close / point.close - 1.0) * 100.0
                for offset in range(1, horizon + 1)
            ]
            row["returns"][str(horizon)] = (
                points[index + horizon].close / point.close - 1.0
            ) * 100.0
            maximum = max(future_returns)
            row["max_close_returns"][str(horizon)] = maximum
            row["peak_days"][str(horizon)] = future_returns.index(maximum) + 1
            positive_days = [
                offset
                for offset, value in enumerate(future_returns, start=1)
                if value > 0
            ]
            row["first_positive_days"][str(horizon)] = (
                positive_days[0] if positive_days else None
            )
            row["first_threshold_days"][str(horizon)] = {
                str(threshold): next(
                    (
                        offset
                        for offset, value in enumerate(
                            future_returns,
                            start=1,
                        )
                        if value >= threshold
                    ),
                    None,
                )
                for threshold in (3, 5, 10)
            }
        if row["returns"]:
            rows.append(row)
    return rows


TAKE_PROFIT_RULES = (
    "weakening_or_cross",
    "death_cross_1",
    "ma5_break_2",
    "trailing_5",
    "trailing_8",
    "trailing_10",
    "trailing_15",
    "trailing_20",
)


def _take_profit_trigger(
    points: Sequence[SignalPoint],
    index: int,
    entry_index: int,
    activation_index: int,
    rule: str,
    running_peak_return: float,
    current_return: float,
) -> bool:
    if index <= activation_index:
        return False
    point = points[index]
    if rule == "death_cross_1":
        return point.dragon <= point.tiger
    if rule == "weakening_or_cross":
        if point.dragon <= point.tiger:
            return True
        if index - entry_index < 2:
            return False
        spreads = [
            points[offset].dragon - points[offset].tiger
            for offset in (index - 2, index - 1, index)
        ]
        dragons = [
            points[offset].dragon
            for offset in (index - 2, index - 1, index)
        ]
        return spreads[0] > spreads[1] > spreads[2] and dragons[0] > dragons[1] > dragons[2]
    if rule.startswith("trailing_"):
        drawdown = float(rule.split("_", 1)[1])
        peak_factor = 1.0 + running_peak_return / 100.0
        current_factor = 1.0 + current_return / 100.0
        return current_factor / peak_factor - 1.0 <= -drawdown / 100.0
    if rule == "ma5_break_2":
        if index < 5 or index - 1 <= activation_index:
            return False
        current_ma = statistics.fmean(
            item.close for item in points[index - 4 : index + 1]
        )
        previous_ma = statistics.fmean(
            item.close for item in points[index - 5 : index]
        )
        return (
            points[index - 1].close < previous_ma
            and point.close < current_ma
            and current_ma < previous_ma
        )
    raise ValueError(f"未知止盈规则: {rule}")


def take_profit_rows(
    stock: Stock,
    points: Sequence[SignalPoint],
    *,
    horizon: int = 60,
    activation_threshold: float = 5.0,
) -> dict[str, list[dict]]:
    rows = {rule: [] for rule in TAKE_PROFIT_RULES}
    for entry_index in base_entry_indices(points):
        if entry_index + horizon >= len(points):
            continue
        entry = points[entry_index]
        future_returns = [
            (
                points[entry_index + offset].close / entry.close - 1.0
            )
            * 100.0
            for offset in range(1, horizon + 1)
        ]
        peak_return = max(future_returns)
        if peak_return < activation_threshold:
            continue
        peak_day = future_returns.index(peak_return) + 1
        activation_day = next(
            offset
            for offset, value in enumerate(future_returns, start=1)
            if value >= activation_threshold
        )
        activation_index = entry_index + activation_day
        for rule in TAKE_PROFIT_RULES:
            running_peak = max(future_returns[:activation_day])
            exit_day = horizon
            for offset in range(activation_day + 1, horizon + 1):
                current_return = future_returns[offset - 1]
                running_peak = max(running_peak, current_return)
                if _take_profit_trigger(
                    points,
                    entry_index + offset,
                    entry_index,
                    activation_index,
                    rule,
                    running_peak,
                    current_return,
                ):
                    exit_day = offset
                    break
            exit_return = future_returns[exit_day - 1]
            rows[rule].append(
                {
                    "code": stock.code,
                    "name": stock.name,
                    "signal_date": entry.date,
                    "activation_day": activation_day,
                    "peak_day": peak_day,
                    "peak_return_pct": peak_return,
                    "exit_day": exit_day,
                    "exit_return_pct": exit_return,
                    "peak_giveback_pct": peak_return - exit_return,
                    "exit_vs_peak_days": exit_day - peak_day,
                    "retained_peak_pct": (
                        max(0.0, exit_return) / peak_return * 100.0
                    ),
                }
            )
    return rows


def _exit_trigger(
    points: Sequence[SignalPoint],
    index: int,
    rule: str,
    death_streak: int,
    entry_index: int,
) -> bool:
    point = points[index]
    if rule == "death_cross_1":
        return death_streak >= 1
    if rule == "death_cross_2":
        return death_streak >= 2
    if rule == "weakening_or_cross":
        if death_streak >= 1:
            return True
        if index - entry_index < 2 or point.dragon <= point.tiger:
            return False
        spreads = [
            points[offset].dragon - points[offset].tiger
            for offset in (index - 2, index - 1, index)
        ]
        dragons = [
            points[offset].dragon
            for offset in (index - 2, index - 1, index)
        ]
        return (
            spreads[0] > spreads[1] > spreads[2]
            and dragons[0] > dragons[1] > dragons[2]
        )
    raise ValueError(f"未知退出规则: {rule}")


def simulate_trades(
    stock: Stock,
    points: Sequence[SignalPoint],
    rule: str,
    entry_mode: str = "pool",
) -> tuple[list[dict], list[dict]]:
    if entry_mode not in {"pool", "base"}:
        raise ValueError(f"未知入场模式: {entry_mode}")
    closed: list[dict] = []
    open_trades: list[dict] = []
    position: dict | None = None
    death_streak = 0
    wait_for_clear = False
    base_armed = True

    for index, point in enumerate(points):
        if point.dragon <= point.tiger:
            base_armed = True
        if position is not None:
            current_return = (
                point.close / float(position["entry_price"]) - 1.0
            ) * 100.0
            if current_return > float(position["best_return_pct"]):
                position["best_return_pct"] = current_return
                position["peak_index"] = index
                position["peak_date"] = point.date
            position["worst_return_pct"] = min(
                float(position["worst_return_pct"]),
                current_return,
            )
            if point.area == "main" and position["entry_area"] == "secondary":
                position["promoted"] = True
            death_streak = (
                death_streak + 1
                if point.dragon <= point.tiger
                else 0
            )
            if index > int(position["entry_index"]) and _exit_trigger(
                points,
                index,
                rule,
                death_streak,
                int(position["entry_index"]),
            ):
                position.update(
                    {
                        "exit_date": point.date,
                        "exit_price": point.close,
                        "return_pct": round(current_return, 4),
                        "holding_bars": index
                        - int(position["entry_index"]),
                        "days_to_peak": int(position["peak_index"])
                        - int(position["entry_index"]),
                        "peak_to_exit_bars": index
                        - int(position["peak_index"]),
                        "peak_giveback_pct": round(
                            float(position["best_return_pct"])
                            - current_return,
                            4,
                        ),
                    }
                )
                position.pop("entry_index", None)
                position.pop("peak_index", None)
                closed.append(position)
                position = None
                death_streak = 0
                if entry_mode == "pool":
                    wait_for_clear = True
                continue

        if position is None:
            if entry_mode == "pool" and wait_for_clear:
                if not point.area:
                    wait_for_clear = False
                continue
            should_enter = (
                bool(point.area)
                if entry_mode == "pool"
                else base_armed and point.base_signal
            )
            if should_enter:
                entry_area = point.area if entry_mode == "pool" else "base"
                position = {
                    "code": stock.code,
                    "name": stock.name,
                    "entry_area": entry_area,
                    "entry_date": point.date,
                    "entry_price": point.close,
                    "entry_index": index,
                    "best_return_pct": 0.0,
                    "worst_return_pct": 0.0,
                    "peak_index": index,
                    "peak_date": point.date,
                    "promoted": False,
                }
                if entry_mode == "base":
                    base_armed = False
                death_streak = 0

    if position is not None:
        last = points[-1]
        current_return = (
            last.close / float(position["entry_price"]) - 1.0
        ) * 100.0
        position.update(
            {
                "last_date": last.date,
                "last_close": last.close,
                "return_pct": round(current_return, 4),
                "holding_bars": len(points)
                - 1
                - int(position["entry_index"]),
                "days_to_peak": int(position["peak_index"])
                - int(position["entry_index"]),
                "peak_to_exit_bars": len(points)
                - 1
                - int(position["peak_index"]),
                "peak_giveback_pct": round(
                    float(position["best_return_pct"]) - current_return,
                    4,
                ),
            }
        )
        position.pop("entry_index", None)
        position.pop("peak_index", None)
        open_trades.append(position)
    return closed, open_trades


def trade_stats(closed: Sequence[dict], open_trades: Sequence[dict]) -> dict:
    returns = [float(item["return_pct"]) for item in closed]
    peak_returns = [float(item["best_return_pct"]) for item in closed]
    days_to_peak = [float(item["days_to_peak"]) for item in closed]
    peak_to_exit = [float(item["peak_to_exit_bars"]) for item in closed]
    holding_bars = [float(item["holding_bars"]) for item in closed]
    givebacks = [float(item["peak_giveback_pct"]) for item in closed]

    def median(values: Sequence[float]) -> float:
        return round(statistics.median(values), 2) if values else 0.0

    def rate_at_least(threshold: float) -> float:
        if not peak_returns:
            return 0.0
        return round(
            sum(value >= threshold for value in peak_returns)
            / len(peak_returns)
            * 100.0,
            2,
        )

    stats = return_stats(returns)
    stats.update(
        {
            "closed_count": len(closed),
            "open_count": len(open_trades),
            "average_holding_bars": round(statistics.fmean(holding_bars), 2)
            if holding_bars
            else 0.0,
            "median_holding_bars": median(holding_bars),
            "average_best_return_pct": round(
                statistics.fmean(peak_returns),
                4,
            )
            if peak_returns
            else 0.0,
            "median_best_return_pct": median(peak_returns),
            "rally_any_rate_pct": rate_at_least(0.000001),
            "rally_3pct_rate_pct": rate_at_least(3.0),
            "rally_5pct_rate_pct": rate_at_least(5.0),
            "rally_10pct_rate_pct": rate_at_least(10.0),
            "median_days_to_peak": median(days_to_peak),
            "p25_days_to_peak": round(_percentile(days_to_peak, 0.25), 2)
            if days_to_peak
            else 0.0,
            "p75_days_to_peak": round(_percentile(days_to_peak, 0.75), 2)
            if days_to_peak
            else 0.0,
            "median_peak_to_exit_bars": median(peak_to_exit),
            "average_worst_return_pct": round(
                statistics.fmean(
                    float(item["worst_return_pct"]) for item in closed
                ),
                4,
            )
            if closed
            else 0.0,
            "average_peak_giveback_pct": round(
                statistics.fmean(givebacks),
                4,
            )
            if givebacks
            else 0.0,
            "median_peak_giveback_pct": median(givebacks),
            "promoted_count": sum(
                bool(item.get("promoted")) for item in closed
            ),
        }
    )
    return stats


def take_profit_stats(rows: Sequence[dict]) -> dict:
    exit_returns = [float(item["exit_return_pct"]) for item in rows]
    peak_returns = [float(item["peak_return_pct"]) for item in rows]
    activation_days = [float(item["activation_day"]) for item in rows]
    peak_days = [float(item["peak_day"]) for item in rows]
    exit_days = [float(item["exit_day"]) for item in rows]
    givebacks = [float(item["peak_giveback_pct"]) for item in rows]
    timing = [float(item["exit_vs_peak_days"]) for item in rows]
    retained = [float(item["retained_peak_pct"]) for item in rows]

    def median(values: Sequence[float]) -> float:
        return round(statistics.median(values), 2) if values else 0.0

    stats = return_stats(exit_returns)
    stats.update(
        {
            "successful_trend_count": len(rows),
            "median_activation_day": median(activation_days),
            "median_peak_return_pct": median(peak_returns),
            "median_peak_day": median(peak_days),
            "p25_peak_day": round(_percentile(peak_days, 0.25), 2)
            if peak_days
            else 0.0,
            "p75_peak_day": round(_percentile(peak_days, 0.75), 2)
            if peak_days
            else 0.0,
            "median_exit_day": median(exit_days),
            "median_exit_vs_peak_days": median(timing),
            "premature_exit_rate_pct": round(
                sum(value < 0 for value in timing) / len(timing) * 100.0,
                2,
            )
            if timing
            else 0.0,
            "median_peak_giveback_pct": median(givebacks),
            "median_retained_peak_pct": median(retained),
        }
    )
    return stats


def _group_forward(rows: Sequence[dict]) -> dict:
    horizons = ("1", "3", "5", "10", "20", "40", "60")
    grouped: dict[str, dict] = {}
    for horizon in horizons:
        available = [row for row in rows if horizon in row["returns"]]
        endpoint = return_stats(
            [float(row["returns"][horizon]) for row in available]
        )
        maximums = [
            float(row["max_close_returns"][horizon]) for row in available
        ]
        positive_first_days = [
            float(row["first_positive_days"][horizon])
            for row in available
            if row["first_positive_days"][horizon] is not None
        ]
        positive_peak_days = [
            float(row["peak_days"][horizon])
            for row in available
            if float(row["max_close_returns"][horizon]) > 0
        ]
        endpoint["max_close_return"] = return_stats(maximums)
        endpoint["rally_occurrence_rate_pct"] = round(
            sum(value > 0 for value in maximums) / len(maximums) * 100.0,
            2,
        ) if maximums else 0.0
        endpoint["median_first_positive_day"] = round(
            statistics.median(positive_first_days),
            2,
        ) if positive_first_days else 0.0
        endpoint["median_positive_peak_day"] = round(
            statistics.median(positive_peak_days),
            2,
        ) if positive_peak_days else 0.0
        endpoint["p25_positive_peak_day"] = round(
            _percentile(positive_peak_days, 0.25),
            2,
        ) if positive_peak_days else 0.0
        endpoint["p75_positive_peak_day"] = round(
            _percentile(positive_peak_days, 0.75),
            2,
        ) if positive_peak_days else 0.0
        for threshold in (3, 5, 10):
            reached_days = [
                float(row["first_threshold_days"][horizon][str(threshold)])
                for row in available
                if row["first_threshold_days"][horizon][str(threshold)]
                is not None
            ]
            endpoint[f"rally_{threshold}pct_rate_pct"] = round(
                len(reached_days) / len(available) * 100.0,
                2,
            ) if available else 0.0
            endpoint[f"median_first_{threshold}pct_day"] = round(
                statistics.median(reached_days),
                2,
            ) if reached_days else 0.0
            threshold_peak_days = [
                float(row["peak_days"][horizon])
                for row in available
                if float(row["max_close_returns"][horizon]) >= threshold
            ]
            endpoint[f"median_peak_day_for_{threshold}pct"] = round(
                statistics.median(threshold_peak_days),
                2,
            ) if threshold_peak_days else 0.0
        grouped[horizon] = endpoint
    return grouped


def _yellow_window_summary(rows: Sequence[dict]) -> dict:
    development = [row for row in rows if row["signal_date"] < "2025-01-01"]
    holdout = [row for row in rows if row["signal_date"] >= "2025-01-01"]

    def sixty(items: Sequence[dict]) -> dict:
        stats = _group_forward(items)["60"]
        return {
            "sample_count": int(stats["sample_count"]),
            "rally_3pct_rate_pct": float(stats["rally_3pct_rate_pct"]),
            "rally_5pct_rate_pct": float(stats["rally_5pct_rate_pct"]),
            "rally_10pct_rate_pct": float(stats["rally_10pct_rate_pct"]),
            "median_first_5pct_day": float(stats["median_first_5pct_day"]),
            "median_peak_day_for_5pct": float(
                stats["median_peak_day_for_5pct"]
            ),
            "median_max_close_return_pct": float(
                stats["max_close_return"]["median_pct"]
            ),
        }

    overall = sixty(rows)
    development_stats = sixty(development)
    holdout_stats = sixty(holdout)
    return {
        "overall": overall,
        "development_before_2025": development_stats,
        "holdout_from_2025": holdout_stats,
        "stability_5pct_rate_pct": min(
            development_stats["rally_5pct_rate_pct"],
            holdout_stats["rally_5pct_rate_pct"],
        ),
    }


def aggregate_result(
    *,
    cfg: dict,
    requested_bars: int,
    stocks: Sequence[Stock],
    histories: Sequence[tuple[Stock, list[Bar]]],
    errors: Sequence[str],
) -> dict:
    forward_rows: list[dict] = []
    yellow_window_rows: dict[str, list[dict]] = {
        variant_id: [] for variant_id, _, _, _ in YELLOW_WINDOW_VARIANTS
    }
    variant_specs = tuple(
        (
            variant_id,
            before_days,
            after_days,
            max(BASE_CROSS_LOOKBACK_DAYS, after_days + 1),
        )
        for variant_id, _, before_days, after_days in YELLOW_WINDOW_VARIANTS
    )
    base_variant_id = next(
        (
            variant_id
            for variant_id, _, before_days, after_days in YELLOW_WINDOW_VARIANTS
            if before_days == int(cfg.get("yellow_before_cross_days", 2))
            and after_days == int(cfg.get("yellow_after_cross_days", 2))
        ),
        "nearby_2",
    )
    retrospective_forward_rows: list[dict] = []
    trades: dict[str, dict[str, list[dict]]] = {
        rule: {"closed": [], "open": []}
        for rule in (
            "death_cross_1",
            "death_cross_2",
            "weakening_or_cross",
        )
    }
    take_profit: dict[str, list[dict]] = {
        rule: [] for rule in TAKE_PROFIT_RULES
    }
    retrospective_take_profit: dict[str, list[dict]] = {
        rule: [] for rule in TAKE_PROFIT_RULES
    }
    date_min = ""
    date_max = ""
    for history_index, (stock, bars) in enumerate(histories, start=1):
        if len(bars) < cfg["minimum_history_bars"]:
            continue
        variant_points = replay_signal_variants(
            stock,
            bars,
            cfg,
            variants=variant_specs,
        )
        points = variant_points[base_variant_id]
        configured_rows: list[dict] = []
        for variant_id, rows in variant_points.items():
            variant_forward_rows = forward_returns(stock, rows)
            yellow_window_rows[variant_id].extend(variant_forward_rows)
            if variant_id == base_variant_id:
                configured_rows = variant_forward_rows
        forward_rows.extend(configured_rows)
        retrospective_points = replay_signals(
            stock,
            bars,
            cfg,
            mode="retrospective",
        )
        retrospective_forward_rows.extend(
            forward_returns(stock, retrospective_points)
        )
        for rule in trades:
            closed, open_rows = simulate_trades(
                stock,
                points,
                rule,
                entry_mode="base",
            )
            trades[rule]["closed"].extend(closed)
            trades[rule]["open"].extend(open_rows)
        profit_rows = take_profit_rows(stock, points)
        for rule, rows in profit_rows.items():
            take_profit[rule].extend(rows)
        retrospective_profit_rows = take_profit_rows(
            stock,
            retrospective_points,
        )
        for rule, rows in retrospective_profit_rows.items():
            retrospective_take_profit[rule].extend(rows)
        if bars:
            date_min = min(date_min or bars[0].date, bars[0].date)
            date_max = max(date_max, bars[-1].date)
        if history_index % 500 == 0:
            print(
                f"黄柱窗口比较：{history_index}/{len(histories)}",
                flush=True,
            )

    yellow_window_analysis = []
    for variant_id, label, before_days, after_days in YELLOW_WINDOW_VARIANTS:
        summary = _yellow_window_summary(yellow_window_rows[variant_id])
        yellow_window_analysis.append(
            {
                "id": variant_id,
                "label": label,
                "yellow_before_days": before_days,
                "yellow_after_days": after_days,
                "cross_lookback_days": max(
                    BASE_CROSS_LOOKBACK_DAYS,
                    after_days + 1,
                ),
                **summary,
            }
        )
    recommended_window = max(
        yellow_window_analysis,
        key=lambda item: (
            item["stability_5pct_rate_pct"],
            item["holdout_from_2025"]["sample_count"],
            item["overall"]["sample_count"],
        ),
    )

    forward_by_year: dict[str, dict] = {}
    for year in sorted({row["signal_date"][:4] for row in forward_rows}):
        forward_by_year[year] = _group_forward(
            [row for row in forward_rows if row["signal_date"].startswith(year)]
        )
    retrospective_forward_by_year: dict[str, dict] = {}
    for year in sorted(
        {row["signal_date"][:4] for row in retrospective_forward_rows}
    ):
        retrospective_forward_by_year[year] = _group_forward(
            [
                row
                for row in retrospective_forward_rows
                if row["signal_date"].startswith(year)
            ]
        )

    exit_rules: dict[str, dict] = {}
    for rule, rows in trades.items():
        closed = rows["closed"]
        open_rows = rows["open"]
        by_year = {}
        for year in sorted({item["entry_date"][:4] for item in closed}):
            year_rows = [
                item
                for item in closed
                if item["entry_date"].startswith(year)
            ]
            by_year[year] = trade_stats(year_rows, [])
        exit_rules[rule] = {
            "summary": trade_stats(closed, open_rows),
            "by_entry_year": by_year,
        }

    take_profit_rules: dict[str, dict] = {}
    for rule, rows in take_profit.items():
        by_year = {}
        for year in sorted({item["signal_date"][:4] for item in rows}):
            by_year[year] = take_profit_stats(
                [
                    item
                    for item in rows
                    if item["signal_date"].startswith(year)
                ]
            )
        take_profit_rules[rule] = {
            "summary": take_profit_stats(rows),
            "by_signal_year": by_year,
        }

    retrospective_take_profit_rules: dict[str, dict] = {}
    for rule, rows in retrospective_take_profit.items():
        by_year = {}
        for year in sorted({item["signal_date"][:4] for item in rows}):
            by_year[year] = take_profit_stats(
                [
                    item
                    for item in rows
                    if item["signal_date"].startswith(year)
                ]
            )
        retrospective_take_profit_rules[rule] = {
            "summary": take_profit_stats(rows),
            "by_signal_year": by_year,
        }

    return {
        "schema_version": 4,
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "method": {
            "name": "逐日无未来数据滚动重放",
            "requested_bars": requested_bars,
            "minimum_history_bars": cfg["minimum_history_bars"],
            "signal_calculation": (
                "每个交易日只用当日及此前数据重算双重XMA与虎线EMA"
            ),
            "price_basis": "通达信日线按最新除权除息记录前复权",
            "universe_basis": "验证时仍上市的沪深A股，按当前名称排除ST与*ST",
            "execution_basis": "信号日收盘加入，退出信号日收盘移出，不计费用与滑点",
            "entry_definition": (
                f"近{cfg['cross_lookback_days']}个交易日发生龙线上穿虎线、当前龙线仍高于虎线，且上穿日前"
                f"{cfg.get('yellow_before_cross_days', 2)}日至后{cfg.get('yellow_after_cross_days', 2)}日内黄柱满足配置阈值；"
                "同一轮龙线位于虎线上方期间只记录首次同时满足日，不要求见底或42日涨停"
            ),
            "peak_definition": "信号启动后至首次死叉前后的最高收盘价",
            "limitations": [
                "当前上市股票样本存在幸存者偏差，未包含历史退市股票",
                "历史ST名称变化未完整还原",
                "除权除息记录按验证日可取得的最新记录统一前复权",
                "涨跌停无法成交、停牌、滑点和手续费未纳入",
            ],
        },
        "coverage": {
            "requested_stock_count": len(stocks),
            "analyzed_stock_count": len(histories),
            "error_count": len(errors),
            "start_date": date_min,
            "end_date": date_max,
        },
        "yellow_window_analysis": {
            "selection_rule": (
                "优先比较2025年前开发样本与2025年起留出样本的60日达到5%比例，"
                "以两段中较低者衡量稳定性；同分时优先样本更多的方案"
            ),
            "recommended_id": recommended_window["id"],
            "variants": yellow_window_analysis,
        },
        "base_signal_forward_returns": {
            "definition": (
                f"龙腾跃虎与上穿前{cfg.get('yellow_before_cross_days', 2)}日至后{cfg.get('yellow_after_cross_days', 2)}日内黄柱完成配对后，"
                "分别统计未来N个交易日内的最高收盘涨幅、"
                "首次上涨日和第N日收盘收益；同一轮龙虎多头周期不重复计数"
            ),
            "overall": _group_forward(forward_rows),
            "by_signal_year": forward_by_year,
        },
        "wave_analysis": {
            "definition": "从基础启动信号到龙线首次不高于虎线的一段完整行情",
            "summary": exit_rules["death_cross_1"]["summary"],
            "by_entry_year": exit_rules["death_cross_1"]["by_entry_year"],
        },
        "take_profit_analysis": {
            "definition": (
                "基础信号后60个交易日内最高收盘涨幅达到5%视为形成可止盈上涨趋势；"
                "达到5%后才启用止盈规则，并与60日内阶段最高收盘价比较"
            ),
            "activation_threshold_pct": 5.0,
            "forward_horizon_bars": 60,
            "rules": take_profit_rules,
        },
        "retrospective_chart_analysis": {
            "warning": (
                "使用完整历史序列的居中XMA复现行情软件事后图形；历史信号会被后续行情重绘，"
                "包含未来数据，只用于解释图形，不能作为可实时执行的成功率"
            ),
            "forward_returns": {
                "overall": _group_forward(retrospective_forward_rows),
                "by_signal_year": retrospective_forward_by_year,
            },
            "take_profit": {
                "activation_threshold_pct": 5.0,
                "forward_horizon_bars": 60,
                "rules": retrospective_take_profit_rules,
            },
        },
        "exit_rules": exit_rules,
        "rule_definitions": {
            "death_cross_1": "龙线首次不高于虎线，当日收盘确认趋势结束",
            "death_cross_2": "龙线连续两个交易日不高于虎线，第二日收盘确认趋势结束",
            "weakening_or_cross": (
                "启动后龙虎差与龙线均连续两个交易日收窄/下行时提前结束；最迟在首次死叉结束"
            ),
            "ma5_break_2": "达到5%后，连续两个交易日收盘低于5日均线且5日均线下行",
            "trailing_5": "达到5%后，收盘价较持有期最高收盘回撤5%",
            "trailing_8": "达到5%后，收盘价较持有期最高收盘回撤8%",
            "trailing_10": "达到5%后，收盘价较持有期最高收盘回撤10%",
            "trailing_15": "达到5%后，收盘价较持有期最高收盘回撤15%",
            "trailing_20": "达到5%后，收盘价较持有期最高收盘回撤20%",
        },
    }


def fetch_history(
    host: str,
    stock: Stock,
    bars: int,
    client=None,
) -> list[Bar]:
    from xmtdx import KlineCategory, Market, TdxClient

    def load(active_client) -> list[Bar]:
        pages = []
        for start in range(0, bars, MAX_PAGE_BARS):
            count = min(MAX_PAGE_BARS, bars - start)
            page = active_client.get_security_bars(
                Market(stock.market),
                stock.code,
                KlineCategory.DAY,
                start,
                count,
            )
            if not page:
                break
            pages.append(convert_bars(page))
            if len(page) < count:
                break
        xdxr = active_client.get_xdxr_info(
            Market(stock.market),
            stock.code,
        )
        combined: list[Bar] = []
        seen: set[str] = set()
        for page in reversed(pages):
            for bar in page:
                if bar.date not in seen:
                    combined.append(bar)
                    seen.add(bar.date)
        return forward_adjust_bars(combined[-bars:], xdxr)

    if client is not None:
        return load(client)
    with TdxClient(host, timeout=12, auto_reconnect=True) as active_client:
        return load(active_client)


def fetch_histories(
    stocks: Sequence[Stock],
    bars: int,
    workers: int,
) -> tuple[list[tuple[Stock, list[Bar]]], list[str]]:
    from xmtdx import TdxClient

    ranked = TdxClient.ping_all(timeout=2.5)
    if not ranked:
        raise RuntimeError("无法连接通达信行情服务器")
    hosts = [host for host, _ in ranked]
    worker_count = min(max(1, workers), len(hosts), len(stocks))
    groups = [list(stocks[index::worker_count]) for index in range(worker_count)]

    def run_group(host: str, group: Sequence[Stock], group_index: int):
        rows: list[tuple[Stock, list[Bar]]] = []
        failed: list[str] = []
        with TdxClient(host, timeout=12, auto_reconnect=True) as client:
            for item_index, stock in enumerate(group, start=1):
                try:
                    history = fetch_history(
                        host,
                        stock,
                        bars,
                        client=client,
                    )
                    if history:
                        rows.append((stock, history))
                    else:
                        failed.append(f"{stock.code} EmptyHistory")
                except Exception as exc:
                    failed.append(
                        f"{stock.code} {type(exc).__name__}: {exc}"
                    )
                if item_index % 100 == 0:
                    print(
                        f"历史行情分组 {group_index}/{worker_count}："
                        f"{item_index}/{len(group)}",
                        flush=True,
                    )
        return host, rows, failed

    histories: list[tuple[Stock, list[Bar]]] = []
    errors: list[str] = []
    failed_hosts: set[str] = set()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(run_group, hosts[index], group, index + 1)
            for index, group in enumerate(groups)
        ]
        for completed, future in enumerate(as_completed(futures), start=1):
            host, rows, failed = future.result()
            if groups and failed and not rows:
                failed_hosts.add(host)
            histories.extend(rows)
            errors.extend(failed)
            print(
                f"历史行情进度 {completed}/{worker_count}；"
                f"已取得 {len(histories)} 只，失败 {len(errors)} 只",
                flush=True,
            )

    if errors:
        failed_codes = {line.split(" ", 1)[0] for line in errors}
        retry_stocks = [
            stock for stock in stocks if stock.code in failed_codes
        ]
        errors = []
        retry_hosts = [host for host in hosts if host not in failed_hosts] or hosts
        retry_worker_count = min(len(retry_hosts), len(retry_stocks))
        retry_groups = [
            retry_stocks[index::retry_worker_count]
            for index in range(retry_worker_count)
        ]

        def retry_group(host: str, group: Sequence[Stock]):
            rows: list[tuple[Stock, list[Bar]]] = []
            failed: list[str] = []
            with TdxClient(host, timeout=12, auto_reconnect=True) as client:
                for stock in group:
                    try:
                        history = fetch_history(host, stock, bars, client=client)
                        if history:
                            rows.append((stock, history))
                        else:
                            failed.append(f"{stock.code} EmptyHistory")
                    except Exception as exc:
                        failed.append(
                            f"{stock.code} {type(exc).__name__}: {exc}"
                        )
            return rows, failed

        with ThreadPoolExecutor(max_workers=retry_worker_count) as pool:
            futures = [
                pool.submit(retry_group, retry_hosts[index], group)
                for index, group in enumerate(retry_groups)
            ]
            for future in as_completed(futures):
                rows, failed = future.result()
                histories.extend(rows)
                errors.extend(failed)
    unique = {(stock.market, stock.code): (stock, bars_) for stock, bars_ in histories}
    return list(unique.values()), errors


def parse_codes(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {value.strip() for value in raw.split(",") if value.strip()}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="卢氏龙虎策略历史滚动验证"
    )
    parser.add_argument("--bars", type=int, default=640)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--codes", help="仅验证指定股票代码，逗号分隔")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.bars < 120:
        parser.error("--bars 至少为 120")

    cfg = load_config(ROOT / "config.json")
    universe = cached_universe()
    if not universe:
        raise RuntimeError("缺少 cache/universe.json，请先运行一次完整扫描")
    universe = [stock for stock in universe if not is_st_name(stock.name)]
    codes = parse_codes(args.codes)
    if codes:
        universe = [stock for stock in universe if stock.code in codes]
    if not universe:
        raise RuntimeError("验证股票范围为空")

    started = time.monotonic()
    histories, errors = fetch_histories(
        universe,
        args.bars,
        args.workers or cfg["workers"],
    )
    result = aggregate_result(
        cfg=cfg,
        requested_bars=args.bars,
        stocks=universe,
        histories=histories,
        errors=errors,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"滚动验证完成：分析 {len(histories)}/{len(universe)} 只，"
        f"失败 {len(errors)} 只，用时 {time.monotonic() - started:.1f} 秒",
        flush=True,
    )
    print(f"结果：{args.output}", flush=True)
    if len(errors) > MAX_VALIDATION_ERRORS:
        print(
            f"失败 {len(errors)} 只，超过可发布上限 "
            f"{MAX_VALIDATION_ERRORS}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"滚动验证失败：{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
