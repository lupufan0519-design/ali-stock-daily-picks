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

from rolling_validation import fetch_histories, replay_signals
from screener import Bar, Stock, cached_universe, is_st_name, load_config


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "results" / "signal_window_optimization.json"
YELLOW_BEFORE_DAYS = 2
YELLOW_AFTER_DAYS = 7
CROSS_LOOKBACK_DAYS = YELLOW_AFTER_DAYS + 1
MAX_HOLD_BARS = 60
COMMON_FUTURE_BARS = 70
FORWARD_HORIZONS = (5, 10, 20, 40, 60)


ENTRY_METHODS = (
    {"id": "signal_close", "label": "信号确认日收盘", "kind": "close", "delay": 0},
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
    for activation in (0.0, 3.0, 5.0, 8.0):
        for drawdown in (3.0, 5.0, 8.0, 10.0, 12.0, 15.0, 20.0):
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
    return tuple(rules)


EXIT_RULES = exit_rules()


@dataclass
class Samples:
    returns: array = field(default_factory=lambda: array("f"))
    holding: array = field(default_factory=lambda: array("H"))
    development: array = field(default_factory=lambda: array("f"))
    validation: array = field(default_factory=lambda: array("f"))
    holdout: array = field(default_factory=lambda: array("f"))

    def add(self, value: float, holding_bars: int, entry_date: str) -> None:
        self.returns.append(float(value))
        self.holding.append(max(0, int(holding_bars)))
        if entry_date < "2024-01-01":
            self.development.append(float(value))
        elif entry_date < "2026-01-01":
            self.validation.append(float(value))
        else:
            self.holdout.append(float(value))


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
            "p25_pct": 0.0,
            "p75_pct": 0.0,
            "average_excluding_abs_50pct_outliers_pct": 0.0,
            "median_holding_bars": 0.0,
        }
    gains = sum(value for value in numbers if value > 0)
    losses = abs(sum(value for value in numbers if value <= 0))
    regular = [value for value in numbers if abs(value) <= 50.0]
    logs = [math.log1p(value / 100.0) for value in numbers if value > -100.0]
    return {
        "sample_count": len(numbers),
        "average_pct": round(statistics.fmean(numbers), 4),
        "median_pct": round(statistics.median(numbers), 4),
        "positive_rate_pct": round(sum(value > 0 for value in numbers) / len(numbers) * 100.0, 2),
        "geometric_average_pct": round(math.expm1(statistics.fmean(logs)) * 100.0, 4) if logs else 0.0,
        "profit_factor": round(gains / losses, 4) if losses else None,
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


def signal_indices(points: Sequence) -> list[int]:
    """Record every real-time appearance, including a later reappearance."""
    indices: list[int] = []
    previous = False
    for index, point in enumerate(points):
        current = bool(point.base_signal)
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
) -> int:
    end = min(len(points) - 1, start_index + MAX_HOLD_BARS)
    for index in range(start_index + 1, end + 1):
        if exit_on_erasure and signal_erased(points, setup_index, index):
            return index
        if points[index].dragon <= points[index].tiger:
            return index
    return end


def entry_for_method(
    points: Sequence,
    bars: Sequence[Bar],
    setup_index: int,
    method: dict,
) -> tuple[int, float] | None:
    kind = str(method["kind"])
    if kind in {"close", "open"}:
        index = setup_index + int(method["delay"])
        if index >= len(points):
            return None
        for offset in range(setup_index + 1, index + 1):
            if signal_erased(points, setup_index, offset) or points[offset].dragon <= points[offset].tiger:
                return None
        price = bars[index].open if kind == "open" else points[index].close
        return (index, float(price)) if price > 0 else None

    threshold = float(method["threshold"])
    target = points[setup_index].close * (1.0 + threshold / 100.0)
    for index in range(setup_index + 1, min(len(points), setup_index + 11)):
        if signal_erased(points, setup_index, index) or points[index].dragon <= points[index].tiger:
            return None
        if points[index].close >= target:
            return index, float(points[index].close)
    return None


def weakening(points: Sequence, index: int) -> bool:
    if index < 2 or points[index].dragon <= points[index].tiger:
        return False
    latest = points[index - 2 : index + 1]
    dragons = [point.dragon for point in latest]
    spreads = [point.dragon - point.tiger for point in latest]
    return dragons[0] > dragons[1] > dragons[2] and spreads[0] > spreads[1] > spreads[2]


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
    peak_close = entry_price
    activated = float(rule.get("activation", 0.0)) <= 0
    for index in range(entry_index + 1, hard_end + 1):
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
    return hard_end


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
    return {
        "id": f"{entry_id}__{exit_id}",
        "entry_id": entry_id,
        "entry_label": entry["label"],
        "exit_id": exit_id,
        "exit_label": exit_rule["label"],
        "overall": stats(samples.returns, samples.holding),
        "development_before_2024": stats(samples.development),
        "validation_2024_2025": stats(samples.validation),
        "holdout_2026": stats(samples.holdout),
    }


def aggregate(
    cfg: dict,
    stocks: Sequence[Stock],
    histories: Sequence[tuple[Stock, list[Bar]]],
    errors: Sequence[str],
    requested_bars: int,
    *,
    include_retrospective: bool = True,
) -> dict:
    accumulators = {
        (entry["id"], exit_rule["id"]): Samples()
        for entry in ENTRY_METHODS
        for exit_rule in EXIT_RULES
    }
    causal_rally_rows = {str(horizon): [] for horizon in FORWARD_HORIZONS}
    retrospective_rally_rows = {str(horizon): [] for horizon in FORWARD_HORIZONS}
    causal_wave_all = WaveSamples()
    causal_wave_persistent = WaveSamples()
    causal_wave_erased = WaveSamples()
    retrospective_wave = WaveSamples()
    causal_signal_count = 0
    retrospective_signal_count = 0
    common_cohort_count = 0
    erased_count = 0
    entry_counts = {str(method["id"]): 0 for method in ENTRY_METHODS}
    date_min = ""
    date_max = ""

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
        causal_indices = signal_indices(causal)
        retrospective_indices = signal_indices(retrospective)
        causal_signal_count += len(causal_indices)
        retrospective_signal_count += len(retrospective_indices)

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

        for setup_index in causal_indices:
            if setup_index + COMMON_FUTURE_BARS >= len(causal):
                continue
            common_cohort_count += 1
            remaining = max(
                0,
                int(causal[setup_index].cross_lookback_days)
                - int(causal[setup_index].cross_age)
                - 1,
            )
            if any(
                signal_erased(causal, setup_index, index)
                for index in range(
                    setup_index + 1,
                    min(len(causal), setup_index + remaining + 1),
                )
            ):
                erased_count += 1
            for method in ENTRY_METHODS:
                entry = entry_for_method(causal, bars, setup_index, method)
                if entry is None:
                    continue
                entry_index, entry_price = entry
                entry_counts[str(method["id"])] += 1
                relationship_end = risk_exit_index(
                    causal,
                    setup_index,
                    entry_index,
                    exit_on_erasure=False,
                )
                erasure_end = risk_exit_index(
                    causal,
                    setup_index,
                    entry_index,
                    exit_on_erasure=True,
                )
                for exit_rule in EXIT_RULES:
                    hard_end = (
                        erasure_end
                        if exit_rule.get("exit_on_erasure")
                        else relationship_end
                    )
                    exit_index = exit_for_rule(
                        causal,
                        setup_index,
                        entry_index,
                        entry_price,
                        hard_end,
                        exit_rule,
                    )
                    exit_return = (
                        float(causal[exit_index].close) / entry_price - 1.0
                    ) * 100.0
                    accumulators[(str(method["id"]), str(exit_rule["id"]))].add(
                        exit_return,
                        exit_index - entry_index,
                        causal[entry_index].date,
                    )
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
        candidate_summary(key, samples)
        for key, samples in accumulators.items()
    ]
    signal_close_candidates = [
        row for row in candidates if row["entry_id"] == "signal_close"
    ]
    eligible = [
        row
        for row in signal_close_candidates
        if row["development_before_2024"]["sample_count"] >= 200
        and row["validation_2024_2025"]["sample_count"] >= 200
        and row["development_before_2024"]["average_pct"] > 0
        and row["validation_2024_2025"]["average_pct"] > 0
    ]
    high_sample_candidates = [
        row
        for row in signal_close_candidates
        if row["overall"]["sample_count"] >= 500
    ] or signal_close_candidates
    highest_overall = max(
        high_sample_candidates,
        key=lambda row: row["overall"]["average_pct"],
    )
    stable = max(
        eligible or high_sample_candidates,
        key=lambda row: (
            min(
                row["development_before_2024"]["average_pct"],
                row["validation_2024_2025"]["average_pct"],
            ),
            row["overall"]["average_pct"],
        ),
    )
    top = sorted(
        candidates,
        key=lambda row: row["overall"]["average_pct"],
        reverse=True,
    )[:30]

    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "definition": {
            "universe": "验证时仍上市的沪深A股，按当前名称排除ST与*ST",
            "signal": "逐日重算龙腾跃虎；黄柱可位于交叉前2个交易日至交叉后7个交易日，至少1根；每次信号从无到有均记一次",
            "yellow_formula": "龙线高于开盘价与收盘价中的较低者，K线实体位于龙线下方的部分显示黄色",
            "causal_basis": "每个交易日只使用当日及此前行情重算XMA，供实盘评估",
            "retrospective_basis": (
                "另用完整历史序列居中XMA复现事后图形，仅解释肉眼所见，不参与买卖规则选择"
                if include_retrospective
                else "本轮跳过；事后图形对照沿用独立完整回测，不参与买卖规则选择"
            ),
            "execution": "买点固定为信号条件首次同时成立日的收盘价；卖出条件按收盘确认；不计费用、滑点、停牌和涨跌停无法成交",
            "common_trade_cohort": f"为公平比较买卖组合，只使用信号后至少仍有{COMMON_FUTURE_BARS}根K线的共同样本",
            "wave_peak": "主统计从信号条件首次同时成立日的收盘价开始，到龙线首次不再高于虎线前后的本轮波段最高价；最长观察60个交易日，最高点必须发生在信号确认后",
            "selection": "买点固定为信号确认日收盘；同时要求2024年前开发样本与2024-2025验证样本平均收益为正，以两段中较低的平均收益最高者作为稳定卖出方案，2026完全留出检验",
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
            "retrospective_chart_total_count": retrospective_signal_count,
            "common_trade_cohort_count": common_cohort_count,
            "recalculated_away_count": erased_count,
            "recalculated_away_rate_pct": round(erased_count / common_cohort_count * 100.0, 2) if common_cohort_count else 0.0,
            "entry_confirmation_counts": entry_counts,
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
        "optimization": {
            "candidate_count": len(candidates),
            "highest_overall_average_id": highest_overall["id"],
            "stable_recommended_id": stable["id"],
            "highest_overall_average": highest_overall,
            "stable_recommended": stable,
            "top_30_by_overall_average": top,
            "top_signal_close_exit_rules": sorted(
                signal_close_candidates,
                key=lambda row: row["overall"]["average_pct"],
                reverse=True,
            )[:20],
        },
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
        "--causal-only",
        action="store_true",
        help="只重放实盘因果信号，跳过不参与规则选择的事后图形对照",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.bars < 200:
        parser.error("--bars 至少为 200")

    cfg = load_config(ROOT / "config.json")
    cfg["yellow_consecutive_days"] = 1
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
    result = aggregate(
        cfg,
        universe,
        histories,
        errors,
        args.bars,
        include_retrospective=not args.causal_only,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"窗口优化完成：分析 {len(histories)}/{len(universe)} 只，"
        f"失败 {len(errors)} 只，用时 {time.monotonic() - started:.1f} 秒",
        flush=True,
    )
    print(f"结果：{args.output}", flush=True)
    return 1 if len(errors) > 10 else 0


if __name__ == "__main__":
    raise SystemExit(main())
