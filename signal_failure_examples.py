from __future__ import annotations

import argparse
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from rolling_validation import fetch_histories, replay_signals
from screener import (
    Bar,
    Stock,
    cached_universe,
    cross_yellow_pair,
    has_yellow_segment,
    is_cross_up,
    is_st_name,
    line_series,
    load_config,
)
from signal_window_optimization import (
    COMMON_FUTURE_BARS,
    CROSS_LOOKBACK_DAYS,
    MAX_HOLD_BARS,
    YELLOW_AFTER_DAYS,
    YELLOW_BEFORE_DAYS,
    risk_exit_index,
    signal_indices,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "results" / "signal_failure_examples.json"


def evidence_dates(
    bars: Sequence[Bar],
    setup_index: int,
    *,
    mode: str,
) -> tuple[str, str]:
    line_bars = bars if mode == "retrospective" else bars[: setup_index + 1]
    dragon, tiger = line_series(line_bars)
    cross_flags = [
        is_cross_up(dragon, tiger, index) for index in range(len(line_bars))
    ]
    yellow_flags = [
        has_yellow_segment(bar, dragon[index])
        for index, bar in enumerate(line_bars)
    ]
    cross_index, yellow_index, _ = cross_yellow_pair(
        cross_flags,
        yellow_flags,
        end_index=setup_index,
        cross_lookback_days=CROSS_LOOKBACK_DAYS,
        yellow_consecutive_days=1,
        before_days=YELLOW_BEFORE_DAYS,
        after_days=YELLOW_AFTER_DAYS,
    )
    return (
        bars[cross_index].date if cross_index >= 0 else "",
        bars[yellow_index].date if yellow_index >= 0 else "",
    )


def failure_rows(
    histories: Sequence[tuple[Stock, list[Bar]]],
    cfg: dict,
    *,
    mode: str,
) -> tuple[list[dict], int, int]:
    rows: list[dict] = []
    completed_signal_count = 0
    excluded_nonpositive_price_count = 0
    for stock, bars in histories:
        points = replay_signals(
            stock,
            bars,
            cfg,
            mode=mode,
            yellow_before_days=YELLOW_BEFORE_DAYS,
            yellow_after_days=YELLOW_AFTER_DAYS,
            cross_lookback_days=CROSS_LOOKBACK_DAYS,
        )
        for setup_index in signal_indices(points):
            if setup_index + COMMON_FUTURE_BARS >= len(points):
                continue
            completed_signal_count += 1
            relationship_end = risk_exit_index(
                points,
                setup_index,
                setup_index,
                exit_on_erasure=False,
            )
            future = range(setup_index + 1, relationship_end + 1)
            entry = float(points[setup_index].close)
            if entry <= 0 or any(
                float(bars[index].high) <= 0
                or float(points[index].close) <= 0
                for index in future
            ):
                excluded_nonpositive_price_count += 1
                continue
            peak_index = max(future, key=lambda index: float(bars[index].high))
            peak_return = (float(bars[peak_index].high) / entry - 1.0) * 100.0
            if peak_return > 0.000001:
                continue
            stable_exit = min(relationship_end, setup_index + 20)
            cross_date, yellow_date = evidence_dates(
                bars,
                setup_index,
                mode=mode,
            )
            relationship_ended = (
                points[relationship_end].dragon <= points[relationship_end].tiger
            )
            rows.append(
                {
                    "code": stock.code,
                    "name": stock.name,
                    "market": "沪" if stock.market == 1 else "深",
                    "signal_date": points[setup_index].date,
                    "cross_date": cross_date or points[setup_index].cross_date,
                    "yellow_date": yellow_date,
                    "signal_close": round(entry, 4),
                    "later_wave_high_date": bars[peak_index].date,
                    "later_wave_high": round(float(bars[peak_index].high), 4),
                    "peak_high_return_pct": round(peak_return, 4),
                    "observation_end_date": points[relationship_end].date,
                    "observation_end_reason": (
                        "龙线不再高于虎线"
                        if relationship_ended
                        else f"达到{MAX_HOLD_BARS}日观察上限"
                    ),
                    "observation_end_close": round(
                        float(points[relationship_end].close), 4
                    ),
                    "observation_end_return_pct": round(
                        (float(points[relationship_end].close) / entry - 1.0)
                        * 100.0,
                        4,
                    ),
                    "stable_20d_exit_date": points[stable_exit].date,
                    "stable_20d_return_pct": round(
                        (float(points[stable_exit].close) / entry - 1.0) * 100.0,
                        4,
                    ),
                    "wave_length_bars": relationship_end - setup_index,
                }
            )
    return rows, completed_signal_count, excluded_nonpositive_price_count


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="提取信号后未创新高的可核对案例")
    parser.add_argument("--bars", type=int, default=1600)
    parser.add_argument(
        "--sample-size",
        type=int,
        default=0,
        help="0表示全部当前非ST沪深A股；正数表示固定随机抽样",
    )
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--max-examples", type=int, default=30)
    parser.add_argument(
        "--mode",
        choices=("retrospective", "causal"),
        default="retrospective",
        help="retrospective匹配当前完整历史图；causal保留当时出现后又可能消失的临时信号",
    )
    parser.add_argument("--workers", type=int)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(list(argv) if argv is not None else None)

    cfg = load_config(ROOT / "config.json")
    cfg["yellow_consecutive_days"] = 1
    universe = [stock for stock in cached_universe() if not is_st_name(stock.name)]
    if args.sample_size <= 0 or args.sample_size >= len(universe):
        sample = universe
        sample_method = "全部当前非ST沪深A股"
    else:
        sample = random.Random(args.seed).sample(universe, args.sample_size)
        sample_method = (
            f"从当前非ST沪深A股中按固定随机种子{args.seed}"
            f"抽取{args.sample_size}只"
        )
    sample_size = len(sample)
    histories, errors = fetch_histories(
        sample,
        args.bars,
        args.workers or int(cfg["workers"]),
    )
    rows, completed_signal_count, excluded_nonpositive_price_count = failure_rows(
        histories,
        cfg,
        mode=args.mode,
    )
    rows.sort(key=lambda row: (row["signal_date"], row["code"]), reverse=True)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "definition": "信号确认后，到龙线首次不再高于虎线或最长60个交易日为止，后续最高价仍不高于信号日收盘价",
        "signal_basis": (
            "完整历史序列重算后的最终图形信号，匹配当前通达信历史图"
            if args.mode == "retrospective"
            else "截至每个交易日重算的临时信号，后续可能因XMA重绘而消失"
        ),
        "mode": args.mode,
        "sample_method": sample_method,
        "requested_stock_count": sample_size,
        "analyzed_stock_count": len(histories),
        "error_count": len(errors),
        "completed_signal_count": completed_signal_count,
        "evaluable_positive_price_count": (
            completed_signal_count - excluded_nonpositive_price_count
        ),
        "excluded_nonpositive_adjusted_price_count": excluded_nonpositive_price_count,
        "failure_count": len(rows),
        "failure_rate_pct": round(
            len(rows)
            / (completed_signal_count - excluded_nonpositive_price_count)
            * 100.0,
            4,
        ) if completed_signal_count > excluded_nonpositive_price_count else 0.0,
        "examples": rows[: max(1, args.max_examples)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"分析{len(histories)}/{sample_size}只，找到{len(rows)}个失败信号，"
        f"输出{len(payload['examples'])}例",
        flush=True,
    )
    return 1 if len(errors) > 10 else 0


if __name__ == "__main__":
    raise SystemExit(main())
