from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

import screener
from observation import visible_observations


ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "strategy" / "state.json"
HISTORY_PATH = ROOT / "results" / "history.json"
LATEST_PATH = ROOT / "results" / "latest.json"
LATEST_HTML_PATH = ROOT / "results" / "latest.html"
SNAPSHOT_PATH = ROOT / "cloud_snapshot.json"
LIVE_SEED_FORMAT = 8


def snapshot_json(payload: dict) -> str:
    """Serialize generated numeric seeds without review-only whitespace."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def normalized_trade_date(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return ""
    return value if parsed.strftime("%Y-%m-%d") == value else ""


def read_json_trade_date(path: Path, key: str) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return normalized_trade_date(payload.get(key))


def read_last_trade_date() -> str:
    # The compact snapshot is the authoritative settled base for intraday
    # calculations.  History may already contain today's provisional intraday
    # selections, so its maximum date must never be used as a close marker.
    if SNAPSHOT_PATH.exists():
        trade_date = read_json_trade_date(SNAPSHOT_PATH, "trade_date")
        if trade_date:
            return trade_date
        # A snapshot file without a valid settled date is not a usable publish
        # base.  Fail open so the next close run repairs it instead of being
        # suppressed by a newer provisional history entry.
        return ""
    if HISTORY_PATH.exists():
        close_date = read_json_trade_date(HISTORY_PATH, "last_close_trade_date")
        if close_date:
            return close_date
    return read_json_trade_date(STATE_PATH, "last_trade_date")


def read_bootstrap_trade_date() -> str:
    """Choose a settled close date for manual seed reconstruction."""
    for path, key in (
        (HISTORY_PATH, "last_close_trade_date"),
        (SNAPSHOT_PATH, "trade_date"),
        (STATE_PATH, "last_trade_date"),
    ):
        trade_date = read_json_trade_date(path, key)
        if trade_date:
            return trade_date
    return ""


def pack_live_seed(seed: dict) -> list:
    coefficients = seed["line_coefficients"]
    flags = sum(
        (
            1 if seed.get("bottom_ok") else 0,
            2 if seed.get("cross_ok") else 0,
            4 if seed.get("limit_up_ok") else 0,
            8 if seed.get("yellow_ok") else 0,
            16 if seed.get("dragon_above_tiger") else 0,
            32 if seed.get("selected") else 0,
            64 if seed.get("observation_yellow_ok") else 0,
        )
    )
    return [
        str(seed["code"]),
        str(seed.get("name", "")),
        int(seed["market"]),
        str(seed.get("base_date", "")),
        float(seed["previous_close"]),
        float(seed["min_close_15"]),
        float(seed["next_limit_price"]),
        list(seed.get("typical_13", [])),
        [
            value
            for parts in coefficients["dragon_tail"]
            for value in parts
        ],
        [
            value
            for parts in coefficients["tiger_tail"]
            for value in parts
        ],
        list(seed.get("cross_tail_dates", [])),
        str(seed.get("bottom_date", "")),
        str(seed.get("cross_date", "")),
        str(seed.get("limit_up_date", "")),
        int(seed.get("bottom_age", -1)),
        int(seed.get("cross_age", -1)),
        int(seed.get("limit_up_age", -1)),
        int(seed.get("yellow_count", 0)),
        flags,
        list(seed.get("body_low_tail", [])),
        str(seed.get("yellow_date", "")),
        list(seed.get("body_low_tail_dates", [])),
        int(seed.get("observation_yellow_count", 0)),
        str(seed.get("observation_yellow_date", "")),
        float(seed.get("next_breakout_high_5", 0.0)),
        [
            value
            for parts in coefficients.get("yellow_tail", [])
            for value in parts
        ],
        float(seed.get("dragon_value", 0.0)),
        float(seed.get("tiger_value", 0.0)),
        float(seed.get("yellow_line_value", 0.0)),
        str(seed.get("tier", "")),
        [float(value) for value in seed.get("prior_three_gap_abs", [])],
        str(seed.get("company_intro", "")),
        str(seed.get("industry", "")),
        [str(value) for value in seed.get("concepts", [])],
        int(seed.get("zig16_state", 0)),
        float(seed.get("zig16_candidate_value", 0.0) or 0.0),
        int(seed.get("zig16_candidate_age", -1)),
        str(seed.get("zig16_candidate_date", "")),
        bool(seed.get("zig16_candidate_signal_ok", False)),
        float(seed.get("bottom_price", 0.0) or 0.0),
        str(seed.get("customer_summary", "")),
    ]


def compact_snapshot(payload: dict) -> dict:
    minimum = int(payload.get("config", {}).get("near_match_minimum", 3))
    rows = visible_observations(payload.get("results", []), minimum)
    live_universe = sorted(
        [
        pack_live_seed(row["live_seed"])
        for row in payload.get("results", [])
        if isinstance(row.get("live_seed"), dict)
        and row["live_seed"].get("eligible")
        and "ST" not in str(row["live_seed"].get("name", "")).upper()
        ],
        key=lambda item: (int(item[2]), str(item[0])),
    )
    keep = (
        "code",
        "name",
        "market",
        "date",
        "close",
        "change_pct",
        "bottom_ok",
        "bottom_date",
        "bottom_price",
        "bottom_price_gap_abs",
        "cross_ok",
        "limit_up_ok",
        "yellow_ok",
        "matched_count",
        "observation_yellow_ok",
        "observation_yellow_date",
        "observation_yellow_count",
        "observation_matched_count",
        "eligible",
        "selected",
        "cross_date",
        "dragon_value",
        "tiger_value",
        "yellow_line_value",
        "tier",
        "line_gap_abs",
        "prior_three_gap_abs",
        "prior_three_gap_max",
        "company_intro",
        "industry",
        "concepts",
        "customer_summary",
    )
    return {
        "trade_date": payload.get("trade_date"),
        "generated_at": payload.get("generated_at"),
        "config": payload.get("config", {}),
        "strategy": payload.get("strategy", {}),
        "results": [{key: row.get(key) for key in keep} for row in rows],
        "live_seed_format": LIVE_SEED_FORMAT,
        "live_universe": live_universe,
    }


def bootstrap_payload(
    evaluations: list,
    cfg: dict,
    scanned: int,
    errors: list[str],
    strategy: dict,
) -> dict:
    trade_date = max((item.date for item in evaluations), default="")
    return {
        "trade_date": trade_date,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scanned": scanned,
        "errors": list(errors),
        "config": {
            key: value
            for key, value in cfg.items()
            if not key.startswith("_")
        },
        "results": [
            {
                key: value
                for key, value in (
                    asdict(item) if is_dataclass(item) else vars(item)
                ).items()
                if key != "chart"
            }
            for item in evaluations
        ],
        "strategy": strategy,
    }


def bootstrap_live_snapshot(as_of: str | None = None) -> int:
    """Build live seeds from the last settled date without changing strategy state."""
    strategy = screener.load_state(STATE_PATH)
    base_date = normalized_trade_date(as_of) if as_of else read_bootstrap_trade_date()
    if as_of and not base_date:
        raise ValueError("--as-of 必须是 YYYY-MM-DD")
    if not base_date:
        raise RuntimeError("策略状态没有可用于初始化的收盘交易日")

    cfg = screener.load_config(screener.DEFAULT_CONFIG)
    cfg["_as_of_date"] = base_date
    evaluations, errors, scanned = screener.scan_market(cfg)
    quality_error = screener.scan_quality_error(scanned, errors)
    if quality_error:
        raise RuntimeError(quality_error)
    from company_metadata import enrich_evaluations

    enrich_evaluations(evaluations, cfg["workers"])
    payload = bootstrap_payload(evaluations, cfg, scanned, errors, strategy)
    if payload["trade_date"] != base_date:
        raise RuntimeError(
            f"初始化交易日不一致：策略状态 {base_date}，行情 {payload['trade_date']}"
        )
    if screener.is_intraday_snapshot(payload["trade_date"]):
        raise RuntimeError(
            f"{payload['trade_date']} 尚未收盘：拒绝把盘中数据写入收盘快照"
        )

    SNAPSHOT_PATH.write_text(
        snapshot_json(compact_snapshot(payload)),
        encoding="utf-8",
    )
    LATEST_HTML_PATH.write_text(
        screener.render_html(
            evaluations,
            cfg,
            scanned,
            errors,
            strategy,
            [],
        ),
        encoding="utf-8",
    )
    write_github_output("changed", "true")
    write_github_output("trade_date", base_date)
    print(
        f"盘中数值种子初始化完成：基准 {base_date}，"
        f"扫描 {scanned} 只，失败 {len(errors)} 只；策略状态未修改"
    )
    return 0


def write_github_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")


def should_publish_close(trade_date: str, before: str, force: bool) -> bool:
    return bool(trade_date and (trade_date > before or force))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="云端收盘筛选与状态持久化")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--snapshot-only",
        action="store_true",
        help="从现有 latest.json 生成轻量云端快照，不重新扫描",
    )
    mode.add_argument(
        "--bootstrap-live",
        action="store_true",
        help="按最近结算日生成盘中数值种子，不修改策略状态",
    )
    parser.add_argument(
        "--as-of",
        help="配合 --bootstrap-live 指定要重建的 YYYY-MM-DD 收盘日",
    )
    args = parser.parse_args(argv)
    if args.as_of and not args.bootstrap_live:
        parser.error("--as-of 只能与 --bootstrap-live 一起使用")
    if args.bootstrap_live:
        return bootstrap_live_snapshot(args.as_of)
    if args.snapshot_only:
        payload = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
        SNAPSHOT_PATH.write_text(
            snapshot_json(compact_snapshot(payload)),
            encoding="utf-8",
        )
        print(f"云端快照已生成：{SNAPSHOT_PATH}")
        return 0

    before = read_last_trade_date()
    exit_code = screener.main([])
    if exit_code != 0:
        return exit_code
    payload = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    trade_date = str(payload.get("trade_date", ""))
    force_publish = os.environ.get("FORCE_RUN", "").strip().lower() == "true"
    changed = should_publish_close(trade_date, before, force_publish)
    if changed:
        SNAPSHOT_PATH.write_text(
            snapshot_json(compact_snapshot(payload)),
            encoding="utf-8",
        )
    write_github_output("changed", "true" if changed else "false")
    write_github_output("trade_date", trade_date)
    print(
        f"云端收盘检查：原交易日 {before or '无'}，最新交易日 {trade_date}，"
        f"强制发布={force_publish}，更新={changed}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
