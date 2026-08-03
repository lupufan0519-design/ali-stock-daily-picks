from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from rolling_validation import fetch_histories, replay_signals
from screener import Bar, Stock, cached_universe, is_st_name, load_config
from signal_window_optimization import (
    COMMON_FUTURE_BARS,
    CROSS_LOOKBACK_DAYS,
    MAX_HOLD_BARS,
    Samples,
    WaveSamples,
    exit_for_rule,
    risk_exit_index,
    signal_indices,
    stats,
    wave_stats,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "results" / "signal_repaint_comparison.json"
YELLOW_BEFORE_DAYS = 2
YELLOW_AFTER_DAYS = 7


EXIT_POLICIES = (
    {
        "id": "erasure_or_relationship",
        "label": "信号重算消失或龙线不再高于虎线时卖出",
        "kind": "relationship",
        "exit_on_erasure": True,
    },
    {
        "id": "relationship",
        "label": "龙线不再高于虎线时卖出，最长60日",
        "kind": "relationship",
    },
    {
        "id": "hold_20",
        "label": "最多持有20日，龙线不再高于虎线则提前卖出",
        "kind": "fixed",
        "bars": 20,
    },
    {
        "id": "hold_40",
        "label": "最多持有40日，龙线不再高于虎线则提前卖出",
        "kind": "fixed",
        "bars": 40,
    },
    {
        "id": "trail_8_3",
        "label": "浮盈达到8%后较最高收盘回撤3%卖出，最迟龙虎关系结束或60日",
        "kind": "trailing",
        "activation": 8.0,
        "drawdown": 3.0,
    },
)
ENTRY_DELAYS = (0, 1, 2, 3, 5)


@dataclass
class Cohort:
    waves: WaveSamples = field(default_factory=WaveSamples)
    trades: dict[str, Samples] = field(default_factory=dict)
    signal_count: int = 0
    excluded_nonpositive_price_count: int = 0


def measurement(
    points: Sequence,
    bars: Sequence[Bar],
    setup_index: int,
) -> dict | None:
    if setup_index + MAX_HOLD_BARS >= len(points):
        return None
    end_index = setup_index + MAX_HOLD_BARS
    for index in range(setup_index + 1, end_index + 1):
        if points[index].dragon <= points[index].tiger:
            end_index = index
            break
    future = range(setup_index + 1, end_index + 1)
    entry = float(points[setup_index].close)
    if entry <= 0 or any(
        float(bars[index].high) <= 0 or float(points[index].close) <= 0
        for index in future
    ):
        return {"excluded_nonpositive_price": True}
    peak_high_index = max(future, key=lambda index: float(bars[index].high))
    peak_close_index = max(future, key=lambda index: float(points[index].close))
    return {
        "end_index": end_index,
        "peak_high_index": peak_high_index,
        "peak_close_index": peak_close_index,
        "peak_high_return_pct": (
            float(bars[peak_high_index].high) / entry - 1.0
        ) * 100.0,
        "peak_close_return_pct": (
            float(points[peak_close_index].close) / entry - 1.0
        ) * 100.0,
    }


def add_wave(cohort: Cohort, measured: dict, setup_index: int) -> None:
    if measured.get("excluded_nonpositive_price"):
        cohort.excluded_nonpositive_price_count += 1
        return
    cohort.signal_count += 1
    cohort.waves.add(
        measured["peak_high_return_pct"],
        measured["peak_close_return_pct"],
        measured["peak_high_index"] - setup_index,
        measured["end_index"] - setup_index,
    )


def entry_after_confirmation(
    points: Sequence,
    setup_index: int,
    delay: int,
) -> tuple[int, float] | None:
    entry_index = setup_index + delay
    if entry_index >= len(points):
        return None
    for index in range(setup_index, entry_index + 1):
        if not points[index].base_signal:
            return None
        if points[index].dragon <= points[index].tiger:
            return None
    price = float(points[entry_index].close)
    return (entry_index, price) if price > 0 else None


def policy_key(delay: int, policy: dict) -> str:
    return f"confirm_{delay}_close__{policy['id']}"


def add_trades(
    cohort: Cohort,
    points: Sequence,
    setup_index: int,
) -> None:
    for delay in ENTRY_DELAYS:
        entry = entry_after_confirmation(points, setup_index, delay)
        if entry is None:
            continue
        entry_index, entry_price = entry
        if entry_price <= 0:
            continue
        relationship_end = risk_exit_index(
            points,
            setup_index,
            entry_index,
            exit_on_erasure=False,
        )
        erasure_end = risk_exit_index(
            points,
            setup_index,
            entry_index,
            exit_on_erasure=True,
        )
        for policy in EXIT_POLICIES:
            hard_end = (
                erasure_end
                if policy.get("exit_on_erasure")
                else relationship_end
            )
            exit_index = exit_for_rule(
                points,
                setup_index,
                entry_index,
                entry_price,
                hard_end,
                policy,
            )
            if float(points[exit_index].close) <= 0:
                continue
            key = policy_key(delay, policy)
            samples = cohort.trades.setdefault(key, Samples())
            samples.add(
                (float(points[exit_index].close) / entry_price - 1.0)
                * 100.0,
                exit_index - entry_index,
                points[entry_index].date,
            )


def candidate_rows(cohort: Cohort) -> list[dict]:
    rows: list[dict] = []
    for delay in ENTRY_DELAYS:
        for policy in EXIT_POLICIES:
            key = policy_key(delay, policy)
            samples = cohort.trades.get(key, Samples())
            rows.append(
                {
                    "id": key,
                    "entry_label": (
                        "信号首次确认日收盘"
                        if delay == 0
                        else f"信号连续保持{delay + 1}个收盘日后买入"
                    ),
                    "entry_delay_bars": delay,
                    "exit_label": policy["label"],
                    "entry_count": len(samples.returns),
                    "entry_rate_pct": round(
                        len(samples.returns) / cohort.signal_count * 100.0,
                        2,
                    ) if cohort.signal_count else 0.0,
                    "overall": stats(samples.returns, samples.holding),
                    "development_before_2024": stats(samples.development),
                    "validation_2024_2025": stats(samples.validation),
                    "holdout_2026": stats(samples.holdout),
                }
            )
    return rows


def choose_candidates(rows: Sequence[dict]) -> dict:
    eligible = [
        row
        for row in rows
        if row["entry_count"] >= 500
        and row["development_before_2024"]["sample_count"] >= 200
        and row["validation_2024_2025"]["sample_count"] >= 200
    ]
    pool = eligible or [row for row in rows if row["entry_count"] >= 100]
    if not pool:
        return {}
    positive_stable = [
        row
        for row in pool
        if row["development_before_2024"]["average_pct"] > 0
        and row["validation_2024_2025"]["average_pct"] > 0
    ]
    stable_pool = positive_stable or pool
    highest_average = max(pool, key=lambda row: row["overall"]["average_pct"])
    stable_average = max(
        stable_pool,
        key=lambda row: (
            min(
                row["development_before_2024"]["average_pct"],
                row["validation_2024_2025"]["average_pct"],
            ),
            row["overall"]["average_pct"],
        ),
    )
    positive_average = [
        row for row in pool if row["overall"]["average_pct"] > 0
    ] or pool
    highest_success = max(
        positive_average,
        key=lambda row: (
            row["overall"]["positive_rate_pct"],
            row["overall"]["median_pct"],
            row["overall"]["average_pct"],
        ),
    )
    return {
        "highest_average": highest_average,
        "stable_average": stable_average,
        "highest_success_with_positive_average": highest_success,
        "top_15_by_average": sorted(
            rows,
            key=lambda row: row["overall"]["average_pct"],
            reverse=True,
        )[:15],
    }


def failure_example(
    stock: Stock,
    points: Sequence,
    bars: Sequence[Bar],
    setup_index: int,
    measured: dict,
) -> dict:
    end_index = int(measured["end_index"])
    peak_index = int(measured["peak_high_index"])
    relationship_ended = points[end_index].dragon <= points[end_index].tiger
    return {
        "code": stock.code,
        "name": stock.name,
        "signal_date": points[setup_index].date,
        "cross_date": points[setup_index].cross_date,
        "signal_close": round(float(points[setup_index].close), 4),
        "later_wave_high_date": bars[peak_index].date,
        "later_wave_high": round(float(bars[peak_index].high), 4),
        "peak_high_return_pct": round(
            float(measured["peak_high_return_pct"]), 4
        ),
        "observation_end_date": points[end_index].date,
        "observation_end_reason": (
            "龙线不再高于虎线"
            if relationship_ended
            else f"达到{MAX_HOLD_BARS}日观察上限"
        ),
        "observation_end_return_pct": round(
            (float(points[end_index].close) / float(points[setup_index].close) - 1.0)
            * 100.0,
            4,
        ),
    }


def aggregate(
    cfg: dict,
    stocks: Sequence[Stock],
    histories: Sequence[tuple[Stock, list[Bar]]],
    errors: Sequence[str],
    requested_bars: int,
) -> dict:
    causal_all = Cohort()
    causal_disappeared = Cohort()
    causal_cross_retained = Cohort()
    final_chart = Cohort()
    final_failures: list[dict] = []
    angang_check: dict = {}
    causal_raw_count = 0
    disappeared_raw_count = 0
    retained_raw_count = 0
    final_chart_raw_count = 0
    date_min = ""
    date_max = ""

    for stock_index, (stock, bars) in enumerate(histories, start=1):
        causal = replay_signals(
            stock,
            bars,
            cfg,
            mode="causal",
            yellow_before_days=YELLOW_BEFORE_DAYS,
            yellow_after_days=YELLOW_AFTER_DAYS,
            cross_lookback_days=CROSS_LOOKBACK_DAYS,
        )
        retrospective = replay_signals(
            stock,
            bars,
            cfg,
            mode="retrospective",
            yellow_before_days=YELLOW_BEFORE_DAYS,
            yellow_after_days=YELLOW_AFTER_DAYS,
            cross_lookback_days=CROSS_LOOKBACK_DAYS,
        )
        date_to_index = {point.date: index for index, point in enumerate(causal)}

        for setup_index in signal_indices(causal):
            if setup_index + COMMON_FUTURE_BARS >= len(causal):
                continue
            causal_raw_count += 1
            measured = measurement(causal, bars, setup_index)
            if measured is None:
                continue
            add_wave(causal_all, measured, setup_index)
            cross_index = date_to_index.get(causal[setup_index].cross_date, -1)
            retained = bool(
                cross_index >= 0 and retrospective[cross_index].endpoint_cross
            )
            target = causal_cross_retained if retained else causal_disappeared
            if retained:
                retained_raw_count += 1
            else:
                disappeared_raw_count += 1
            add_wave(target, measured, setup_index)
            if measured.get("excluded_nonpositive_price"):
                continue
            add_trades(causal_all, causal, setup_index)
            add_trades(target, causal, setup_index)
            if stock.code == "000898" and causal[setup_index].date == "2026-03-20":
                angang_check = {
                    "causal_signal_seen_on_2026_03_20": True,
                    "causal_cross_date": causal[setup_index].cross_date,
                    "cross_survives_in_final_chart": retained,
                    "final_chart_signal_on_2026_03_20": retrospective[
                        setup_index
                    ].base_signal,
                }

        for setup_index in signal_indices(retrospective):
            if setup_index + COMMON_FUTURE_BARS >= len(retrospective):
                continue
            final_chart_raw_count += 1
            measured = measurement(retrospective, bars, setup_index)
            if measured is None:
                continue
            add_wave(final_chart, measured, setup_index)
            if measured.get("excluded_nonpositive_price"):
                continue
            add_trades(final_chart, retrospective, setup_index)
            if measured["peak_high_return_pct"] <= 0.000001:
                final_failures.append(
                    failure_example(
                        stock,
                        retrospective,
                        bars,
                        setup_index,
                        measured,
                    )
                )

        if bars:
            date_min = min(date_min or bars[0].date, bars[0].date)
            date_max = max(date_max, bars[-1].date)
        if stock_index % 250 == 0:
            print(
                f"重绘分类：{stock_index}/{len(histories)}，"
                f"实时信号{causal_all.signal_count}次，"
                f"最终图信号{final_chart.signal_count}次",
                flush=True,
            )

    causal_rows = candidate_rows(causal_all)
    final_rows = candidate_rows(final_chart)
    final_failures.sort(
        key=lambda row: (row["signal_date"], row["code"]),
        reverse=True,
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "definition": {
            "signal": "龙腾跃虎交叉前2日至后7日内至少出现1根黄柱，每次信号从无到有分别统计",
            "disappeared": "截至某日曾出现的交叉，在加入后续K线并按完整历史XMA重算后，同一交叉日期不再存在",
            "cross_retained": "截至某日曾出现的交叉，在当前完整历史图的同一日期仍存在",
            "final_chart": "当前完整历史图中最终仍存在的全部交叉信号；含未来重绘信息，只作历史形态验证，不是当时可知信号",
            "success": "信号确认日收盘后，到龙虎关系结束或最长60日，后续最高价高于信号确认价",
            "realized_return": "买卖均按收盘确认，不计费用、滑点、停牌及涨跌停无法成交",
        },
        "coverage": {
            "requested_stock_count": len(stocks),
            "analyzed_stock_count": len(histories),
            "error_count": len(errors),
            "requested_bars": requested_bars,
            "start_date": date_min,
            "end_date": date_max,
        },
        "causal_live_signals": {
            "total": causal_raw_count,
            "evaluable_positive_price_count": causal_all.signal_count,
            "excluded_nonpositive_adjusted_price_count": causal_all.excluded_nonpositive_price_count,
            "disappeared_count": disappeared_raw_count,
            "disappeared_rate_pct": round(
                disappeared_raw_count / causal_raw_count * 100.0,
                2,
            ) if causal_raw_count else 0.0,
            "cross_retained_count": retained_raw_count,
            "cross_retained_rate_pct": round(
                retained_raw_count / causal_raw_count * 100.0,
                2,
            ) if causal_raw_count else 0.0,
            "all_wave": wave_stats(causal_all.waves),
            "disappeared_wave": wave_stats(causal_disappeared.waves),
            "cross_retained_wave": wave_stats(causal_cross_retained.waves),
            "all_executable_strategy_comparison": {
                "candidate_count": len(causal_rows),
                **choose_candidates(causal_rows),
            },
            "disappeared_strategy_rows": candidate_rows(causal_disappeared),
            "cross_retained_strategy_rows": candidate_rows(causal_cross_retained),
        },
        "final_chart_signals": {
            "total": final_chart_raw_count,
            "evaluable_positive_price_count": final_chart.signal_count,
            "excluded_nonpositive_adjusted_price_count": final_chart.excluded_nonpositive_price_count,
            "wave": wave_stats(final_chart.waves),
            "hindsight_strategy_comparison": {
                "warning": "使用完整历史图信号，买点当时不可知，只能解释形态，不能作为实盘收益承诺",
                "candidate_count": len(final_rows),
                **choose_candidates(final_rows),
            },
            "strict_failure_count": len(final_failures),
            "strict_failure_examples": final_failures[:100],
        },
        "angang_000898_check": angang_check,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="XMA临时信号与最终历史图信号分类回测")
    parser.add_argument("--bars", type=int, default=1600)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--codes", help="仅验证指定股票代码，逗号分隔")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(list(argv) if argv is not None else None)

    cfg = load_config(ROOT / "config.json")
    cfg["yellow_consecutive_days"] = 1
    universe = [stock for stock in cached_universe() if not is_st_name(stock.name)]
    if args.codes:
        codes = {code.strip() for code in args.codes.split(",") if code.strip()}
        universe = [stock for stock in universe if stock.code in codes]
    if not universe:
        raise RuntimeError("验证股票范围为空")

    started = time.monotonic()
    histories, errors = fetch_histories(
        universe,
        args.bars,
        args.workers or int(cfg["workers"]),
    )
    payload = aggregate(cfg, universe, histories, errors, args.bars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"重绘分类完成：分析{len(histories)}/{len(universe)}只，"
        f"失败{len(errors)}只，用时{time.monotonic() - started:.1f}秒",
        flush=True,
    )
    print(f"结果：{args.output}", flush=True)
    return 1 if len(errors) > 10 else 0


if __name__ == "__main__":
    raise SystemExit(main())
