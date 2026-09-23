"""Validated public HTTPS daily prices. Never substitute a stale candle for today.

Tencent's fqkline endpoint is requested explicitly with qfq. It returns qfqday
when adjusted candles are present, and day when that requested series needs no
adjustment (also for indices). The original response key is retained in cache.
These vendor-adjusted values must not be described as TDX-adjusted data.
"""
from __future__ import annotations

import json
import math
import re
import time
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CHINA = timezone(timedelta(hours=8))
CACHE_ROOT = Path(__file__).resolve().parent / "cache" / "daily_bars" / "tencent_qfq"
ENDPOINTS = (
    "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get",
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
)
ENDPOINT = ENDPOINTS[0]
_request_lock = threading.Lock()
_last_request_at = 0.0


class DailyDataError(ValueError):
    pass


class StaleDailyData(DailyDataError):
    pass


def _date(value: object) -> str:
    text = str(value)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise DailyDataError(f"Invalid candle date: {text!r}")
    datetime.strptime(text, "%Y-%m-%d")
    return text


def _number(value: object) -> float:
    if value is None or isinstance(value, bool):
        raise DailyDataError("Missing numeric candle value")
    number = float(value)
    if not math.isfinite(number):
        raise DailyDataError("Non-finite candle value")
    return number


def _get_json(url: str, timeout: float = 8) -> dict:
    global _last_request_at
    # Bound aggregate traffic, including retries, rather than allowing each
    # worker its own unconstrained request stream.
    with _request_lock:
        wait = 0.18 - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 ali-stock-daily-picks/1.0",
        "Referer": "https://gu.qq.com/", "Cache-Control": "no-cache",
    })
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_daily_payload(payload: dict, symbol: str, *, through_date: str = "") -> dict:
    if payload.get("code", 0) != 0 or not isinstance(payload.get("data"), dict):
        raise DailyDataError("Tencent daily request failed")
    data = payload["data"].get(symbol)
    if not isinstance(data, dict):
        raise DailyDataError(f"Tencent response missing requested symbol {symbol}")
    key = "qfqday" if "qfqday" in data else "day"
    raw = data.get(key)
    if not isinstance(raw, list) or not raw:
        raise DailyDataError(f"{symbol}: no daily candles")
    end = _date(through_date) if through_date else ""
    bars = []
    previous = ""
    for values in raw:
        if not isinstance(values, list) or len(values) < 6:
            raise DailyDataError(f"{symbol}: malformed candle")
        day = _date(values[0])
        if day <= previous:
            raise DailyDataError(f"{symbol}: duplicate or unordered candle dates")
        previous = day
        if end and day > end:
            continue
        opening, close, high, low, volume = map(_number, values[1:6])
        if min(opening, close, high, low) <= 0 or volume < 0:
            raise DailyDataError(f"{symbol}: invalid price or volume on {day}")
        if low > min(opening, close) + 0.011 or high < max(opening, close) - 0.011 or high < low:
            raise DailyDataError(f"{symbol}: inconsistent OHLC on {day}")
        bars.append(dict(date=day, open=opening, close=close, high=high, low=low,
                         volume=volume, amount=0.0))
    if not bars:
        raise DailyDataError(f"{symbol}: no candles at requested date {end}")
    quote = data.get("qt", {}).get(symbol, [])
    stamp = str(quote[30]) if isinstance(quote, list) and len(quote) > 30 else ""
    quote_date = (f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
                  if len(stamp) >= 8 and stamp[:8].isdigit() else "")
    if quote_date:
        _date(quote_date)
    quote_volume = _number(quote[6]) if len(quote) > 6 and str(quote[6]).strip() else None
    return {
        "schema": 1, "symbol": symbol, "source": "Tencent HTTPS fqkline",
        "adjustment": "qfq", "response_series": key,
        "adjustment_evidence": "fqkline request parameter qfq",
        "volume_unit": "lots", "amount_available": False,
        "requested_end": end, "bars_end_date": bars[-1]["date"], "bars": bars,
        "quote_date": quote_date, "quote_volume": quote_volume,
        "quote_name": str(quote[1]).strip() if len(quote) > 1 else "",
        "fetched_at": datetime.now(CHINA).isoformat(timespec="seconds"),
    }


def fetch_daily_prices(symbol: str, count: int = 180, *, through_date: str = "",
                       attempts: int = 3) -> dict:
    if not re.fullmatch(r"(?:sh|sz)\d{6}", symbol):
        raise ValueError("Invalid market symbol")
    end = _date(through_date) if through_date else ""
    if not 1 <= count <= 640:
        raise ValueError("Daily candle count must be between 1 and 640")
    query = urlencode({
        "param": f"{symbol},day,,{end},{count},qfq", "r": time.time_ns(),
    })
    last_error = None
    for attempt in range(max(1, attempts)):
        try:
            endpoint = ENDPOINTS[0] if (attempt == 0 or (attempts >= 3 and attempt == 1)) else ENDPOINTS[1]
            url = endpoint + "?" + query
            return parse_daily_payload(_get_json(url), symbol, through_date=end)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.3 * (attempt + 1))
    raise DailyDataError(f"{symbol} HTTPS daily failed: {type(last_error).__name__}: {last_error}") from last_error


def fetch_market_sessions(count: int = 240) -> dict:
    data = fetch_daily_prices("sh000001", count)
    sessions = [row["date"] for row in data["bars"]]
    if not data["quote_date"] or data["quote_date"] != sessions[-1]:
        raise StaleDailyData("Reference index candles do not match current index quote date")
    return {"sessions": sessions, "latest_session": sessions[-1],
            "quote_date": data["quote_date"], "fetched_at": data["fetched_at"],
            "source": "Tencent Shanghai Composite actual daily sessions"}


def fetch_reference_sessions(through_date: str = "", count: int = 240) -> list[str]:
    """Actual exchange sessions, never weekdays guessed from the calendar."""
    result = fetch_market_sessions(count)
    end = _date(through_date) if through_date else ""
    return [day for day in result["sessions"] if not end or day <= end]


def _datacenter_rows(report: str, filters: str, columns: str = "ALL") -> tuple[list[dict], str]:
    rows = []
    page = 1
    while True:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + urlencode({
            "reportName": report, "columns": columns, "filter": filters,
            "pageSize": 500, "pageNumber": page, "source": "WEB", "client": "WEB",
        })
        payload = _get_json(url)
        result = payload.get("result")
        if payload.get("success") is not True or not isinstance(result, dict):
            raise DailyDataError(f"{report}: {payload.get('message', 'missing result')}")
        batch = result.get("data")
        if not isinstance(batch, list):
            raise DailyDataError(f"{report}: invalid records")
        rows.extend(batch)
        pages = int(result.get("pages", 1))
        if page >= pages:
            return rows, url
        if pages > 20:
            raise DailyDataError(f"{report}: unbounded page count")
        page += 1


def parse_full_day_suspensions(rows: list[dict], trade_date: str) -> dict[str, dict]:
    day = _date(trade_date)
    result = {}
    for row in rows:
        code = str(row.get("SECURITY_CODE", ""))
        start = str(row.get("SUSPEND_START_TIME") or "")
        end = str(row.get("SUSPEND_END_TIME") or "")
        resume = str(row.get("PREDICT_RESUME_DATE") or "")[:10]
        try:
            datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
            if end:
                datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
            if resume:
                _date(resume)
        except ValueError:
            continue
        # Intraday 10-minute halts must never make a full daily candle optional.
        if (not re.fullmatch(r"\d{6}", code)
                or str(row.get("SECUCODE", "")) not in (code + ".SZ", code + ".SH")
                or str(row.get("SECURITY_TYPE_CODE", "")) != "058001001"
                or len(start) < 19 or start > day + " 09:30:00"
                or (end and end < day + " 15:00:00")
                or (resume and resume <= day)):
            continue
        if not end and row.get("SUSPEND_EXPIRE") != "连续停牌":
            continue
        result[code] = dict(row)
    return result


def fetch_nontrading_evidence(trade_date: str) -> dict:
    """Date-specific, full-day suspensions; preserve source evidence for audit."""
    day = _date(trade_date)
    rows, url = _datacenter_rows(
        "RPT_CUSTOM_SUSPEND_DATA_INTERFACE", f'(MARKET="全部")(DATETIME=\'{day}\')'
    )
    return {"trade_date": day, "source_url": url,
            "fetched_at": datetime.now(CHINA).isoformat(timespec="seconds"),
            "stocks": parse_full_day_suspensions(rows, day)}


def parse_prelisting_stocks(rows: list[dict], trade_date: str) -> dict[str, dict]:
    day = _date(trade_date)
    result = {}
    for row in rows:
        code = str(row.get("SECURITY_CODE", ""))
        listing = str(row.get("LISTING_DATE") or "")[:10]
        if not re.fullmatch(r"\d{6}", code) or not str(row.get("SECUCODE", "")).endswith((".SZ", ".SH")):
            continue
        if ((listing and _date(listing) > day)
                or (not listing and row.get("CONTINUOUS_1WORD_NUM") == "待上市")):
            result[code] = dict(row)
    return result


def fetch_prelisting_evidence(trade_date: str) -> dict:
    day = _date(trade_date)
    cutoff = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    rows, url = _datacenter_rows(
        "RPTA_APP_IPOAPPLY", f"(APPLY_DATE>='{cutoff}')",
        "SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,APPLY_DATE,LISTING_DATE,CONTINUOUS_1WORD_NUM",
    )
    return {"trade_date": day, "source_url": url,
            "fetched_at": datetime.now(CHINA).isoformat(timespec="seconds"),
            "stocks": parse_prelisting_stocks(rows, day)}


def validate_freshness(data: dict, expected_date: str) -> bool:
    """Return False only for quote-confirmed suspension; otherwise fail closed."""
    expected = _date(expected_date)
    actual = data.get("bars_end_date", "")
    bars = data.get("bars")
    if not isinstance(bars, list) or not bars or bars[-1].get("date") != actual:
        raise StaleDailyData(f"{data.get('symbol')}: candle/cache date metadata mismatch")
    if actual == expected:
        return True
    if actual < expected and data.get("quote_date") == expected and data.get("quote_volume") == 0:
        data["suspended"] = True
        return False
    raise StaleDailyData(f"{data.get('symbol')}: candles end {actual}, expected {expected}; quote {data.get('quote_date')}")


def save_daily_cache(data: dict, expected_date: str, cache_root: Path = CACHE_ROOT) -> Path:
    target = cache_root / _date(expected_date) / (data["symbol"] + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(target)
    return target


def load_daily_cache(symbol: str, expected_date: str, cache_root: Path = CACHE_ROOT) -> dict | None:
    """Opt-in reconstruction cache; only settled sessions can be reused."""
    try:
        data = json.loads((cache_root / _date(expected_date) / (symbol + ".json")).read_text(encoding="utf-8"))
        captured = datetime.fromisoformat(data["fetched_at"]).astimezone(CHINA)
        complete = captured.date().isoformat() > expected_date or (
            captured.date().isoformat() == expected_date and captured.strftime("%H:%M") >= "15:05"
        )
        if data.get("symbol") != symbol or data.get("adjustment") != "qfq" or not complete:
            return None
        if (data.get("exclusion_reason") == "st_excluded"
                and "ST" in str(data.get("quote_name", "")).upper()
                and data.get("quote_date", "") >= expected_date):
            return data
        validate_freshness(data, expected_date)
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None
