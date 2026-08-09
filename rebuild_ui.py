from __future__ import annotations

import json
from pathlib import Path

from selection_history import empty_history
from simple_report_ui import render_report
from simple_strategy import FIRST_TIER, SECOND_TIER, THIRD_TIER


ROOT = Path(__file__).resolve().parent


def rebuild_ui(root: Path = ROOT) -> Path:
    snapshot_path = root / "cloud_snapshot.json"
    live_path = root / "results" / "live.json"
    output_path = root / "results" / "latest.html"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    live = json.loads(live_path.read_text(encoding="utf-8"))
    pools = live.get("live_pools", {})
    rows = [
        dict(item)
        for tier in (FIRST_TIER, SECOND_TIER, THIRD_TIER)
        for item in pools.get(tier, [])
        if isinstance(item, dict)
    ]
    trade_date = str(
        live.get("live_trade_date")
        or live.get("close_trade_date")
        or snapshot.get("trade_date", "")
    )
    history = live.get("history")
    if not isinstance(history, dict):
        history = empty_history(trade_date)
    output_path.write_text(
        render_report(
            rows,
            snapshot.get("config", {}),
            int(live.get("target_count", 0) or 0),
            [],
            history=history,
            trade_date_override=trade_date,
        ),
        encoding="utf-8",
    )
    print(f"UI 已按现有行情快照重建：{output_path}")
    return output_path


if __name__ == "__main__":
    rebuild_ui()
