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


def read_last_trade_date() -> str:
    if not STATE_PATH.exists():
        return ""
    return str(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("last_trade_date", ""))


def compact_snapshot(payload: dict) -> dict:
    minimum = int(payload.get("config", {}).get("near_match_minimum", 3))
    rows = visible_observations(payload.get("results", []), minimum)
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
