import unittest
from datetime import datetime
from types import SimpleNamespace

from cloud_daily import compact_snapshot
from intraday import (
    collect_targets,
    market_state,
    normalize_quote_time,
    parse_tencent_quotes,
)
from report_ui import LIVE_SCRIPT, _evaluation_row, _position_row


class CloudWorkflowTests(unittest.TestCase):
    def test_intraday_targets_exclude_st_and_keep_pool(self):
        payload = {
            "config": {"near_match_minimum": 3},
            "strategy": {
                "active": [
                    {"code": "600001", "name": "主选示例", "market": 1},
                    {"code": "600002", "name": "ST示例", "market": 1},
                ],
                "secondary_active": [
                    {"code": "000001", "name": "次选示例", "market": 0}
                ],
            },
            "results": [
                {
                    "code": "300001",
                    "name": "观察示例",
                    "market": 0,
                    "eligible": True,
                    "selected": False,
                    "matched_count": 3,
                    "cross_ok": True,
                    "bottom_ok": False,
                    "yellow_ok": True,
                    "limit_up_ok": True,
                    "cross_date": "2026-07-24",
                }
            ],
        }
        targets = collect_targets(payload)
        self.assertEqual(
            {item["code"] for item in targets},
            {"600001", "000001", "300001"},
        )

    def test_intraday_targets_cover_all_visible_observations_by_default(self):
        rows = [
            {
                "code": f"30{index:04d}",
                "name": f"观察{index}",
                "market": 0,
                "eligible": True,
                "selected": False,
                "matched_count": 3,
                "cross_ok": True,
                "bottom_ok": False,
                "yellow_ok": True,
                "limit_up_ok": True,
                "cross_date": "2026-07-24",
            }
            for index in range(30)
        ]
        payload = {
            "config": {"near_match_minimum": 3},
            "strategy": {"active": [], "secondary_active": []},
            "results": rows,
        }
        self.assertEqual(
            {item["code"] for item in collect_targets(payload)},
            {row["code"] for row in rows},
        )
        self.assertEqual(len(collect_targets(payload, observation_limit=12)), 12)

    def test_snapshot_and_live_targets_share_visible_top_30(self):
        rows = [
            {
                "code": f"30{index:04d}",
                "name": f"观察{index}",
                "market": 0,
                "eligible": True,
                "selected": False,
                "matched_count": 3 + (index % 2),
                "cross_ok": index % 3 != 0,
                "bottom_ok": index % 5 == 0,
                "yellow_ok": index % 4 != 0,
                "limit_up_ok": index % 7 == 0,
                "cross_date": f"2026-07-{(index % 28) + 1:02d}",
                "bottom_date": f"2026-06-{(index % 28) + 1:02d}",
            }
            for index in range(45)
        ]
        payload = {
            "trade_date": "2026-07-24",
            "config": {"near_match_minimum": 3},
            "strategy": {"active": [], "secondary_active": []},
            "results": rows,
        }
        snapshot = compact_snapshot(payload)
        targets = collect_targets(snapshot)
        self.assertEqual(len(snapshot["results"]), 30)
        self.assertEqual(
            {row["code"] for row in snapshot["results"]},
            {target["code"] for target in targets},
        )

    def test_compact_snapshot_keeps_only_relevant_rows(self):
        payload = {
            "trade_date": "2026-07-24",
            "generated_at": "2026-07-24T15:20:00+08:00",
            "config": {"near_match_minimum": 3},
            "strategy": {"active": [], "secondary_active": []},
            "results": [
                {
                    "code": "600001",
                    "name": "保留",
                    "market": 1,
                    "eligible": True,
                    "selected": False,
                    "matched_count": 3,
                    "cross_ok": True,
                    "bottom_ok": False,
                    "yellow_ok": True,
                    "limit_up_ok": True,
                    "cross_date": "2026-07-24",
                    "unused": "drop",
                },
                {
                    "code": "600002",
                    "name": "忽略",
                    "market": 1,
                    "eligible": True,
                    "selected": False,
                    "matched_count": 2,
                },
            ],
        }
        snapshot = compact_snapshot(payload)
        self.assertEqual([row["code"] for row in snapshot["results"]], ["600001"])
        self.assertNotIn("unused", snapshot["results"][0])

    def test_market_state_labels_trading_session(self):
        label, _ = market_state(datetime(2026, 7, 24, 10, 0))
        self.assertEqual(label, "盘中行情")
        label, _ = market_state(datetime(2026, 7, 24, 12, 0))
        self.assertEqual(label, "午间休市")

    def test_parse_tencent_quotes_uses_realtime_timestamp(self):
        raw = (
            'v_sz002038="51~双鹭药业~002038~5.57~5.29~5.27~258234'
            + "~0" * 23
            + "~20260727104200~0.28~5.29~5.70~5.22"
            + '~5.57/258234/142691351~";'
        )
        quotes = parse_tencent_quotes(
            raw,
            [
                {
                    "code": "002038",
                    "name": "双鹭药业",
                    "market": 0,
                    "scope": "observation",
                }
            ],
        )
        self.assertEqual(quotes["002038"]["price"], 5.57)
        self.assertEqual(quotes["002038"]["change_pct"], 5.29)
        self.assertEqual(
            quotes["002038"]["server_time"],
            "2026-07-27T10:42:00+08:00",
        )
        self.assertEqual(quotes["002038"]["amount"], 142691351.0)

    def test_quote_time_normalizes_iso_and_time_only_formats(self):
        now = datetime(2026, 7, 31, 10, 30)
        self.assertEqual(
            normalize_quote_time("2026-07-31T10:15:20+08:00", now),
            "2026-07-31T10:15:20+08:00",
        )
        self.assertEqual(
            normalize_quote_time("15:17:58.099", now),
            "2026-07-31T15:17:58+08:00",
        )

    def test_live_rows_expose_and_update_quote_time(self):
        position = {
            "code": "600001",
            "name": "主选示例",
            "market": 1,
            "entry_price": 10.0,
            "entry_date": "2026-07-20",
            "last_close": 10.5,
            "last_date": "2026-07-24",
            "return_pct": 5.0,
            "holding_days": 4,
            "missing_streak": 0,
            "status": "跟踪中",
        }
        item = SimpleNamespace(
            code="300001",
            name="观察示例",
            market=0,
            date="2026-07-24",
            close=12.3,
            change_pct=1.2,
            chart="<svg></svg>",
            cross_ok=True,
            cross_date="2026-07-24",
            bottom_ok=False,
            bottom_date="",
            yellow_ok=True,
            yellow_count=2,
            limit_up_ok=True,
            limit_up_date="2026-07-01",
        )
        self.assertIn("data-live-time", _position_row(position))
        self.assertIn("data-live-time", _evaluation_row(item, observation=True))
        self.assertIn("quote.server_time", LIVE_SCRIPT)
        self.assertIn('row.querySelector("[data-live-time]")', LIVE_SCRIPT)
        self.assertIn("time.textContent =", LIVE_SCRIPT)
        self.assertIn("formatQuoteTime", LIVE_SCRIPT)


if __name__ == "__main__":
    unittest.main()
