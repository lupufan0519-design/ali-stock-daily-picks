from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USER_AGENT = "Mozilla/5.0 (compatible; AliStockDailyPicks/1.0)"


def _get_json(url: str, timeout: float = 8.0) -> dict:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Referer": "https://quote.eastmoney.com/",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # public data endpoints occasionally reset
            last_error = exc
            if attempt == 0:
                time.sleep(0.25)
    if last_error is not None:
        raise last_error
    return {}


def concise_company_intro(profile: object, industry: object = "") -> str:
    text = re.sub(r"\s+", "", str(profile or "")).replace(",", "，")
    listed = re.search(r"上市公司\(\d+\)，", text)
    if listed:
        text = text[listed.end() :]
    sentences = [
        value.strip("，。；;！!")
        for value in re.split(r"[。！!]", text)
        if value.strip("，。；;！!")
    ]
    priorities = ("主营", "专注", "主要从事", "核心业务", "致力于", "提供")
    selected = ""
    for keyword in priorities:
        selected = next((value for value in sentences if keyword in value), "")
        if selected:
            break
    if not selected and sentences:
        selected = sentences[0]
    if not selected:
        sector = str(industry or "").strip()
        return f"专注于{sector}相关业务。" if sector else "公司业务简介暂缺。"

    clauses = [value for value in selected.split("，") if value]
    compact: list[str] = []
    for clause in clauses:
        candidate = "，".join([*compact, clause])
        if compact and len(candidate) > 68:
            break
        compact.append(clause)
        if len(candidate) >= 34:
            break
    result = "，".join(compact) if compact else selected[:68]
    return result.rstrip("，。；;！!") + "。"


def fetch_company_metadata(code: str, market: int) -> dict:
    prefix = "SH" if int(market) == 1 else "SZ"
    survey_url = (
        "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?"
        + urlencode({"code": prefix + str(code)})
    )
    quote_url = (
        "https://push2.eastmoney.com/api/qt/stock/get?"
        + urlencode(
            {
                "secid": f"{int(market)}.{code}",
                "fields": "f57,f58,f127,f128,f129",
            }
        )
    )
    core_url = (
        "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?"
        + urlencode({"code": prefix + str(code)})
    )
    try:
        survey = _get_json(survey_url)
    except Exception:
        survey = {}
    try:
        quote = _get_json(quote_url)
    except Exception:
        quote = {}
    try:
        core = _get_json(core_url) if not quote.get("data") else {}
    except Exception:
        core = {}
    basics = (survey.get("jbzl") or [{}])[0]
    quote_data = quote.get("data") or {}
    industry = str(quote_data.get("f127") or "").strip()
    boards = sorted(
        [item for item in core.get("ssbk", []) if isinstance(item, dict)],
        key=lambda item: int(item.get("BOARD_RANK", 999) or 999),
    )
    if not industry and len(boards) >= 2:
        industry = str(boards[1].get("BOARD_NAME") or "").strip()
    if not industry:
        hierarchy = str(basics.get("EM2016") or "").split("-")
        industry = hierarchy[-1].strip() if hierarchy else ""
    concepts = [
        value.strip()
        for value in re.split(r"[,，]", str(quote_data.get("f129") or ""))
        if value.strip()
    ][:3]
    if not concepts and boards:
        excluded = re.compile(
            r"板块$|风格$|成长$|股$|重仓$|综$|MSCI|沪股通|深股通|"
            r"融资融券|上证|深证|HS300|富时|QFII|AH股"
        )
        concepts = [
            name
            for item in reversed(boards[3:])
            if (name := str(item.get("BOARD_NAME") or "").strip())
            and not excluded.search(name)
        ][:3]
    if not survey and not quote and not core:
        raise RuntimeError("company metadata endpoints returned no data")
    return {
        "company_intro": concise_company_intro(
            basics.get("ORG_PROFILE", ""),
            industry,
        ),
        "industry": industry,
        "concepts": concepts,
    }


def enrich_evaluations(evaluations: Iterable[object], max_workers: int = 6) -> list[str]:
    targets = [
        item
        for item in evaluations
        if bool(getattr(item, "eligible", True))
        and bool(getattr(item, "bottom_ok", False))
    ]
    if not targets:
        return []
    errors: list[str] = []
    workers = min(max(1, max_workers), len(targets))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                fetch_company_metadata,
                str(getattr(item, "code", "")),
                int(getattr(item, "market", 0)),
            ): item
            for item in targets
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                metadata = future.result()
            except Exception as exc:
                errors.append(
                    f"{getattr(item, 'code', '')} company metadata: "
                    f"{type(exc).__name__}: {exc}"
                )
                metadata = {
                    "company_intro": "公司业务简介暂缺。",
                    "industry": "",
                    "concepts": [],
                }
            for key, value in metadata.items():
                setattr(item, key, value)
            seed = getattr(item, "live_seed", None)
            if isinstance(seed, dict):
                seed.update(metadata)
    return errors
