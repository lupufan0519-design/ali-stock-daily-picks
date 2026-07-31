from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import screener
from observation import visible_observations


ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "strategy" / "state.json"
LATEST_PATH = ROOT / "results" / "latest.json"
SNAPSHOT_PATH = ROOT / "cloud_snapshot.json"
LIVE_SEED_FORMAT = 1


def read_last_trade_date() -> str:
    if not STATE_PATH.exists():
        return ""
    return str(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("last_trade_date", ""))


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
    ]


def compact_snapshot(payload: dict) -> dict:
    minimum = int(payload.get("config", {}).get("near_match_minimum", 3))
    rows = visible_observations(payload.get("results", []), minimum)
    live_universe = [
        pack_live_seed(row["live_seed"])
        for row in payload.get("results", [])
        if isinstance(row.get("live_seed"), dict)
        and row["live_seed"].get("eligible")
        and "ST" not in str(row["live_seed"].get("name", "")).upper()
    ]
    keep = {
        "code",
        "name",
        "market",
        "date",
        "close",
        "change_pct",
        "bottom_ok",
        "cross_ok",
        "limit_up_ok",
        "yellow_ok",
        "matched_count",
        "eligible",
        "selected",
        "cross_date",
    }
    return {
        "trade_date": payload.get("trade_date"),
        "generated_at": payload.get("generated_at"),
        "config": payload.get("config", {}),
        "strategy": payload.get("strategy", {}),
        "results": [{key: row.get(key) for key in keep} for row in rows],
        "live_seed_format": LIVE_SEED_FORMAT,
        "live_universe": live_universe,
    }


def write_github_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="云端收盘筛选与状态持久化")
    parser.add_argument(
        "--snapshot-only",
        action="store_true",
        help="从现有 latest.json 生成轻量云端快照，不重新扫描",
    )
    args = parser.parse_args(argv)
    if args.snapshot_only:
        payload = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
        SNAPSHOT_PATH.write_text(
            json.dumps(compact_snapshot(payload), ensure_ascii=False, indent=2),
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
    changed = bool(trade_date and trade_date > before)
    if changed:
        SNAPSHOT_PATH.write_text(
            json.dumps(compact_snapshot(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    write_github_output("changed", "true" if changed else "false")
    write_github_output("trade_date", trade_date)
    print(f"云端收盘检查：原交易日 {before or '无'}，最新交易日 {trade_date}，更新={changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
