import unittest
from datetime import datetime

from cloud_daily import compact_snapshot
from intraday import collect_targets, market_state, parse_tencent_quotes


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


if __name__ == "__main__":
    unittest.main()
