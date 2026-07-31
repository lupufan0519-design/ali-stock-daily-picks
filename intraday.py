from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from observation import OBSERVATION_LIMIT, visible_observations
from screener import cross_yellow_pair


ROOT = Path(__file__).resolve().parent
DEFAULT_RESULT = ROOT / "results" / "latest.json"
DEFAULT_OUTPUT = ROOT / "results" / "live.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def is_st_name(name: object) -> bool:
    return "ST" in str(name).upper()


def unpack_live_seed(item: object, seed_format: int = 0) -> dict:
    """Decode the compact close-generated seed used by the intraday workflow."""
    if isinstance(item, dict):
        return item
    if seed_format not in {1, 2, 3} or not isinstance(item, list) or len(item) < 19:
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
        return sorted(
            [
                {
                    "code": str(item["code"]),
                    "name": str(item.get("name", "")),
                    "market": int(item["market"]),
                    "scope": "universe",
                }
                for item in universe
                if item.get("eligible")
                and not is_st_name(item.get("name", ""))
            ],
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


def collect_tracking_codes(payload: dict) -> dict[str, list[str]]:
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
        "main": codes("active"),
        "secondary": codes("secondary_active"),
    }


def market_state(now: datetime) -> tuple[str, str]:
    if now.weekday() >= 5:
        return "休市", "周末休市，页面保留最近一次已验证行情"
    hhmm = now.strftime("%H:%M")
    if "09:15" <= hhmm < "09:30":
        return "集合竞价", "主选与次选按最新行情预选；跟踪统计收盘后结算"
    if "09:30" <= hhmm <= "11:30" or "13:00" <= hhmm <= "15:00":
        return "盘中行情", "主选与次选约每 5 分钟重算；跟踪统计收盘后结算"
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


def _baseline_live_row(seed: dict, quote: dict) -> dict:
    return {
        "code": str(seed["code"]),
        "name": str(seed.get("name", quote.get("name", ""))),
        "market": int(seed["market"]),
        "price": float(quote.get("price", seed.get("previous_close", 0.0))),
        "change_pct": float(quote.get("change_pct", 0.0)),
        "server_time": str(quote.get("server_time", "")),
        "bottom_ok": bool(seed.get("bottom_ok")),
        "cross_ok": bool(seed.get("cross_ok")),
        "limit_up_ok": bool(seed.get("limit_up_ok")),
        "yellow_ok": bool(seed.get("yellow_ok")),
        "bottom_date": str(seed.get("bottom_date", "")),
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
    }


def evaluate_live_seed(
    seed: dict,
    quote: dict,
    cfg: dict,
    close_trade_date: str,
) -> dict | None:
    """Re-evaluate one stock from today's OHLC without mutating settled state."""
    if not seed.get("eligible") or is_st_name(seed.get("name", "")):
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
        return _baseline_live_row(seed, quote)
    if min(price, open_price, high, low) <= 0:
        return None

    coefficients = seed["line_coefficients"]
    dragon_tail_coefficients = coefficients.get("dragon_tail")
    tiger_tail_coefficients = coefficients.get("tiger_tail")
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
    dragon = dragon_tail[-1]
    tiger = tiger_tail[-1]
    dragon_above_tiger = dragon > tiger

    new_bottom = bool(
        price <= float(seed["min_close_15"]) + 1e-8
        and high > low + 0.04
        and current_cci(seed.get("typical_13", []), high, low, price) < -110
    )
    bottom_age = int(seed.get("bottom_age", -1))
    prior_bottom = (
        bottom_age >= 0
        and bottom_age + 1 < int(cfg["bottom_lookback_days"])
    )
    bottom_ok = new_bottom or prior_bottom
    bottom_date = (
        live_date
        if new_bottom
        else str(seed.get("bottom_date", ""))
        if prior_bottom
        else ""
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
    return {
        "code": str(seed["code"]),
        "name": str(seed.get("name", quote.get("name", ""))),
        "market": int(seed["market"]),
        "price": price,
        "change_pct": float(quote.get("change_pct", 0.0)),
        "server_time": server_time,
        "bottom_ok": bottom_ok,
        "cross_ok": cross_ok,
        "limit_up_ok": limit_up_ok,
        "yellow_ok": yellow_ok,
        "bottom_date": bottom_date,
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
        "eligible": True,
        "selected": selected,
    }


def build_live_pools(payload: dict, quotes: dict[str, dict]) -> dict:
    seeds = live_seeds(payload)
    if not seeds:
        return {"main": [], "secondary": [], "available": False}
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
    live_pools = build_live_pools(payload, quotes)
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
    live_dates = sorted(
        {
            str(item.get("server_time", ""))[:10]
            for item in quotes.values()
            if len(str(item.get("server_time", ""))) >= 10
        }
    )
    live_trade_date = live_dates[-1] if live_dates else ""
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
        "tracking_codes": collect_tracking_codes(payload),
        "target_count": len(targets),
        "quote_count": len(quotes),
        "quotes": display_quotes,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="卢氏龙虎趋势池盘中行情刷新")
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        payload = json.loads(args.result.read_text(encoding="utf-8"))
        live = build_live_payload(payload)
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
