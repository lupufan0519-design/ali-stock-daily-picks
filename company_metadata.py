from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USER_AGENT = "Mozilla/5.0 (compatible; AliStockDailyPicks/1.0)"
ROOT = Path(__file__).resolve().parent
DEFAULT_CACHE_PATH = ROOT / "cache" / "company_metadata.json"
CACHE_MAX_AGE_DAYS = 30
CACHE_RETRY_DELAY_HOURS = 2
INTRO_PLACEHOLDER = "公司主营业务资料正在自动补全。"
PUBLIC_METADATA_KEYS = (
    "company_intro",
    "industry",
    "concepts",
    "customer_summary",
)


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
    signals = (
        ("主营", 120),
        ("主要从事", 115),
        ("产品布局", 110),
        ("主要产品", 105),
        ("产品包括", 100),
        ("业务包括", 95),
        ("提供", 85),
        ("专注", 80),
        ("致力于", 60),
    )

    def sentence_score(value: str) -> int:
        score = max((weight for keyword, weight in signals if keyword in value), default=0)
        if any(keyword in value for keyword in ("成立于", "挂牌上市", "证券代码")):
            score -= 45
        return score

    selected = max(sentences, key=sentence_score, default="")
    if not selected:
        sector = str(industry or "").strip()
        return f"主要提供{sector}相关产品与服务。" if sector else INTRO_PLACEHOLDER

    clauses = [value for value in selected.split("，") if value]
    focus_terms = tuple(keyword for keyword, _ in signals)
    focus_index = next(
        (index for index, clause in enumerate(clauses) if any(term in clause for term in focus_terms)),
        0,
    )
    clauses = clauses[focus_index:]
    compact: list[str] = []
    for clause in clauses:
        candidate = "，".join([*compact, clause])
        if compact and len(candidate) > 68:
            break
        compact.append(clause)
        if len(candidate) >= 34:
            break
    result = ("，".join(compact) if compact else selected)[:68]
    return result.rstrip("，。；;！!") + "。"


def concise_customer_summary(profile: object) -> str:
    """Extract only customer wording that the company profile actually discloses."""
    text = re.sub(r"\s+", "", str(profile or "")).replace(",", "，")
    sentences = [
        value.strip("，。；;！!")
        for value in re.split(r"[。！!]", text)
        if value.strip("，。；;！!")
    ]
    customer_terms = (
        "主要客户",
        "核心客户",
        "客户包括",
        "客户覆盖",
        "客户群体",
        "服务客户",
        "服务于",
        "供应商",
        "合作伙伴",
    )
    selected = next(
        (sentence for sentence in sentences if any(term in sentence for term in customer_terms)),
        "",
    )
    if not selected:
        return ""
    return selected[:96].rstrip("，。；;！!") + "。"


def _empty_cache() -> dict:
    return {"schema_version": 2, "stocks": {}}


def _load_cache(path: Path | None) -> dict:
    if path is None or not path.exists():
        return _empty_cache()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _empty_cache()
    if not isinstance(payload, dict) or not isinstance(payload.get("stocks"), dict):
        return _empty_cache()
    return payload


def _save_cache(path: Path | None, payload: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _cached_metadata(entry: object) -> dict:
    value = entry if isinstance(entry, dict) else {}
    concepts = value.get("concepts", [])
    return {
        "company_intro": str(value.get("company_intro") or "").strip(),
        "industry": str(value.get("industry") or "").strip(),
        "concepts": [str(item).strip() for item in concepts if str(item).strip()][:3]
        if isinstance(concepts, list)
        else [],
        "customer_summary": str(value.get("customer_summary") or "").strip(),
    }


def _cache_is_fresh(entry: object, now: datetime) -> bool:
    if not isinstance(entry, dict):
        return False
    # Refresh schema-v1 rows once so the newly added customer field is not
    # suppressed by an otherwise fresh 30-day cache entry. An explicit empty
    # string is valid when the company does not disclose customer information.
    if "customer_summary" not in entry:
        return False
    try:
        retry_after = datetime.fromisoformat(
            str(entry.get("retry_after", "")).replace("Z", "+00:00")
        )
    except ValueError:
        retry_after = None
    if retry_after is not None:
        if retry_after.tzinfo is None:
            retry_after = retry_after.replace(tzinfo=timezone.utc)
        if now < retry_after.astimezone(timezone.utc):
            return True
    try:
        updated_at = datetime.fromisoformat(str(entry.get("updated_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return now - updated_at.astimezone(timezone.utc) <= timedelta(days=CACHE_MAX_AGE_DAYS)


def _merge_metadata(fetched: object, cached: object, industry: object = "") -> dict:
    fresh = _cached_metadata(fetched)
    old = _cached_metadata(cached)
    intro = fresh["company_intro"]
    if not intro or intro == INTRO_PLACEHOLDER or intro.endswith("相关产品与服务。"):
        intro = old["company_intro"]
    sector = fresh["industry"] or old["industry"] or str(industry or "").strip()
    concepts = fresh["concepts"] or old["concepts"]
    customer_summary = fresh["customer_summary"] or old["customer_summary"]
    if not intro:
        intro = f"主要提供{sector}相关产品与服务。" if sector else INTRO_PLACEHOLDER
    return {
        "company_intro": intro,
        "industry": sector,
        "concepts": concepts[:3],
        "customer_summary": customer_summary,
    }


def _apply_metadata(item: object, metadata: dict) -> None:
    for key in PUBLIC_METADATA_KEYS:
        value = metadata.get(key, [] if key == "concepts" else "")
        setattr(item, key, value)
    seed = getattr(item, "live_seed", None)
    if isinstance(seed, dict):
        seed.update({key: metadata[key] for key in PUBLIC_METADATA_KEYS})


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
    quote_data = quote.get("data") or {}
    needs_core = not str(quote_data.get("f127") or "").strip() or not str(
        quote_data.get("f129") or ""
    ).strip()
    try:
        core = _get_json(core_url) if needs_core else {}
    except Exception:
        core = {}
    basics = (survey.get("jbzl") or [{}])[0]
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
        "customer_summary": concise_customer_summary(basics.get("ORG_PROFILE", "")),
    }


def enrich_evaluations(
    evaluations: Iterable[object],
    max_workers: int = 6,
    cache_path: Path | None = DEFAULT_CACHE_PATH,
) -> list[str]:
    targets = [
        item
        for item in evaluations
        if bool(getattr(item, "eligible", True))
        and bool(getattr(item, "bottom_ok", False))
    ]
    if not targets:
        return []
    cache = _load_cache(cache_path)
    cached_stocks = cache["stocks"]
    now = datetime.now(timezone.utc)
    errors: list[str] = []
    refresh_targets: list[object] = []
    for item in targets:
        code = str(getattr(item, "code", ""))
        cached = cached_stocks.get(code, {})
        if cached:
            _apply_metadata(item, _merge_metadata({}, cached))
        if not cached or not _cache_is_fresh(cached, now):
            refresh_targets.append(item)
    if not refresh_targets:
        return []

    cache_changed = False
    workers = min(max(1, max_workers), len(refresh_targets))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                fetch_company_metadata,
                str(getattr(item, "code", "")),
                int(getattr(item, "market", 0)),
            ): item
            for item in refresh_targets
        }
        for future in as_completed(futures):
            item = futures[future]
            code = str(getattr(item, "code", ""))
            cached = cached_stocks.get(code, {})
            try:
                metadata = _merge_metadata(
                    future.result(),
                    cached,
                    getattr(item, "industry", ""),
                )
            except Exception as exc:
                errors.append(
                    f"{code} company metadata: "
                    f"{type(exc).__name__}: {exc}"
                )
                metadata = _merge_metadata({}, cached, getattr(item, "industry", ""))
                cached_stocks[code] = {
                    **(cached if isinstance(cached, dict) else {}),
                    **metadata,
                    "market": int(getattr(item, "market", 0)),
                    "retry_after": (now + timedelta(hours=CACHE_RETRY_DELAY_HOURS)).isoformat(
                        timespec="seconds"
                    ),
                    "last_error": f"{type(exc).__name__}: {exc}",
                }
                cache_changed = True
            else:
                updated_cache = {
                    **(cached if isinstance(cached, dict) else {}),
                    **metadata,
                    "market": int(getattr(item, "market", 0)),
                    "updated_at": now.isoformat(timespec="seconds"),
                }
                updated_cache.pop("retry_after", None)
                updated_cache.pop("last_error", None)
                cached_stocks[code] = updated_cache
                cache_changed = True
            _apply_metadata(item, metadata)
    if cache_changed:
        cache["schema_version"] = 2
        cache["updated_at"] = now.isoformat(timespec="seconds")
        _save_cache(cache_path, cache)
    return errors


def enrich_live_pools(
    pools: object,
    max_workers: int = 4,
    cache_path: Path | None = DEFAULT_CACHE_PATH,
) -> list[str]:
    if not isinstance(pools, dict):
        return []
    rows_by_code: dict[str, list[dict]] = {}
    for name in ("first", "second", "third", "main", "secondary"):
        values = pools.get(name, [])
        if not isinstance(values, list):
            continue
        for row in values:
            if not isinstance(row, dict) or not row.get("code"):
                continue
            rows_by_code.setdefault(str(row["code"]), []).append(row)
    proxies: list[SimpleNamespace] = []
    for code, rows in rows_by_code.items():
        representative = rows[0]
        proxies.append(
            SimpleNamespace(
                code=code,
                market=int(representative.get("market", 0)),
                bottom_ok=True,
                eligible=True,
                live_seed=representative,
                company_intro=str(representative.get("company_intro", "")),
                industry=str(representative.get("industry", "")),
                concepts=list(representative.get("concepts", []) or []),
                customer_summary=str(representative.get("customer_summary", "")),
            )
        )
    errors = enrich_evaluations(proxies, max_workers, cache_path)
    for proxy in proxies:
        metadata = {key: getattr(proxy, key) for key in PUBLIC_METADATA_KEYS}
        for row in rows_by_code[proxy.code]:
            row.update(metadata)
    return errors
