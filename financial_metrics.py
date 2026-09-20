"""Disclosed YTD financials for stock cards, independent of screening signals."""
from __future__ import annotations

import copy
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

from company_metadata import DEFAULT_CACHE_PATH, _get_json, _load_cache, _save_cache


CACHE_HOURS = 12
RETRY_HOURS = 2
CHINA_TZ = timezone(timedelta(hours=8))
REPORT_NAME = "RPT_F10_FINANCE_MAINFINADATA"
REPORT_COLUMNS = (
    "SECURITY_CODE,REPORT_DATE,REPORT_TYPE,NOTICE_DATE,UPDATE_DATE,"
    "TOTALOPERATEREVETZ,PARENTNETPROFITTZ,KCFJCXSYJLRTZ,"
    "TOTALOPERATEREVE,PARENTNETPROFIT,KCFJCXSYJLR,NETCASH_OPERATE_PK"
)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _date(value: object) -> str:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _timestamp(value: object) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def parse_financials(payload: dict, code: str, market: int, as_of: str) -> dict:
    """Keep one report intact; never fill its missing values from an older period."""
    if not payload.get("success"):
        raise ValueError("financial endpoint: " + str(payload.get("message", "invalid response")))
    result = payload.get("result") or {}
    rows = result.get("data") or []
    available = [
        row for row in rows
        if isinstance(row, dict)
        and str(row.get("SECURITY_CODE", "")) == code
        and _date(row.get("REPORT_DATE"))
        and _date(row.get("NOTICE_DATE"))
        and _date(row.get("REPORT_DATE")) <= as_of
        and _date(row.get("NOTICE_DATE")) <= as_of
    ]
    if not available:
        raise ValueError("no disclosed financial report available")
    row = max(available, key=lambda item: (
        _date(item.get("REPORT_DATE")), _date(item.get("UPDATE_DATE")),
        _date(item.get("NOTICE_DATE")),
    ))
    report_date = _date(row["REPORT_DATE"])
    period = {"03-31": "一季报", "06-30": "中报", "09-30": "三季报", "12-31": "年报"}
    parent_profit = _number(row.get("PARENTNETPROFIT"))
    cash = _number(row.get("NETCASH_OPERATE_PK"))
    ratio = None
    cash_status = "missing"
    if parent_profit is not None and parent_profit <= 0:
        cash_status = "nonpositive_profit"
    elif parent_profit is not None and cash is not None:
        ratio = _number(cash / parent_profit)
        cash_status = "ok" if ratio is not None else "missing"
    prefix = "SH" if market == 1 else "SZ"
    return {
        "report_date": report_date,
        "report_label": report_date[:4] + "年" + period.get(report_date[5:], "财报"),
        "notice_date": _date(row["NOTICE_DATE"]),
        "basis": "year_to_date",
        "revenue_yoy_pct": _number(row.get("TOTALOPERATEREVETZ")),
        "parent_profit_yoy_pct": _number(row.get("PARENTNETPROFITTZ")),
        "adjusted_profit_yoy_pct": _number(row.get("KCFJCXSYJLRTZ")),
        "operating_cash_to_parent_profit": ratio,
        "cash_ratio_status": cash_status,
        "parent_profit": parent_profit,
        "operating_cash_flow": cash,
        "source": "东方财富财务分析",
        "source_url": "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?"
        + urlencode({"code": prefix + code, "type": "web"}),
    }


def fetch_financials(code: str, market: int, as_of: str) -> dict:
    if not re.fullmatch(r"\d{6}", code) or not _date(as_of):
        raise ValueError("invalid financial query")
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + urlencode({
        "reportName": REPORT_NAME,
        "columns": REPORT_COLUMNS,
        "filter": f'(SECURITY_CODE="{code}")(REPORT_DATE<=\'{as_of}\')(NOTICE_DATE<=\'{as_of}\')',
        "pageSize": 12,
        "pageNumber": 1,
        "sortColumns": "REPORT_DATE,UPDATE_DATE",
        "sortTypes": "-1,-1",
        "source": "WEB",
        "client": "WEB",
    })
    return parse_financials(_get_json(url), code, market, as_of)


def enrich_financial_evaluations(
    evaluations: Iterable[object],
    max_workers: int = 4,
    cache_path: Path | None = DEFAULT_CACHE_PATH,
    *,
    as_of: str = "",
    now: datetime | None = None,
) -> list[str]:
    # Convert objects to row proxies so close and intraday share the same cache rules.
    targets = [item for item in evaluations if getattr(item, "eligible", True)
               and getattr(item, "bottom_ok", False)]
    rows = [{"code": str(item.code), "market": int(item.market)} for item in targets]
    errors = enrich_financial_pools({"first": rows}, max_workers, cache_path, as_of=as_of, now=now)
    for item, row in zip(targets, rows):
        item.financials = row.get("financials", {})
        seed = getattr(item, "live_seed", None)
        if isinstance(seed, dict):
            seed["financials"] = copy.deepcopy(item.financials)
    return errors


def enrich_financial_pools(
    pools: dict,
    max_workers: int = 4,
    cache_path: Path | None = DEFAULT_CACHE_PATH,
    *,
    as_of: str = "",
    now: datetime | None = None,
) -> list[str]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = _date(as_of) if as_of else now.astimezone(CHINA_TZ).date().isoformat()
    if not cutoff:
        raise ValueError("invalid financial report cutoff")
    rows_by_code: dict[str, list[dict]] = {}
    for tier in ("first", "second", "third", "main", "secondary"):
        for row in pools.get(tier, []) or []:
            if isinstance(row, dict) and re.fullmatch(r"\d{6}", str(row.get("code", ""))):
                rows_by_code.setdefault(str(row["code"]), []).append(row)
    if not rows_by_code:
        return []
    cache = _load_cache(cache_path)
    stocks = cache["stocks"]
    pending: list[str] = []
    data: dict[str, dict] = {}
    for code in rows_by_code:
        entry = stocks.get(code, {})
        financials = copy.deepcopy(entry.get("financials") or {})
        if financials and (financials.get("notice_date", "") > cutoff
                           or financials.get("report_date", "") > cutoff):
            financials = {}
        fetched = _timestamp(financials.get("fetched_at"))
        fresh = bool(fetched and financials.get("as_of") == cutoff
                     and timedelta(0) <= now - fetched < timedelta(hours=CACHE_HOURS))
        retry = _timestamp(entry.get("financial_retry_after"))
        # A retry for today's data must not suppress a historical-date query.
        throttled = bool(retry and now < retry and entry.get("financial_as_of") == cutoff)
        if financials:
            financials["stale"] = not fresh
        data[code] = financials
        if not fresh and not throttled:
            pending.append(code)
    errors: list[str] = []
    if pending:
        with ThreadPoolExecutor(max_workers=min(max(1, max_workers), 6, len(pending))) as pool:
            futures = {pool.submit(fetch_financials, code, int(rows_by_code[code][0].get("market", 0)), cutoff): code
                       for code in pending}
            for future in as_completed(futures):
                code = futures[future]
                entry = stocks.setdefault(code, {})
                entry["financial_as_of"] = cutoff
                try:
                    financials = future.result()
                except Exception as exc:
                    errors.append(f"{code} financials: {type(exc).__name__}: {exc}")
                    entry["financial_retry_after"] = (now + timedelta(hours=RETRY_HOURS)).isoformat(timespec="seconds")
                    entry["financial_error"] = f"{type(exc).__name__}: {exc}"
                else:
                    financials["fetched_at"] = now.isoformat(timespec="seconds")
                    financials["as_of"] = cutoff
                    financials["stale"] = False
                    data[code] = financials
                    entry["financials"] = copy.deepcopy(financials)
                    entry.pop("financial_retry_after", None)
                    entry.pop("financial_error", None)
        _save_cache(cache_path, cache)
    for code, rows in rows_by_code.items():
        for row in rows:
            row["financials"] = copy.deepcopy(data[code])
    return errors
