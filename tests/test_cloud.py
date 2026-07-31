import unittest
from datetime import datetime
from types import SimpleNamespace

from cloud_gate import parse_tencent_trade_date, should_screen
from cloud_daily import compact_snapshot
from intraday import (
    build_live_pools,
    collect_targets,
    evaluate_live_seed,
    market_state,
    normalize_quote_time,
    parse_tencent_quotes,
    unpack_live_seed,
)
from report_ui import LIVE_SCRIPT, _evaluation_row, _position_row


class CloudWorkflowTests(unittest.TestCase):
    @staticmethod
    def live_seed(code="600001", bottom_age=0, limit_age=0, name="实时示例"):
        return {
            "code": code,
            "name": name,
            "market": 1,
            "base_date": "2026-07-30",
            "previous_close": 10.0,
            "min_close_15": 9.0,
            "typical_13": [10.0] * 13,
            "next_limit_price": 11.0,
            "line_coefficients": {
                "dragon": [11.0, 0.0, 0.0],
                "tiger": [10.0, 0.0, 0.0],
                "previous_dragon": [9.0, 0.0, 0.0],
                "previous_tiger": [10.0, 0.0, 0.0],
                "dragon_tail": [
                    [value, 0.0, 0.0]
                    for value in [9.0, 9.0, 9.0, 9.0, 9.0, 11.0]
                ],
                "tiger_tail": [
                    [10.0, 0.0, 0.0]
                    for _ in range(6)
                ],
            },
            "cross_tail_dates": [
                "2026-07-27",
                "2026-07-28",
                "2026-07-29",
                "2026-07-30",
            ],
            "bottom_date": "2026-07-30" if bottom_age >= 0 else "",
            "cross_date": "",
            "limit_up_date": "2026-07-15" if limit_age >= 0 else "",
            "bottom_age": bottom_age,
            "cross_age": -1,
            "limit_up_age": limit_age,
            "bottom_ok": bottom_age >= 0,
            "cross_ok": False,
            "limit_up_ok": limit_age >= 0,
            "yellow_ok": False,
            "yellow_count": 0,
            "matched_count": int(bottom_age >= 0) + int(limit_age >= 0),
            "dragon_above_tiger": False,
            "eligible": "ST" not in name.upper(),
            "selected": False,
        }

    @staticmethod
    def live_quote(code="600001"):
        return {
            "code": code,
            "name": "实时示例",
            "market": 1,
            "price": 10.5,
            "pre_close": 10.0,
            "open": 10.0,
            "high": 11.5,
            "low": 9.5,
            "change_pct": 5.0,
            "server_time": "2026-07-31T10:30:00+08:00",
        }

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

    def test_live_universe_drives_full_market_quote_targets(self):
        payload = {
            "live_universe": [
                self.live_seed("600001"),
                self.live_seed("600002", bottom_age=-1, limit_age=-1),
                self.live_seed("600003", name="ST示例"),
            ],
            "strategy": {"active": [], "secondary_active": []},
            "results": [],
        }
        self.assertEqual(
            [item["code"] for item in collect_targets(payload)],
            ["600001", "600002"],
        )

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

    def test_compact_snapshot_keeps_live_seed_for_every_eligible_stock(self):
        payload = {
            "trade_date": "2026-07-30",
            "config": {"near_match_minimum": 3},
            "strategy": {"active": [], "secondary_active": []},
            "results": [
                {
                    "code": "600001",
                    "name": "全市场种子",
                    "market": 1,
                    "eligible": True,
                    "selected": False,
                    "matched_count": 1,
                    "live_seed": self.live_seed("600001"),
                }
            ],
        }
        snapshot = compact_snapshot(payload)
        self.assertEqual(snapshot["live_seed_format"], 1)
        self.assertEqual(
            [item[0] for item in snapshot["live_universe"]],
            ["600001"],
        )
        seed = unpack_live_seed(
            snapshot["live_universe"][0],
            snapshot["live_seed_format"],
        )
        self.assertEqual(seed["code"], "600001")
        self.assertTrue(seed["eligible"])

    def test_live_seed_recomputes_primary_and_secondary_without_settlement(self):
        cfg = {
            "bottom_lookback_days": 5,
            "cross_lookback_days": 5,
            "limit_up_lookback_days": 42,
            "yellow_consecutive_days": 1,
        }
        primary_seed = self.live_seed("600001")
        primary_quote = self.live_quote("600001")
        primary = evaluate_live_seed(
            primary_seed,
            primary_quote,
            cfg,
            "2026-07-30",
        )
        self.assertTrue(primary["selected"])
        self.assertTrue(primary["yellow_ok"])
        self.assertEqual(primary["yellow_count"], 1)

        secondary_seed = self.live_seed(
            "600002",
            bottom_age=-1,
            limit_age=0,
        )
        secondary_quote = self.live_quote("600002")
        pools = build_live_pools(
            {
                "trade_date": "2026-07-30",
                "config": cfg,
                "live_universe": [primary_seed, secondary_seed],
            },
            {
                "600001": primary_quote,
                "600002": secondary_quote,
            },
        )
        self.assertEqual([row["code"] for row in pools["main"]], ["600001"])
        self.assertEqual(
            [row["code"] for row in pools["secondary"]],
            ["600002"],
        )

    def test_live_cross_recomputes_the_full_five_day_window(self):
        cfg = {
            "bottom_lookback_days": 5,
            "cross_lookback_days": 5,
            "limit_up_lookback_days": 42,
            "yellow_consecutive_days": 1,
        }
        seed = self.live_seed("600010", bottom_age=-1, limit_age=-1)
        seed["line_coefficients"]["dragon_tail"] = [
            [value, 0.0, 0.0]
            for value in [8.0, 9.0, 11.0, 12.0, 13.0, 14.0]
        ]
        seed["line_coefficients"]["tiger_tail"] = [
            [10.0, 0.0, 0.0]
            for _ in range(6)
        ]
        seed["cross_tail_dates"] = [
            "2026-07-27",
            "2026-07-28",
            "2026-07-29",
            "2026-07-30",
        ]
        row = evaluate_live_seed(
            seed,
            self.live_quote("600010"),
            cfg,
            "2026-07-30",
        )
        self.assertTrue(row["cross_ok"])
        self.assertEqual(row["cross_date"], "2026-07-28")

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
        now = datetime(2026, 7, 31, 16, 30)
        self.assertEqual(
            normalize_quote_time("2026-07-31T10:15:20+08:00", now),
            "2026-07-31T10:15:20+08:00",
        )
        self.assertEqual(
            normalize_quote_time("15:17:58.099", now),
            "2026-07-31T15:17:58+08:00",
        )
        self.assertEqual(
            normalize_quote_time("15:00:00", datetime(2026, 7, 27, 9, 15)),
            "2026-07-24T15:00:00+08:00",
        )

    def test_close_gate_skips_weekends_duplicates_and_holidays(self):
        friday = datetime(2026, 7, 31, 15, 40)
        self.assertEqual(
            should_screen(friday, "2026-07-30", "2026-07-31"),
            (True, "new completed trading day"),
        )
        self.assertFalse(should_screen(friday, "2026-07-31", "2026-07-31")[0])
        self.assertFalse(should_screen(friday, "2026-07-30", "2026-07-30")[0])
        self.assertFalse(
            should_screen(datetime(2026, 8, 1, 15, 40), "2026-07-31", "")[0]
        )
        self.assertTrue(
            should_screen(datetime(2026, 8, 1, 9, 0), "", "", force=True)[0]
        )

    def test_parse_tencent_index_trade_date(self):
        fields = [""] * 31
        fields[30] = "20260731150000"
        raw = f'v_sh000001="{"~".join(fields)}";'
        self.assertEqual(parse_tencent_trade_date(raw), "2026-07-31")

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
        self.assertNotIn("data-live-time", _position_row(position))
        self.assertNotIn("data-live-return", _position_row(position))
        self.assertIn("data-live-time", _evaluation_row(item, observation=True))
        self.assertIn("quote.server_time", LIVE_SCRIPT)
        self.assertIn('row.querySelector("[data-live-time]")', LIVE_SCRIPT)
        self.assertIn("time.textContent =", LIVE_SCRIPT)
        self.assertIn("formatQuoteTime", LIVE_SCRIPT)
        self.assertIn("paintLivePools", LIVE_SCRIPT)
        self.assertNotIn('row.querySelector("[data-live-return]")', LIVE_SCRIPT)


if __name__ == "__main__":
    unittest.main()
