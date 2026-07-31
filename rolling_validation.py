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
    has_yellow_segment,
    is_cross_up,
    is_st_name,
    limit_up_price,
    load_config,
    price_limit_rate,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "results" / "rolling_validation.json"
MAX_PAGE_BARS = 640
MAX_VALIDATION_ERRORS = 10


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


def replay_signals(
    stock: Stock,
    bars: Sequence[Bar],
    cfg: dict,
) -> list[SignalPoint]:
    state = CausalLineState()
    bottom_flags: list[bool] = []
    limit_flags: list[bool] = []
    points: list[SignalPoint] = []
    rate = price_limit_rate(stock)

    for index, bar in enumerate(bars):
        dragon_now, tiger_now = state.append(bar)
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

        cross_start = max(1, len(state.dragon) - cfg["cross_lookback_days"])
        cross_ok = (
            any(
                is_cross_up(state.dragon, state.tiger, signal_index)
                for signal_index in range(cross_start, len(state.dragon))
            )
            and dragon_now > tiger_now
        )
        bottom_ok = any(bottom_flags[-cfg["bottom_lookback_days"] :])
        limit_ok = any(limit_flags[-cfg["limit_up_lookback_days"] :])

        yellow_count = 0
        for line_index in range(index, -1, -1):
            if not has_yellow_segment(
                bars[line_index],
                state.dragon[line_index],
            ):
                break
            yellow_count += 1
        yellow_ok = yellow_count >= cfg["yellow_consecutive_days"]

        area = ""
        if index + 1 >= cfg["minimum_history_bars"] and bar.volume > 0:
            if bottom_ok and cross_ok and limit_ok and yellow_ok:
                area = "main"
            elif cross_ok and yellow_ok and (bottom_ok or limit_ok):
                area = "secondary"

        points.append(
            SignalPoint(
                date=bar.date,
                close=float(bar.close),
                dragon=float(dragon_now),
                tiger=float(tiger_now),
                area=area,
                endpoint_cross=(
                    index + 1 >= cfg["minimum_history_bars"]
                    and is_cross_up(
                        state.dragon,
                        state.tiger,
                        index,
                    )
                ),
            )
        )
    return points


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


def forward_returns(
    stock: Stock,
    points: Sequence[SignalPoint],
    horizons: Sequence[int] = (1, 3, 5, 10),
) -> list[dict]:
    rows: list[dict] = []
    minimum = max(horizons)
    for index, point in enumerate(points):
        if not point.endpoint_cross or index + minimum >= len(points):
            continue
        row = {
            "code": stock.code,
            "name": stock.name,
            "signal_date": point.date,
            "returns": {},
        }
        for horizon in horizons:
            row["returns"][str(horizon)] = (
                points[index + horizon].close / point.close - 1.0
            ) * 100.0
        rows.append(row)
    return rows


def _exit_trigger(
    points: Sequence[SignalPoint],
    index: int,
    rule: str,
    death_streak: int,
) -> bool:
    point = points[index]
    if rule == "death_cross_1":
        return death_streak >= 1
    if rule == "death_cross_2":
        return death_streak >= 2
    if rule == "weakening_or_cross":
        if death_streak >= 1:
            return True
        if index < 2 or point.dragon <= point.tiger:
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
) -> tuple[list[dict], list[dict]]:
    closed: list[dict] = []
    open_trades: list[dict] = []
    position: dict | None = None
    death_streak = 0
    wait_for_clear = False

    for index, point in enumerate(points):
        if position is not None:
            current_return = (
                point.close / float(position["entry_price"]) - 1.0
            ) * 100.0
            position["best_return_pct"] = max(
                float(position["best_return_pct"]),
                current_return,
            )
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
            ):
                position.update(
                    {
                        "exit_date": point.date,
                        "exit_price": point.close,
                        "return_pct": round(current_return, 4),
                        "holding_bars": index
                        - int(position["entry_index"]),
                        "peak_giveback_pct": round(
                            float(position["best_return_pct"])
                            - current_return,
                            4,
                        ),
                    }
                )
                position.pop("entry_index", None)
                closed.append(position)
                position = None
                death_streak = 0
                wait_for_clear = True
                continue

        if position is None:
            if wait_for_clear:
                if not point.area:
                    wait_for_clear = False
                continue
            if point.area:
                position = {
                    "code": stock.code,
                    "name": stock.name,
                    "entry_area": point.area,
                    "entry_date": point.date,
                    "entry_price": point.close,
                    "entry_index": index,
                    "best_return_pct": 0.0,
                    "worst_return_pct": 0.0,
                    "promoted": False,
                }
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
                "peak_giveback_pct": round(
                    float(position["best_return_pct"]) - current_return,
                    4,
                ),
            }
        )
        position.pop("entry_index", None)
        open_trades.append(position)
    return closed, open_trades


def trade_stats(closed: Sequence[dict], open_trades: Sequence[dict]) -> dict:
    returns = [float(item["return_pct"]) for item in closed]
    stats = return_stats(returns)
    stats.update(
        {
            "closed_count": len(closed),
            "open_count": len(open_trades),
            "average_holding_bars": round(
                statistics.fmean(
                    float(item["holding_bars"]) for item in closed
                ),
                2,
            )
            if closed
            else 0.0,
            "average_best_return_pct": round(
                statistics.fmean(
                    float(item["best_return_pct"]) for item in closed
                ),
                4,
            )
            if closed
            else 0.0,
            "average_worst_return_pct": round(
                statistics.fmean(
                    float(item["worst_return_pct"]) for item in closed
                ),
                4,
            )
            if closed
            else 0.0,
            "average_peak_giveback_pct": round(
                statistics.fmean(
                    float(item["peak_giveback_pct"]) for item in closed
                ),
                4,
            )
            if closed
            else 0.0,
            "promoted_count": sum(
                bool(item.get("promoted")) for item in closed
            ),
        }
    )
    return stats


def _group_forward(rows: Sequence[dict]) -> dict:
    horizons = ("1", "3", "5", "10")
    return {
        horizon: return_stats(
            [
                float(row["returns"][horizon])
                for row in rows
                if horizon in row["returns"]
            ]
        )
        for horizon in horizons
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
    trades: dict[str, dict[str, list[dict]]] = {
        rule: {"closed": [], "open": []}
        for rule in (
            "death_cross_1",
            "death_cross_2",
            "weakening_or_cross",
        )
    }
    date_min = ""
    date_max = ""
    for stock, bars in histories:
        if len(bars) < cfg["minimum_history_bars"]:
            continue
        points = replay_signals(stock, bars, cfg)
        forward_rows.extend(forward_returns(stock, points))
        for rule in trades:
            closed, open_rows = simulate_trades(stock, points, rule)
            trades[rule]["closed"].extend(closed)
            trades[rule]["open"].extend(open_rows)
        if bars:
            date_min = min(date_min or bars[0].date, bars[0].date)
            date_max = max(date_max, bars[-1].date)

    forward_by_year: dict[str, dict] = {}
    for year in sorted({row["signal_date"][:4] for row in forward_rows}):
        forward_by_year[year] = _group_forward(
            [row for row in forward_rows if row["signal_date"].startswith(year)]
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
        by_origin = {}
        for origin in ("main", "secondary"):
            origin_closed = [
                item for item in closed if item["entry_area"] == origin
            ]
            origin_open = [
                item for item in open_rows if item["entry_area"] == origin
            ]
            by_origin[origin] = trade_stats(origin_closed, origin_open)
        exit_rules[rule] = {
            "summary": trade_stats(closed, open_rows),
            "by_entry_year": by_year,
            "by_entry_area": by_origin,
        }

    return {
        "schema_version": 1,
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
            "price_basis": "通达信未复权日线收盘价",
            "universe_basis": "验证时仍上市的沪深A股，按当前名称排除ST与*ST",
            "execution_basis": "信号日收盘加入，退出信号日收盘移出，不计费用与滑点",
            "limitations": [
                "当前上市股票样本存在幸存者偏差，未包含历史退市股票",
                "历史ST名称变化未完整还原",
                "未复权价格未计入现金分红，除权事件可能影响个别样本",
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
        "cross_forward_returns": {
            "definition": "龙线在当日收盘首次上穿虎线后的第N个该股交易日收盘收益",
            "overall": _group_forward(forward_rows),
            "by_signal_year": forward_by_year,
        },
        "exit_rules": exit_rules,
        "rule_definitions": {
            "death_cross_1": "龙线首次不高于虎线，当日收盘确认趋势结束",
            "death_cross_2": "龙线连续两个交易日不高于虎线，第二日收盘确认趋势结束",
            "weakening_or_cross": (
                "龙虎差与龙线均连续两日收窄/下行时提前结束；最迟在首次死叉结束"
            ),
        },
    }


def fetch_history(
    host: str,
    stock: Stock,
    bars: int,
) -> list[Bar]:
    from xmtdx import KlineCategory, Market, TdxClient

    pages = []
    with TdxClient(host, timeout=12, auto_reconnect=True) as client:
        for start in range(0, bars, MAX_PAGE_BARS):
            count = min(MAX_PAGE_BARS, bars - start)
            page = client.get_security_bars(
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
    combined: list[Bar] = []
    seen: set[str] = set()
    for page in reversed(pages):
        for bar in page:
            if bar.date not in seen:
                combined.append(bar)
                seen.add(bar.date)
    return combined[-bars:]


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
        for item_index, stock in enumerate(group, start=1):
            try:
                history = fetch_history(host, stock, bars)
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
        return rows, failed

    histories: list[tuple[Stock, list[Bar]]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(run_group, hosts[index], group, index + 1)
            for index, group in enumerate(groups)
        ]
        for completed, future in enumerate(as_completed(futures), start=1):
            rows, failed = future.result()
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
        def retry_one(stock: Stock, start_index: int):
            last_error = ""
            for offset in range(len(hosts)):
                host = hosts[(start_index + offset) % len(hosts)]
                try:
                    history = fetch_history(host, stock, bars)
                    if history:
                        return stock, history, ""
                    last_error = f"{stock.code} EmptyHistory"
                except Exception as exc:
                    last_error = (
                        f"{stock.code} {type(exc).__name__}: {exc}"
                    )
            return stock, [], last_error

        with ThreadPoolExecutor(
            max_workers=min(worker_count, len(retry_stocks))
        ) as pool:
            futures = [
                pool.submit(retry_one, stock, index)
                for index, stock in enumerate(retry_stocks)
            ]
            for future in as_completed(futures):
                stock, history, error = future.result()
                if history:
                    histories.append((stock, history))
                else:
                    errors.append(error)
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
