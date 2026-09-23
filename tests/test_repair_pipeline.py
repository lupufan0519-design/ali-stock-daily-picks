import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import cloud_daily
from audit_signal_history import repair_history
from cloud_gate import should_screen
from rebuild_ui import rebuild_ui


class RepairPipelineTests(unittest.TestCase):
    def test_before_open_can_repair_completed_session_not_current_intraday(self):
        self.assertTrue(should_screen(datetime(2026, 9, 23, 9), "2026-09-09", "2026-09-22")[0])
        self.assertFalse(should_screen(datetime(2026, 9, 23, 9), "2026-09-22", "2026-09-22")[0])
        self.assertFalse(should_screen(datetime(2026, 9, 23, 10), "2026-09-09", "2026-09-22")[0])
        self.assertFalse(should_screen(datetime(2026, 9, 23, 9), "2026-09-09", "2026-09-23")[0])
        self.assertFalse(should_screen(datetime(2026, 9, 26, 9), "2026-09-09", "2026-09-25")[0])

    def test_close_cutoff_is_forwarded_to_actual_scan(self):
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        with patch.object(cloud_daily, "read_last_trade_date", return_value="2026-09-09"), \
             patch.object(cloud_daily.screener, "main", return_value=4) as scan:
            self.assertEqual(cloud_daily.main(["--close-as-of", today]), 4)
            scan.assert_called_once_with(["--as-of", today])

    def test_next_morning_recovery_never_backfills_recommendations(self):
        with patch.object(cloud_daily, "bootstrap_live_snapshot", return_value=0) as recover, \
             patch.object(cloud_daily.screener, "main") as scan:
            self.assertEqual(cloud_daily.main(["--close-as-of", "2020-01-02"]), 0)
            recover.assert_called_once_with("2020-01-02")
            scan.assert_not_called()

    def test_bootstrap_does_not_regress_a_repaired_snapshot(self):
        with patch.object(cloud_daily, "read_json_trade_date", side_effect=["2026-09-09", "2026-09-22"]):
            self.assertEqual(cloud_daily.read_bootstrap_trade_date(), "2026-09-22")

    def test_history_dry_run_backup_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results" / "history.json"
            path.parent.mkdir()
            original = json.dumps({"dates": [{"trade_date": "2026-09-22", "first": [
                {"code": "002132", "bottom_date": "2026-09-07", "selected_price": 4.21}],
                "second": [], "third": [], "live_active_codes": ["002132"]}]})
            path.write_text(original, encoding="utf-8")
            sessions = ["2026-09-07", "2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22"]
            self.assertEqual(repair_history(path, sessions)["counts"]["moved_count"], 1)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            report = repair_history(path, sessions, apply=True)
            self.assertEqual(Path(report["backup"]).read_text(encoding="utf-8"), original)
            repaired = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(repaired["dates"][0]["first"], [])
            self.assertEqual(repaired["dates"][0]["removed"][0]["original_record"]["selected_price"], 4.21)
            self.assertEqual(repair_history(path, sessions)["counts"]["moved_count"], 0)

    def test_rebuild_preserves_blocked_state_and_true_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            (root / "cloud_snapshot.json").write_text(json.dumps({"trade_date": "2026-09-09", "config": {}}), encoding="utf-8")
            live = {"live_trade_date": "2026-09-22", "selection_status": "blocked", "available": False,
                    "signal_base_date": "2026-09-09", "selection_note": "stale baseline", "live_pools": {"available": False}}
            (root / "results" / "live.json").write_text(json.dumps(live), encoding="utf-8")
            with patch("rebuild_ui.render_report", return_value="ok") as render:
                rebuild_ui(root)
            self.assertEqual(render.call_args.kwargs["live_state"], live)


if __name__ == "__main__":
    unittest.main()
