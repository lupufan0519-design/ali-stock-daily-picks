from __future__ import annotations

import argparse
import csv
import html
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Sequence

from strategy_tracker import (
    POOL_NAME,
    bootstrap_state,
    load_state,
    replay_state,
    save_state,
    secondary_strategy_stats,
    strategy_stats,
    update_state,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"
OUTPUT_DIR = ROOT / "results"
CACHE_DIR = ROOT / "cache"
UNIVERSE_CACHE = CACHE_DIR / "universe.json"
STRATEGY_DIR = ROOT / "strategy"
STRATEGY_STATE_PATH = STRATEGY_DIR / "state.json"
FINAL_INDIVIDUAL_RETRY_LIMIT = 200
FINAL_RETRY_TIME_BUDGET_SECONDS = 600
MAX_UNRESOLVED_ERRORS = 10


@dataclass(frozen=True)
class Stock:
    market: int
    code: str
    name: str


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float


@dataclass
class Evaluation:
    code: str
    name: str
    market: int
    date: str
    close: float
    change_pct: float
    bottom_ok: bool
    cross_ok: bool
    limit_up_ok: bool
    yellow_ok: bool
    bottom_date: str
    cross_date: str
    limit_up_date: str
    yellow_count: int
    matched_count: int
    dragon_above_tiger: bool
    eligible: bool
    selected: bool
    chart: str


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    required = {
        "bottom_lookback_days",
        "cross_lookback_days",
        "limit_up_lookback_days",
        "yellow_consecutive_days",
        "history_bars",
        "minimum_history_bars",
        "workers",
        "include_st",
        "near_match_minimum",
    }
    missing = required.difference(cfg)
    if missing:
        raise ValueError(f"配置缺少字段: {', '.join(sorted(missing))}")
    for key in required - {"include_st"}:
        if not isinstance(cfg[key], int) or cfg[key] <= 0:
            raise ValueError(f"配置 {key} 必须是正整数")
    if cfg["minimum_history_bars"] > cfg["history_bars"]:
        raise ValueError("minimum_history_bars 不能大于 history_bars")
    return cfg


def ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for value in values[1:]:
        out.append(alpha * float(value) + (1.0 - alpha) * out[-1])
    return out


def xma(values: Sequence[float], period: int) -> list[float]:
    """通达信 XMA：居中窗口，序列两端按实际可用数据缩短窗口。"""
    if not values:
        return []
    left = (period - 1) // 2
    right = period // 2
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + float(value))
    out: list[float] = []
    for i in range(len(values)):
        start = max(0, i - left)
        end = min(len(values), i + right + 1)
        out.append((prefix[end] - prefix[start]) / (end - start))
    return out


def rolling_cci(bars: Sequence[Bar], period: int = 14) -> list[float]:
    typical = [(b.high + b.low + b.close) / 3.0 for b in bars]
    out = [math.nan] * len(bars)
    for i in range(period - 1, len(bars)):
        window = typical[i - period + 1 : i + 1]
        mean = sum(window) / period
        dev = sum(abs(x - mean) for x in window) / period
        out[i] = 0.0 if dev == 0 else (typical[i] - mean) / (0.015 * dev)
    return out


def line_series(bars: Sequence[Bar]) -> tuple[list[float], list[float]]:
    low2 = xma(xma([b.low for b in bars], 25), 25)
    high2 = xma(xma([b.high for b in bars], 25), 25)
    dragon = [2.0 * low - high for low, high in zip(low2, high2)]
    tiger = ema(dragon, 25)
    return dragon, tiger


def has_yellow_segment(bar: Bar, dragon_value: float) -> bool:
    """K 线实体下沿位于龙线下方时，即出现黄色部分。"""
    return dragon_value > min(bar.open, bar.close)


def is_cross_up(a: Sequence[float], b: Sequence[float], i: int) -> bool:
    return i > 0 and a[i] > b[i] and a[i - 1] <= b[i - 1]


def latest_true_date(flags: Sequence[bool], bars: Sequence[Bar], lookback: int) -> str:
    start = max(0, len(flags) - lookback)
    for i in range(len(flags) - 1, start - 1, -1):
        if flags[i]:
            return bars[i].date
    return ""


def is_st_name(name: str) -> bool:
    return "ST" in name.upper()


def price_limit_rate(stock: Stock) -> Decimal:
    upper_name = stock.name.upper()
    if is_st_name(upper_name):
        return Decimal("0.05")
    if stock.market == 2:
        return Decimal("0.30")
    if stock.code.startswith(("30", "68")):
        return Decimal("0.20")
    return Decimal("0.10")


def limit_up_price(previous_close: float, rate: Decimal) -> float:
    price = Decimal(str(previous_close)) * (Decimal("1") + rate)
    return float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def make_sparkline(bars: Sequence[Bar], dragon: Sequence[float], tiger: Sequence[float]) -> str:
    count = min(42, len(bars))
    bars = bars[-count:]
    dragon = dragon[-count:]
    tiger = tiger[-count:]
    lo = min(min(b.low for b in bars), min(dragon), min(tiger))
    hi = max(max(b.high for b in bars), max(dragon), max(tiger))
    span = hi - lo or 1.0
    width, height = 420, 176
    left, right, top, bottom = 8, 50, 10, 24
    plot_width = width - left - right
    plot_height = height - top - bottom
    step = plot_width / max(1, count - 1)
    candle_width = max(2.5, min(6.2, step * 0.62))

    def x_at(index: int) -> float:
        return left + index * step

    def y_at(value: float) -> float:
        return top + (hi - value) * plot_height / span

    def points(values: Sequence[float]) -> str:
        return " ".join(
            f"{x_at(i):.1f},{y_at(value):.1f}"
            for i, value in enumerate(values)
        )

    grid = []
    for fraction in (0.0, 0.5, 1.0):
        value = hi - span * fraction
        y = y_at(value)
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right + 4}" y2="{y:.1f}" '
            f'stroke="#263348" stroke-width="1" stroke-dasharray="3 3"/>'
            f'<text x="{width - right + 8}" y="{y + 3.5:.1f}" fill="#91a0b5" font-size="10">{value:.2f}</text>'
        )

    candles = []
    for i, (bar, dragon_value) in enumerate(zip(bars, dragon)):
        is_yellow = has_yellow_segment(bar, dragon_value)
        is_full_yellow = dragon_value > bar.high
        normal_color = "#ff5c70" if bar.close >= bar.open else "#4dd599"
        color = "#f4d35e" if is_full_yellow else normal_color
        x = x_at(i)
        open_y, close_y = y_at(bar.open), y_at(bar.close)
        body_y = min(open_y, close_y)
        body_height = max(1.5, abs(close_y - open_y))
        yellow_part = ""
        if is_yellow and not is_full_yellow:
            body_low = min(bar.open, bar.close)
            body_high = max(bar.open, bar.close)
            yellow_top = min(dragon_value, body_high)
            yellow_y = y_at(yellow_top)
            yellow_height = max(1.5, y_at(body_low) - yellow_y)
            yellow_part = (
                f'<rect class="yellow-part" x="{x - candle_width / 2:.1f}" y="{yellow_y:.1f}" '
                f'width="{candle_width:.1f}" height="{yellow_height:.1f}" fill="#f4d35e" rx="0.5"/>'
            )
        tooltip = (
            f"{bar.date} 开{bar.open:.2f} 高{bar.high:.2f} "
            f"低{bar.low:.2f} 收{bar.close:.2f}"
            f"{' 黄柱' if is_yellow else ''}"
        )
        candles.append(
            f'<g class="kbar {"yellow" if is_yellow else "normal"}"><title>{tooltip}</title>'
            f'<line x1="{x:.1f}" y1="{y_at(bar.high):.1f}" x2="{x:.1f}" y2="{y_at(bar.low):.1f}" '
            f'stroke="{color}" stroke-width="1"/>'
            f'<rect x="{x - candle_width / 2:.1f}" y="{body_y:.1f}" width="{candle_width:.1f}" '
            f'height="{body_height:.1f}" fill="{color}" rx="0.5"/>{yellow_part}</g>'
        )

    start_label = bars[0].date[5:]
    end_label = bars[-1].date[5:]
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="最近{count}日K线、龙线和虎线">'
        f'{"".join(grid)}{"".join(candles)}'
        f'<polyline points="{points(dragon)}" fill="none" stroke="#ff5c70" stroke-width="2" stroke-linejoin="round"/>'
        f'<polyline points="{points(tiger)}" fill="none" stroke="#55c6e8" stroke-width="2" stroke-linejoin="round"/>'
        f'<text x="{left}" y="{height - 5}" fill="#91a0b5" font-size="10">{start_label}</text>'
        f'<text x="{width - right}" y="{height - 5}" fill="#91a0b5" font-size="10" text-anchor="end">{end_label}</text>'
        f'</svg>'
    )


def evaluate(stock: Stock, bars: Sequence[Bar], cfg: dict) -> Evaluation | None:
    as_of_date = cfg.get("_as_of_date")
    if as_of_date:
        bars = [bar for bar in bars if bar.date <= as_of_date]
    if len(bars) < cfg["minimum_history_bars"] or bars[-1].volume <= 0:
        return None
    eligible = bool(cfg["include_st"] or not is_st_name(stock.name))

    dragon, tiger = line_series(bars)
    cci = rolling_cci(bars)
    close = [b.close for b in bars]

    bottom_flags: list[bool] = []
    for i, bar in enumerate(bars):
        start = max(0, i - 15)
        is_new_low = bar.close <= min(close[start : i + 1])
        bottom_flags.append(
            i >= 13 and is_new_low and bar.high > bar.low + 0.04 and cci[i] < -110
        )

    cross_flags = [is_cross_up(dragon, tiger, i) for i in range(len(bars))]
    rate = price_limit_rate(stock)
    limit_flags = [False]
    for i in range(1, len(bars)):
        limit_flags.append(bars[i].close + 1e-8 >= limit_up_price(bars[i - 1].close, rate))
    # 对齐原公式：K 线实体只要有一部分位于龙线下方，就计为黄柱。
    yellow_flags = [has_yellow_segment(bar, value) for value, bar in zip(dragon, bars)]

    bottom_date = latest_true_date(
        bottom_flags, bars, cfg["bottom_lookback_days"]
    )
    cross_date = latest_true_date(cross_flags, bars, cfg["cross_lookback_days"])
    limit_date = latest_true_date(
        limit_flags, bars, cfg["limit_up_lookback_days"]
    )
    yellow_count = 0
    for flag in reversed(yellow_flags):
        if not flag:
            break
        yellow_count += 1

    bottom_ok = bool(bottom_date)
    cross_ok = bool(cross_date) and dragon[-1] > tiger[-1]
    limit_ok = bool(limit_date)
    yellow_ok = yellow_count >= cfg["yellow_consecutive_days"]
    matched = sum((bottom_ok, cross_ok, limit_ok, yellow_ok))
    previous = bars[-2].close if len(bars) > 1 else bars[-1].close
    change_pct = (bars[-1].close / previous - 1.0) * 100.0 if previous else 0.0

    return Evaluation(
        code=stock.code,
        name=stock.name,
        market=stock.market,
        date=bars[-1].date,
        close=bars[-1].close,
        change_pct=change_pct,
        bottom_ok=bottom_ok,
        cross_ok=cross_ok,
        limit_up_ok=limit_ok,
        yellow_ok=yellow_ok,
        bottom_date=bottom_date,
        cross_date=cross_date,
        limit_up_date=limit_date,
        yellow_count=yellow_count,
        matched_count=matched,
        dragon_above_tiger=dragon[-1] > tiger[-1],
        eligible=eligible,
        selected=eligible and matched == 4,
        chart=make_sparkline(bars, dragon, tiger),
    )


def fetch_security_page(host: str, market: int, start: int):
    from xmtdx import Market, TdxClient

    with TdxClient(host, timeout=8, auto_reconnect=False) as client:
        return client.get_security_list(Market(market), start)


def tdx_universe(hosts: Sequence[str], workers: int) -> list[Stock]:
    from xmtdx import Market, TdxClient

    counts: dict[int, int] = {}
    for i, market in enumerate((Market.SH, Market.SZ)):
        with TdxClient(hosts[i % len(hosts)], timeout=8) as client:
            counts[int(market)] = client.get_security_count(market)

    pages = [
        (int(market), start)
        for market, total in counts.items()
        for start in range(0, total, 1000)
    ]
    universe: list[Stock] = []
    with ThreadPoolExecutor(max_workers=min(max(workers * 2, 4), 10)) as pool:
        futures = {
            pool.submit(fetch_security_page, hosts[i % len(hosts)], market, start): market
            for i, (market, start) in enumerate(pages)
        }
        for future in as_completed(futures):
            market = futures[future]
            for item in future.result():
                if market == int(Market.SH):
                    is_a = item.code.startswith(("60", "68"))
                else:
                    is_a = item.code.startswith(("00", "30"))
                if is_a:
                    universe.append(Stock(market, item.code, item.name.strip()))
    unique = {(s.market, s.code): s for s in universe}
    return sorted(unique.values(), key=lambda s: (s.market, s.code))


def cached_universe() -> list[Stock]:
    if not UNIVERSE_CACHE.exists():
        return []
    try:
        data = json.loads(UNIVERSE_CACHE.read_text(encoding="utf-8"))
        return [Stock(int(x["market"]), str(x["code"]), str(x["name"])) for x in data]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def reliable_universe(hosts: Sequence[str], workers: int) -> list[Stock]:
    minimum_expected = 5000
    cache = cached_universe()
    universe: list[Stock] = []
    for _ in range(1 if len(cache) >= minimum_expected else 3):
        try:
            universe = tdx_universe(hosts, workers)
        except Exception:
            continue
        if len(universe) >= minimum_expected:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            UNIVERSE_CACHE.write_text(
                json.dumps([asdict(x) for x in universe], ensure_ascii=False),
                encoding="utf-8",
            )
            return universe
    if len(cache) >= minimum_expected:
        print("实时股票名单不完整，已使用最近一次完整缓存", flush=True)
        return cache
    raise RuntimeError(f"股票名单仅取得 {len(universe)} 只，未达到完整性校验")


def convert_bars(items) -> list[Bar]:
    return [
        Bar(
            date=f"{x.year:04d}-{x.month:02d}-{x.day:02d}",
            open=float(x.open),
            high=float(x.high),
            low=float(x.low),
            close=float(x.close),
            volume=float(x.vol),
            amount=float(x.amount),
        )
        for x in items
    ]


def fetch_chunk(host: str, stocks: Sequence[Stock], cfg: dict) -> tuple[list[Evaluation], list[str]]:
    from xmtdx import KlineCategory, Market, TdxClient

    results: list[Evaluation] = []
    errors: list[str] = []
    attempted: set[str] = set()
    try:
        with TdxClient(host, timeout=12, auto_reconnect=True) as client:
            for stock in stocks:
                try:
                    raw = client.get_security_bars(
                        Market(stock.market),
                        stock.code,
                        KlineCategory.DAY,
                        0,
                        cfg["history_bars"],
                    )
                    item = evaluate(stock, convert_bars(raw), cfg)
                    if item is not None:
                        results.append(item)
                except Exception as exc:  # 单只股票失败不影响全市场
                    errors.append(f"{stock.code} {type(exc).__name__}: {exc}")
                finally:
                    attempted.add(stock.code)
    except Exception as exc:
        # 公共服务器可能在建立连接时整批失败。把未尝试的股票交回
        # scan_market 的换服务器补扫流程，不能让 future.result() 终止全场扫描。
        errors.extend(
            f"{stock.code} {type(exc).__name__}: {exc}"
            for stock in stocks
            if stock.code not in attempted
        )
    return results, errors


def chunks(items: Sequence[Stock], count: int) -> list[list[Stock]]:
    return [list(items[i::count]) for i in range(count)]


def scan_market(cfg: dict, codes: set[str] | None = None) -> tuple[list[Evaluation], list[str], int]:
    from xmtdx import TdxClient

    ranked = TdxClient.ping_all(timeout=2.5)
    if not ranked:
        raise RuntimeError("无法连接通达信行情服务器")
    hosts = [host for host, _ in ranked]
    universe = reliable_universe(hosts, cfg["workers"])
    if codes:
        universe = [s for s in universe if s.code in codes]
    if not universe:
        raise RuntimeError("股票范围为空，请检查代码")

    worker_count = min(cfg["workers"], len(hosts), len(universe))
    print(f"行情服务器 {worker_count} 个；待扫描 {len(universe)} 只沪深A股", flush=True)
    evaluations: list[Evaluation] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(fetch_chunk, hosts[i], part, cfg)
            for i, part in enumerate(chunks(universe, worker_count))
        ]
        finished = 0
        for future in as_completed(futures):
            part_results, part_errors = future.result()
            evaluations.extend(part_results)
            errors.extend(part_errors)
            finished += 1
            print(f"扫描进度 {finished}/{worker_count}", flush=True)

    # 某台公共服务器偶发整批超时时，换服务器只重试失败股票。
    for attempt in range(1, 4):
        if not errors:
            break
        failed_codes = {line.split(" ", 1)[0] for line in errors}
        retry_stocks = [s for s in universe if s.code in failed_codes]
        print(f"第 {attempt} 次补扫 {len(retry_stocks)} 只失败股票", flush=True)
        errors = []
        retry_workers = min(worker_count, len(retry_stocks))
        with ThreadPoolExecutor(max_workers=retry_workers) as pool:
            futures = [
                pool.submit(
                    fetch_chunk,
                    hosts[(i + attempt) % len(hosts)],
                    part,
                    cfg,
                )
                for i, part in enumerate(chunks(retry_stocks, retry_workers))
            ]
            for future in as_completed(futures):
                part_results, part_errors = future.result()
                evaluations.extend(part_results)
                errors.extend(part_errors)
    if errors:
        failed_codes = {line.split(" ", 1)[0] for line in errors}
        retry_stocks = [s for s in universe if s.code in failed_codes]
        if len(retry_stocks) <= FINAL_INDIVIDUAL_RETRY_LIMIT:
            print(f"逐只换服务器补扫 {len(retry_stocks)} 只", flush=True)
            final_errors: list[str] = []
            retry_deadline = time.monotonic() + FINAL_RETRY_TIME_BUDGET_SECONDS
            for index, stock in enumerate(retry_stocks):
                if time.monotonic() >= retry_deadline:
                    final_errors.extend(
                        f"{remaining.code} FinalRetryBudgetExceeded: "
                        f"{FINAL_RETRY_TIME_BUDGET_SECONDS}s budget exhausted"
                        for remaining in retry_stocks[index:]
                    )
                    break
                last_errors: list[str] = []
                for host in hosts:
                    if time.monotonic() >= retry_deadline:
                        last_errors = [
                            f"{stock.code} FinalRetryBudgetExceeded: "
                            f"{FINAL_RETRY_TIME_BUDGET_SECONDS}s budget exhausted"
                        ]
                        break
                    part_results, part_errors = fetch_chunk(host, [stock], cfg)
                    if not part_errors:
                        evaluations.extend(part_results)
                        last_errors = []
                        break
                    last_errors = part_errors
                final_errors.extend(last_errors)
            errors = final_errors
        else:
            print(
                f"仍有 {len(retry_stocks)} 只失败，超过逐只补扫上限 "
                f"{FINAL_INDIVIDUAL_RETRY_LIMIT}；保留错误并结束本轮，避免工作流超时",
                flush=True,
            )
    evaluations.sort(
        key=lambda x: (x.selected, x.matched_count, x.yellow_count, x.change_pct),
        reverse=True,
    )
    return evaluations, errors, len(universe)


def scan_quality_error(scanned: int, errors: Sequence[str]) -> str:
    if len(errors) <= MAX_UNRESOLVED_ERRORS:
        return ""
    return (
        f"全市场扫描仍有 {len(errors)}/{scanned} 只行情失败，"
        f"超过发布上限 {MAX_UNRESOLVED_ERRORS}；本轮不更新策略状态"
    )


def market_prefix(item: Evaluation) -> str:
    return "sh" if item.market == 1 else "sz" if item.market == 0 else "bj"


def mark(value: bool) -> str:
    return '<span class="yes">✓</span>' if value else '<span class="no">—</span>'


def row_html(item: Evaluation) -> str:
    url = f"https://quote.eastmoney.com/{market_prefix(item)}{item.code}.html"
    return f"""
      <tr>
        <td><a href="{url}" target="_blank" rel="noreferrer">{html.escape(item.code)}</a><br><strong>{html.escape(item.name)}</strong></td>
        <td>{item.close:.2f}<br><span class="{'up' if item.change_pct >= 0 else 'down'}">{item.change_pct:+.2f}%</span></td>
        <td>{item.chart}</td>
        <td>{mark(item.bottom_ok)}<small>{item.bottom_date or '未命中'}</small></td>
        <td>{mark(item.cross_ok)}<small>{item.cross_date or '未命中'}</small></td>
        <td>{mark(item.limit_up_ok)}<small>{item.limit_up_date or '未命中'}</small></td>
        <td>{mark(item.yellow_ok)}<small>连续 {item.yellow_count} 根</small></td>
      </tr>"""


def observation_row_html(item: Evaluation) -> str:
    url = f"https://quote.eastmoney.com/{market_prefix(item)}{item.code}.html"
    cross_note = item.cross_date if item.cross_ok else (f"龙腾跃虎已失效 {item.cross_date}" if item.cross_date else "未出现")
    if item.cross_ok and item.bottom_ok:
        priority = '<span class="status healthy">优先观察</span><small>龙腾跃虎和见底都已出现</small>'
    elif item.cross_ok:
        priority = '<span class="status healthy">龙虎优先</span><small>等待其他条件补齐</small>'
    elif item.bottom_ok:
        priority = '<span class="status warning">见底候选</span><small>尚缺近期龙腾跃虎</small>'
    else:
        priority = '<span class="status warning">普通观察</span>'
    return f"""
      <tr>
        <td><a href="{url}" target="_blank" rel="noreferrer">{html.escape(item.code)}</a><br><strong>{html.escape(item.name)}</strong></td>
        <td>{item.close:.2f}<br><span class="{'up' if item.change_pct >= 0 else 'down'}">{item.change_pct:+.2f}%</span></td>
        <td>{item.chart}</td>
        <td>{mark(item.cross_ok)}<small>{cross_note}</small></td>
        <td>{mark(item.bottom_ok)}<small>{item.bottom_date or '未出现'}</small></td>
        <td>{mark(item.yellow_ok)}<small>连续 {item.yellow_count} 根</small></td>
        <td>{mark(item.limit_up_ok)}<small>{item.limit_up_date or '未出现'}</small></td>
        <td>{priority}</td>
      </tr>"""


def strategy_link(position: dict) -> str:
    prefix = "sh" if int(position["market"]) == 1 else "sz" if int(position["market"]) == 0 else "bj"
    return f"https://quote.eastmoney.com/{prefix}{position['code']}.html"


def pct_html(value: float | None) -> str:
    if value is None:
        return "—"
    css = "up" if value >= 0 else "down"
    return f'<span class="{css}">{value:+.2f}%</span>'


def active_position_row(position: dict) -> str:
    per_share = float(position["last_close"]) - float(position["entry_price"])
    status_class = "warning" if int(position.get("missing_streak", 0)) else "healthy"
    return f"""
      <tr>
        <td><a href="{strategy_link(position)}" target="_blank" rel="noreferrer">{html.escape(position['code'])}</a><br><strong>{html.escape(position['name'])}</strong></td>
        <td>{position['entry_date']}<small>{float(position['entry_price']):.2f} 元</small></td>
        <td>{position['last_date']}<small>{float(position['last_close']):.2f} 元</small></td>
        <td>{pct_html(float(position['return_pct']))}<small>每股 {per_share:+.2f} 元</small></td>
        <td>{int(position['holding_days'])} 个交易日</td>
        <td><span class="status {status_class}">{html.escape(position['status'])}</span><small>{'首次消失 ' + position.get('signal_lost_date', '') if position.get('signal_lost_date') else '龙线 > 虎线'}</small></td>
      </tr>"""


def closed_position_row(position: dict) -> str:
    return f"""
      <tr>
        <td><a href="{strategy_link(position)}" target="_blank" rel="noreferrer">{html.escape(position['code'])}</a><br><strong>{html.escape(position['name'])}</strong></td>
        <td>{position['entry_date']}<small>{float(position['entry_price']):.2f} 元</small></td>
        <td>{position.get('exit_date', '')}<small>{float(position.get('exit_price', 0)):.2f} 元</small></td>
        <td>{pct_html(float(position.get('exit_return_pct', 0.0)))}</td>
        <td>{int(position.get('holding_days', 0))} 个交易日</td>
        <td>{html.escape(position.get('exit_reason', ''))}</td>
      </tr>"""


def event_text(event: dict) -> str:
    label = {
        "added": "加入跟踪池",
        "signal_lost": "龙虎信号消失，进入待移出观察",
        "signal_restored": "龙虎信号恢复，取消移出提示",
        "removed": "连续第二个交易日未恢复，已移出",
        "ineligible_removed": "股票名称含 ST，已移出",
        "secondary_added": "加入次选区",
        "secondary_removed": "龙虎信号消失，已移出次选区",
        "secondary_promoted": "条件补齐，已转入主选区",
    }.get(event.get("type"), "状态更新")
    return_label = "阶段收益" if event.get("type") == "secondary_promoted" else "移出收益"
    suffix = f"，{return_label} {event['return_pct']:+.2f}%" if "return_pct" in event else ""
    return f"{event.get('code', '')} {event.get('name', '')}：{label}{suffix}"


def render_html(
    evaluations: Sequence[Evaluation],
    cfg: dict,
    scanned: int,
    errors: Sequence[str],
    strategy_state: dict,
    events: Sequence[dict],
) -> str:
    selected = [x for x in evaluations if x.selected]
    near = sorted([
        x
        for x in evaluations
        if x.eligible and not x.selected and x.matched_count >= cfg["near_match_minimum"]
    ], key=lambda x: (
        x.cross_ok,
        x.bottom_ok,
        x.yellow_ok,
        x.limit_up_ok,
        x.cross_date,
        x.bottom_date,
    ), reverse=True)[:30]
    trade_date = max((x.date for x in evaluations), default="无数据")
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    stats = strategy_stats(strategy_state)
    secondary_stats = secondary_strategy_stats(strategy_state)
    strict_rows = "".join(row_html(x) for x in selected) or '<tr><td colspan="7" class="empty">今日没有股票同时满足四项条件</td></tr>'
    near_rows = "".join(observation_row_html(x) for x in near) or '<tr><td colspan="8" class="empty">今日没有满足三项条件的观察标的</td></tr>'
    active_rows = "".join(active_position_row(x) for x in strategy_state["active"]) or '<tr><td colspan="6" class="empty">跟踪池目前为空</td></tr>'
    closed_rows = "".join(closed_position_row(x) for x in strategy_state["closed"][:50]) or '<tr><td colspan="6" class="empty">尚无移出记录</td></tr>'
    secondary_active_rows = "".join(
        active_position_row(x) for x in strategy_state.get("secondary_active", [])
    ) or '<tr><td colspan="6" class="empty">次选区目前为空</td></tr>'
    secondary_closed_rows = "".join(
        closed_position_row(x) for x in strategy_state.get("secondary_closed", [])[:50]
    ) or '<tr><td colspan="6" class="empty">次选区尚无移出记录</td></tr>'
    event_notice = "".join(f"<li>{html.escape(event_text(x))}</li>" for x in events)
    event_block = f'<div class="events"><strong>今日状态变动</strong><ul>{event_notice}</ul></div>' if event_notice else ""
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>阿里股神每日选股 · {trade_date}</title>
<style>
:root{{--bg:#0c111b;--panel:#141c29;--line:#263348;--text:#eef3fa;--muted:#91a0b5;--red:#ff5c70;--blue:#55c6e8;--yellow:#f4d35e;--green:#4dd599}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0,#18263b 0,transparent 35%),var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,"Microsoft YaHei",sans-serif}}
main{{max-width:1260px;margin:auto;padding:34px 20px 60px}}h1{{margin:0 0 6px;font-size:30px}}h2{{margin:34px 0 12px}}h3{{margin:24px 0 8px;font-size:20px}}p{{color:var(--muted)}}.meta{{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 22px}}.pill{{padding:8px 12px;border:1px solid var(--line);border-radius:999px;background:#111926}}.pill b{{color:white}}
.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:14px;background:rgba(20,28,41,.9)}}table{{border-collapse:collapse;width:100%;min-width:1200px}}th,td{{padding:13px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}}th{{position:sticky;top:0;background:#182232;color:#aeb9c8;font-weight:600}}tr:last-child td{{border-bottom:0}}a{{color:#9bdcff;text-decoration:none}}small{{display:block;color:var(--muted);white-space:nowrap}}.spark{{display:block;width:420px;height:176px}}.yes{{font-size:22px;color:var(--green)}}.no{{font-size:22px;color:#526176}}.up{{color:var(--red)}}.down{{color:var(--green)}}.empty{{padding:34px;text-align:center;color:var(--muted)}}.legend{{display:flex;gap:18px;flex-wrap:wrap;margin:0 0 9px;font-size:13px;color:var(--muted)}}.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}}
.stats{{display:grid;grid-template-columns:repeat(6,minmax(140px,1fr));gap:10px;margin:14px 0}}.stat{{padding:14px;border:1px solid var(--line);border-radius:12px;background:#111926}}.stat small{{margin-bottom:3px}}.stat b{{font-size:21px}}.events{{margin:14px 0;padding:14px 18px;border:1px solid #375478;background:#12243a;border-radius:12px}}.events ul{{margin:6px 0 0;padding-left:20px;color:#bdd5f0}}.status{{display:inline-block;padding:5px 9px;border-radius:999px;font-size:13px;white-space:nowrap}}.status.healthy{{color:#8de8bc;background:#113329}}.status.warning{{color:#ffd381;background:#3a2a10}}
footer{{margin-top:25px;color:#738198;font-size:13px}}@media(max-width:900px){{.stats{{grid-template-columns:repeat(2,minmax(130px,1fr))}}}}@media(max-width:700px){{main{{padding:24px 12px}}h1{{font-size:25px}}}}
</style></head><body><main>
<h1>阿里股神每日选股</h1><p>交易日 {trade_date} · 仅按技术条件机械筛选，不构成投资建议</p>
<div class="meta"><span class="pill">严格命中 <b>{len(selected)}</b></span><span class="pill">扫描 <b>{scanned}</b> 只</span><span class="pill">见底/龙腾跃虎 <b>{cfg['bottom_lookback_days']}/{cfg['cross_lookback_days']} 日</b></span><span class="pill">两月涨停 <b>{cfg['limit_up_lookback_days']} 日</b></span><span class="pill">黄柱 <b>连续 {cfg['yellow_consecutive_days']} 根</b></span><span class="pill">ST <b>排除</b></span></div>
<h2>今日入选清单</h2><div class="legend"><span><i class="dot" style="background:#ff5c70"></i>上涨 K 线</span><span><i class="dot" style="background:#4dd599"></i>下跌 K 线</span><span><i class="dot" style="background:#f4d35e"></i>龙线下方的实体部分</span><span><i class="dot" style="background:#ff5c70"></i>龙线</span><span><i class="dot" style="background:#55c6e8"></i>虎线</span></div>
<div class="table-wrap"><table><thead><tr><th>股票</th><th>收盘</th><th>近42日 K 线 + 龙虎线</th><th>可能见底</th><th>龙腾跃虎</th><th>两月内涨停</th><th>连续黄柱</th></tr></thead><tbody>{strict_rows}</tbody></table></div>

<h2>{POOL_NAME}</h2>
{event_block}
<h3>主选区</h3>
<p>入选日收盘价作为加入价。龙线不再高于虎线时当天提示；下一交易日仍未恢复，收盘后移出。</p>
<div class="stats">
  <div class="stat"><small>跟踪中</small><b>{stats['active_count']} 只</b></div>
  <div class="stat"><small>信号消失待确认</small><b>{stats['warning_count']} 只</b></div>
  <div class="stat"><small>当前成功率</small><b>{pct_html(stats['current_success_rate'])}</b></div>
  <div class="stat"><small>样本平均收益</small><b>{pct_html(stats['all_average_return'])}</b></div>
  <div class="stat"><small>已完成胜率</small><b>{pct_html(stats['closed_success_rate'])}</b></div>
  <div class="stat"><small>已实现累计收益</small><b>{pct_html(stats['realized_compound_return'])}</b></div>
</div>
<div class="table-wrap"><table><thead><tr><th>股票</th><th>加入日/加入价</th><th>最新日/收盘价</th><th>加入日至今收益</th><th>跟踪时长</th><th>龙虎信号</th></tr></thead><tbody>{active_rows}</tbody></table></div>

<h3>次选区</h3>
<p>近期龙腾跃虎与连续黄柱必须同时满足，并在“可能见底”或两月内涨停中至少再满足一项。黄柱指 K 线实体有一部分位于龙线下方；龙线不再高于虎线时，当日收盘后立即移出；条件补齐时转入主选区。</p>
<div class="stats">
  <div class="stat"><small>次选跟踪中</small><b>{secondary_stats['active_count']} 只</b></div>
  <div class="stat"><small>当前成功率</small><b>{pct_html(secondary_stats['current_success_rate'])}</b></div>
  <div class="stat"><small>跟踪中平均收益</small><b>{pct_html(secondary_stats['active_average_return'])}</b></div>
  <div class="stat"><small>全部样本平均收益</small><b>{pct_html(secondary_stats['all_average_return'])}</b></div>
  <div class="stat"><small>已移出</small><b>{secondary_stats['closed_count']} 只</b></div>
  <div class="stat"><small>累计样本</small><b>{secondary_stats['sample_count']} 只</b></div>
</div>
<div class="table-wrap"><table><thead><tr><th>股票</th><th>加入日/加入价</th><th>最新日/收盘价</th><th>加入日至今收益</th><th>跟踪时长</th><th>龙虎信号</th></tr></thead><tbody>{secondary_active_rows}</tbody></table></div>

<h3>次选区移出记录</h3>
<div class="table-wrap"><table><thead><tr><th>股票</th><th>加入日/加入价</th><th>移出日/移出价</th><th>实现收益</th><th>持有时长</th><th>移出原因</th></tr></thead><tbody>{secondary_closed_rows}</tbody></table></div>

<h2>成功率与收益统计</h2>
<p>当前成功率＝全部在池浮盈样本与已移出盈利样本占全部策略样本的比例；已完成胜率只统计已移出样本。收益按每只股票等权计算，未计手续费、滑点和实际仓位。</p>
<div class="table-wrap"><table><thead><tr><th>股票</th><th>加入日/加入价</th><th>移出日/移出价</th><th>实现收益</th><th>持有时长</th><th>移出原因</th></tr></thead><tbody>{closed_rows}</tbody></table></div>

<h2>观察区：满足三项</h2><p>按“龙腾跃虎 → 可能见底 → 连续黄柱 → 两月内涨停”排序。出现龙腾跃虎并同时出现可能见底的股票优先。</p>
<div class="legend"><span><i class="dot" style="background:#ff5c70"></i>上涨 K 线</span><span><i class="dot" style="background:#4dd599"></i>下跌 K 线</span><span><i class="dot" style="background:#f4d35e"></i>龙线下方的实体部分</span><span><i class="dot" style="background:#ff5c70"></i>龙线</span><span><i class="dot" style="background:#55c6e8"></i>虎线</span><span>鼠标停在 K 线上可看开高低收</span></div>
<div class="table-wrap"><table><thead><tr><th>股票</th><th>收盘</th><th>近42日 K 线 + 龙虎线</th><th>① 龙腾跃虎</th><th>② 可能见底</th><th>③ 连续黄柱</th><th>④ 两月内涨停</th><th>观察优先级</th></tr></thead><tbody>{near_rows}</tbody></table></div>
<footer>生成时间 {generated} · 沪深 A 股 · 数据失败 {len(errors)} 只 · 页面可直接转发，打开时无需联网（股票详情链接除外）</footer>
</main></body></html>"""


def render_html(
    evaluations: Sequence[Evaluation],
    cfg: dict,
    scanned: int,
    errors: Sequence[str],
    strategy_state: dict,
    events: Sequence[dict],
) -> str:
    """使用独立的响应式报告模板，保留筛选与跟踪逻辑不变。"""
    from report_ui import render_report

    return render_report(
        evaluations,
        cfg,
        scanned,
        errors,
        strategy_state,
        events,
    )


def write_strategy_csv(state: dict, trade_date: str, publish_latest: bool = True) -> Path:
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = STRATEGY_DIR / f"{POOL_NAME}_{trade_date}.csv"
    latest_path = STRATEGY_DIR / f"{POOL_NAME}_最新.csv"
    rows = []
    for x in state["active"]:
        rows.append([
            "主选区", "跟踪中", x["code"], x["name"], x["entry_date"], x["entry_price"],
            x["last_date"], x["last_close"], f"{x['return_pct']:.2f}%", x["holding_days"],
            x["status"], "", "", "",
        ])
    for x in state["closed"]:
        rows.append([
            "主选区", "已移出", x["code"], x["name"], x["entry_date"], x["entry_price"],
            x.get("exit_date", ""), x.get("exit_price", ""), f"{x.get('exit_return_pct', 0):.2f}%",
            x.get("holding_days", ""), "已移出", x.get("exit_date", ""),
            x.get("exit_price", ""), x.get("exit_reason", ""),
        ])
    for x in state.get("secondary_active", []):
        rows.append([
            "次选区", "跟踪中", x["code"], x["name"], x["entry_date"], x["entry_price"],
            x["last_date"], x["last_close"], f"{x['return_pct']:.2f}%", x["holding_days"],
            x["status"], "", "", "",
        ])
    for x in state.get("secondary_closed", []):
        rows.append([
            "次选区", "已移出", x["code"], x["name"], x["entry_date"], x["entry_price"],
            x.get("exit_date", ""), x.get("exit_price", ""), f"{x.get('exit_return_pct', 0):.2f}%",
            x.get("holding_days", ""), "已移出", x.get("exit_date", ""),
            x.get("exit_price", ""), x.get("exit_reason", ""),
        ])
    paths = (dated_path, latest_path) if publish_latest else (dated_path,)
    for path in paths:
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["区域", "状态", "代码", "名称", "加入日", "加入价", "最新/移出日", "最新/移出价", "收益", "交易日数", "龙虎信号", "移出日", "移出价", "移出原因"])
            writer.writerows(rows)
    return latest_path


def write_outputs(
    evaluations: Sequence[Evaluation],
    cfg: dict,
    scanned: int,
    errors: Sequence[str],
    strategy_state: dict,
    events: Sequence[dict],
    publish_latest: bool = True,
) -> tuple[Path, Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trade_date = max((x.date for x in evaluations), default=datetime.now().strftime("%Y-%m-%d"))
    csv_path = OUTPUT_DIR / f"选股结果_{trade_date}.csv"
    html_path = OUTPUT_DIR / f"选股报告_{trade_date}.html"
    json_path = OUTPUT_DIR / f"选股结果_{trade_date}.json"

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["代码", "名称", "交易日", "收盘", "涨跌幅", "见底日期", "龙腾跃虎日期", "涨停日期", "连续黄柱", "龙线在虎线上方", "是否排除ST", "命中项数", "严格入选"])
        for x in evaluations:
            writer.writerow([x.code, x.name, x.date, f"{x.close:.2f}", f"{x.change_pct:.2f}%", x.bottom_date, x.cross_date, x.limit_up_date, x.yellow_count, "是" if x.dragon_above_tiger else "否", "否" if x.eligible else "是", x.matched_count, "是" if x.selected else "否"])

    payload = {
        "trade_date": trade_date,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scanned": scanned,
        "errors": list(errors),
        "config": {k: v for k, v in cfg.items() if not k.startswith("_")},
        "results": [{k: v for k, v in asdict(x).items() if k != "chart"} for x in evaluations],
        "strategy": strategy_state,
        "strategy_stats": strategy_stats(strategy_state),
        "secondary_strategy_stats": secondary_strategy_stats(strategy_state),
        "strategy_events": list(events),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(evaluations, cfg, scanned, errors, strategy_state, events), encoding="utf-8")
    write_strategy_csv(strategy_state, trade_date, publish_latest)
    if publish_latest:
        (OUTPUT_DIR / "latest.html").write_text(html_path.read_text(encoding="utf-8"), encoding="utf-8")
        (OUTPUT_DIR / "latest.json").write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    return html_path, csv_path, json_path


def parse_codes(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {x.strip() for x in raw.split(",") if x.strip()}


def is_intraday_snapshot(trade_date: str, now: datetime | None = None) -> bool:
    local_now = now or datetime.now().astimezone()
    return trade_date == local_now.strftime("%Y-%m-%d") and local_now.strftime("%H:%M") < "15:15"


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="阿里股神每日选股")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--codes", help="只扫描指定代码，逗号分隔；用于测试")
    parser.add_argument("--as-of", help="按 YYYY-MM-DD 截止日期重建历史日报")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        cfg = load_config(args.config)
        if args.as_of:
            datetime.strptime(args.as_of, "%Y-%m-%d")
            cfg["_as_of_date"] = args.as_of
        evaluations, errors, scanned = scan_market(cfg, parse_codes(args.codes))
        quality_error = scan_quality_error(scanned, errors)
        if quality_error:
            print(quality_error, file=sys.stderr)
            return 4
        trade_date = max(x.date for x in evaluations)
        if is_intraday_snapshot(trade_date):
            print(f"{trade_date} 尚未收盘：本次为盘中数据，未更新日报和策略跟踪池")
            return 3
        current_state = load_state(STRATEGY_STATE_PATH) if STRATEGY_STATE_PATH.exists() else None
        historical_only = bool(
            args.as_of
            and current_state
            and current_state.get("last_trade_date", "") > args.as_of
        )
        strategy_state = (
            replay_state(OUTPUT_DIR, args.as_of)
            if historical_only
            else bootstrap_state(STRATEGY_STATE_PATH, OUTPUT_DIR)
        )
        strategy_rows = [{k: v for k, v in asdict(x).items() if k != "chart"} for x in evaluations]
        events: list[dict] = []
        if not args.codes:
            strategy_state, events = update_state(strategy_state, strategy_rows, trade_date)
            if not historical_only:
                save_state(STRATEGY_STATE_PATH, strategy_state)
        html_path, csv_path, _ = write_outputs(
            evaluations, cfg, scanned, errors, strategy_state, events,
            publish_latest=not historical_only,
        )
        selected = sum(x.selected for x in evaluations)
        print(f"完成：严格命中 {selected} 只；行情失败 {len(errors)} 只")
        print(f"报告：{html_path}")
        print(f"表格：{csv_path}")
        return 0 if evaluations else 2
    except Exception as exc:
        print(f"运行失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
