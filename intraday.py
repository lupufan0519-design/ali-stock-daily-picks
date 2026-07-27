from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
DEFAULT_RESULT = ROOT / "results" / "latest.json"
DEFAULT_OUTPUT = ROOT / "results" / "live.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def is_st_name(name: object) -> bool:
    return "ST" in str(name).upper()


def collect_targets(payload: dict, observation_limit: int = 12) -> list[dict]:
    """盘中只跟踪策略池和少量接近标的，不重新计算收盘信号。"""
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
    candidates = [
        row
        for row in payload.get("results", [])
        if row.get("eligible")
        and not row.get("selected")
        and int(row.get("matched_count", 0)) >= minimum
        and not is_st_name(row.get("name", ""))
    ]
    candidates.sort(
        key=lambda row: (
            bool(row.get("cross_ok")),
            bool(row.get("bottom_ok")),
            bool(row.get("yellow_ok")),
            bool(row.get("limit_up_ok")),
            str(row.get("cross_date", "")),
        ),
        reverse=True,
    )
    for row in candidates[:observation_limit]:
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


def market_state(now: datetime) -> tuple[str, str]:
    if now.weekday() >= 5:
        return "休市", "周末休市，页面保留最近一次已验证行情"
    hhmm = now.strftime("%H:%M")
    if "09:15" <= hhmm < "09:30":
        return "集合竞价", "价格约每 5 分钟更新，收盘信号保持不变"
    if "09:30" <= hhmm <= "11:30" or "13:00" <= hhmm <= "15:00":
        return "盘中行情", "价格约每 5 分钟更新，收盘信号保持不变"
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


def fetch_tencent_quotes(targets: Sequence[dict]) -> dict[str, dict]:
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
    quotes = parse_tencent_quotes(raw, targets)
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
                            "server_time": str(quote.server_time),
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


def build_live_payload(payload: dict, now: datetime | None = None) -> dict:
    local_now = now or datetime.now(SHANGHAI)
    targets = collect_targets(payload)
    label, note = market_state(local_now)
    quotes, source, host = fetch_quotes(targets)
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
        "target_count": len(targets),
        "quote_count": len(quotes),
        "quotes": quotes,
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
