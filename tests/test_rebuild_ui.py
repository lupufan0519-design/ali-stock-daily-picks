import json
import tempfile
import unittest
from pathlib import Path

from rebuild_ui import rebuild_ui


class RebuildUiTests(unittest.TestCase):
    def test_rebuilds_current_ui_without_a_full_market_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            results.mkdir()
            (root / "cloud_snapshot.json").write_text(
                json.dumps(
                    {
                        "trade_date": "2026-08-07",
                        "config": {"line_gap_max_abs": 0.5},
                    }
                ),
                encoding="utf-8",
            )
            (results / "live.json").write_text(
                json.dumps(
                    {
                        "live_trade_date": "2026-08-07",
                        "target_count": 4966,
                        "live_pools": {
                            "first": [],
                            "second": [],
                            "third": [],
                        },
                        "history": {
                            "schema_version": 1,
                            "strategy_version": "three_tier_confirmed_bottom4_v6",
                            "started_on": "2026-08-07",
                            "dates": [],
                            "summary": {},
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = rebuild_ui(root)
            page = output.read_text(encoding="utf-8")
            self.assertIn("2026-08-07", page)
            self.assertIn('class="view-dock"', page)
            self.assertIn("position: sticky", page)


if __name__ == "__main__":
    unittest.main()
