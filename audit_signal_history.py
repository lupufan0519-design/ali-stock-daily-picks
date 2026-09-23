"""Audit observed selections; never manufacture historical recommendations."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from daily_market_data import fetch_reference_sessions
from selection_history import audit_history_signals

ROOT = Path(__file__).resolve().parent
CHINA = timezone(timedelta(hours=8))


def repair_history(path: Path, sessions: list[str], *, stale_from: str = "",
                   stale_through: str = "", stale_base: str = "",
                   apply: bool = False, now: str = "") -> dict:
    original = path.read_bytes()
    history = json.loads(original.decode("utf-8"))
    stamp = now or datetime.now(CHINA).isoformat(timespec="seconds")
    provenance = {
        day["trade_date"]: stale_base for day in history.get("dates", [])
        if stale_base and stale_from <= day.get("trade_date", "") <= stale_through
    }
    corrected, counts = audit_history_signals(history, sessions, provenance, stamp)
    daily = []
    for old, new in zip(history.get("dates", []), corrected.get("dates", [])):
        before = sum(len(old.get(tier, [])) for tier in ("first", "second", "third"))
        after = sum(len(new.get(tier, [])) for tier in ("first", "second", "third"))
        if before != after:
            daily.append({"trade_date": old["trade_date"], "before": before,
                          "after": after, "quarantined": before - after})
    report = {"audited_at": stamp, "applied": apply, "source_sha256": hashlib.sha256(original).hexdigest(),
              "calendar_first": min(sessions, default=""), "calendar_last": max(sessions, default=""),
              "known_stale_base": {"from": stale_from, "through": stale_through, "base": stale_base},
              "counts": counts, "daily": daily,
              "policy": "Original observed selections retained in correction records; no hindsight backfill."}
    if apply:
        backup_dir = path.parent.parent / ".codex" / "audits" / (
            "signal-history-" + datetime.now(CHINA).strftime("%Y%m%dT%H%M%S%f"))
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup = backup_dir / path.name
        shutil.copy2(path, backup)
        report["backup"] = str(backup)
        # Write and replace on the same filesystem; never lose the original backup.
        temporary = path.with_suffix(".repair.tmp")
        temporary.write_text(json.dumps(corrected, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        (backup_dir / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check historical signal windows; dry run by default")
    parser.add_argument("--history", type=Path, default=ROOT / "results" / "history.json")
    parser.add_argument("--stale-from", default="")
    parser.add_argument("--stale-through", default="")
    parser.add_argument("--stale-base", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    supplied = [args.stale_from, args.stale_through, args.stale_base]
    if any(supplied) and not all(supplied):
        parser.error("A known stale interval requires --stale-from, --stale-through and --stale-base")
    if all(supplied):
        for value in supplied:
            if datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") != value:
                parser.error("Dates must be YYYY-MM-DD")
        if not args.stale_base < args.stale_from <= args.stale_through:
            parser.error("Expected stale-base < stale-from <= stale-through")
    sessions = fetch_reference_sessions()
    report = repair_history(args.history, sessions, stale_from=args.stale_from,
                            stale_through=args.stale_through, stale_base=args.stale_base,
                            apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
