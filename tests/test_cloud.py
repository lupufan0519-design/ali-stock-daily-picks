import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from cloud_gate import parse_tencent_trade_date, should_screen
from cloud_daily import (
    bootstrap_payload,
    compact_snapshot,
    should_publish_close,
    snapshot_json,
)
from intraday import (
    build_live_tracking,
    build_live_pools,
    collect_tracking_codes,
    collect_targets,
    evaluate_live_seed,
    market_state,
    normalize_quote_time,
    parse_tencent_quotes,
    unpack_live_seed,
)
from report_ui import (
    LIVE_SCRIPT,
    _evaluation_row,
    _position_row,
    _trend_case_chart,
    render_report,
)
from screener import Bar, cross_yellow_pair, forward_adjust_bars


class CloudWorkflowTests(unittest.TestCase):
    def test_force_refresh_publishes_the_same_trade_date(self):
        self.assertFalse(
            should_publish_close("2026-07-31", "2026-07-31", False)
        )
        self.assertTrue(
            should_publish_close("2026-07-31", "2026-07-31", True)
        )

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
            "body_low_tail": [10.0] * 5,
            "body_low_tail_dates": [
                "2026-07-24",
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
            "yellow_date": "",
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
                    "matched_count": 2,
                    "observation_yellow_ok": True,
                    "observation_yellow_date": "2026-07-24",
                    "observation_yellow_count": 1,
                    "observation_matched_count": 3,
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

    def test_area_tracking_codes_are_unique_and_exclude_st(self):
        payload = {
            "strategy": {
                "active": [
                    {"code": "600001", "name": "主选"},
                    {"code": "600001", "name": "主选"},
                ],
                "secondary_active": [
                    {"code": "603648", "name": "畅联股份"},
                    {"code": "600002", "name": "ST示例"},
                ],
            }
        }
        self.assertEqual(
            collect_tracking_codes(payload),
            {"main": ["600001"], "secondary": ["603648"]},
        )

    def test_live_tracking_updates_return_and_marks_trend_end(self):
        payload = {
            "strategy": {
                "active": [
                    {
                        "code": "600001",
                        "name": "主选",
                        "market": 1,
                        "entry_price": 10.0,
                        "entry_date": "2026-07-20",
                        "last_close": 15.0,
                        "last_date": "2026-07-30",
                        "return_pct": 50.0,
                        "best_return_pct": 50.0,
                        "holding_days": 8,
                    }
                ],
                "secondary_active": [
                    {
                        "code": "603648",
                        "name": "次选",
                        "market": 1,
                        "entry_price": 10.0,
                        "entry_date": "2026-07-20",
                        "last_close": 10.5,
                        "last_date": "2026-07-30",
                        "return_pct": 5.0,
                        "best_return_pct": 5.0,
                        "holding_days": 8,
                    }
                ],
            }
        }
        quotes = {
            "600001": {**self.live_quote("600001"), "price": 12.0},
            "603648": {**self.live_quote("603648"), "price": 10.8},
        }
        tracking = build_live_tracking(payload, quotes)
        main = tracking["main"][0]
        secondary = tracking["secondary"][0]
        self.assertTrue(main["trend_ended"])
        self.assertEqual(main["status"], "趋势结束")
        self.assertAlmostEqual(main["live_return_pct"], 20.0)
        self.assertIn("回撤5%", main["exit_reason"])
        self.assertFalse(secondary["trend_ended"])
        self.assertEqual(secondary["status"], "上升趋势中")
        self.assertAlmostEqual(secondary["live_return_pct"], 8.0)
        self.assertEqual(
            collect_tracking_codes(payload, tracking),
            {"main": [], "secondary": ["603648"]},
        )

    def test_live_pool_does_not_readd_a_position_ending_intraday(self):
        payload = {
            "trade_date": "2026-07-30",
            "config": {
                "bottom_lookback_days": 5,
                "cross_lookback_days": 5,
                "limit_up_lookback_days": 42,
                "yellow_consecutive_days": 1,
                "yellow_before_cross_days": 2,
                "yellow_after_cross_days": 8,
            },
            "live_universe": [self.live_seed("600001")],
        }
        pools = build_live_pools(
            payload,
            {"600001": self.live_quote("600001")},
            {"600001"},
        )
        self.assertEqual(pools["main"], [])
        self.assertEqual(pools["secondary"], [])

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
        self.assertEqual(snapshot["live_seed_format"], 3)
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
        self.assertEqual(seed["observation_matched_count"], 2)

    def test_compact_snapshot_sorts_live_universe_and_result_keys(self):
        first = self.live_seed("600002")
        first["market"] = 1
        second = self.live_seed("000001")
        second["market"] = 0
        payload = {
            "trade_date": "2026-07-30",
            "config": {"near_match_minimum": 3},
            "strategy": {"active": [], "secondary_active": []},
            "results": [
                {
                    **first,
                    "date": "2026-07-30",
                    "close": 10.0,
                    "change_pct": 0.0,
                    "matched_count": 3,
                    "cross_ok": True,
                    "live_seed": first,
                },
                {
                    **second,
                    "date": "2026-07-30",
                    "close": 10.0,
                    "change_pct": 0.0,
                    "matched_count": 3,
                    "cross_ok": True,
                    "live_seed": second,
                },
            ],
        }
        snapshot = compact_snapshot(payload)
        self.assertEqual(
            [item[0] for item in snapshot["live_universe"]],
            ["000001", "600002"],
        )
        self.assertEqual(
            list(snapshot["results"][0]),
            [
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
                "observation_yellow_ok",
                "observation_yellow_date",
                "observation_yellow_count",
                "observation_matched_count",
                "eligible",
                "selected",
                "cross_date",
            ],
        )
        encoded = snapshot_json(snapshot)
        self.assertNotIn("\n", encoded)
        self.assertLess(len(encoded), len(json.dumps(snapshot, indent=2)))

    def test_bootstrap_payload_does_not_change_strategy_state(self):
        strategy = {
            "last_trade_date": "2026-07-30",
            "active": [],
            "closed": [],
            "secondary_active": [],
            "secondary_closed": [],
        }
        original = dict(strategy)
        item = SimpleNamespace(
            code="301516",
            name="中远通",
            market=0,
            date="2026-07-30",
            close=14.43,
            change_pct=-8.44,
            bottom_ok=True,
            bottom_date="2026-07-30",
            cross_ok=True,
            cross_date="2026-07-24",
            limit_up_ok=True,
            limit_up_date="2026-07-07",
            yellow_ok=True,
            yellow_count=1,
            matched_count=4,
            dragon_above_tiger=True,
            eligible=True,
            selected=True,
            chart="<svg></svg>",
            live_seed=self.live_seed("301516"),
        )
        payload = bootstrap_payload(
            [item],
            {"yellow_consecutive_days": 1, "_as_of_date": "2026-07-30"},
            5208,
            [],
            strategy,
        )
        self.assertEqual(strategy, original)
        self.assertIs(payload["strategy"], strategy)
        self.assertTrue(payload["results"][0]["selected"])
        self.assertNotIn("chart", payload["results"][0])

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

    def test_live_cross_pairs_with_yellow_two_days_before(self):
        cfg = {
            "bottom_lookback_days": 5,
            "cross_lookback_days": 5,
            "limit_up_lookback_days": 42,
            "yellow_consecutive_days": 1,
        }
        seed = self.live_seed("600003")
        seed["body_low_tail"] = [10.0, 10.0, 10.0, 8.5, 10.0]
        quote = self.live_quote("600003")
        quote["open"] = 11.2
        quote["price"] = 11.2
        result = evaluate_live_seed(seed, quote, cfg, "2026-07-30")
        self.assertTrue(result["cross_ok"])
        self.assertTrue(result["yellow_ok"])
        self.assertEqual(result["yellow_date"], "2026-07-29")

    def test_observation_yellow_does_not_require_a_cross(self):
        cfg = {
            "bottom_lookback_days": 5,
            "cross_lookback_days": 5,
            "limit_up_lookback_days": 42,
            "yellow_consecutive_days": 1,
        }
        seed = self.live_seed("600009")
        seed["line_coefficients"]["dragon_tail"] = [
            [11.0, 0.0, 0.0] for _ in range(6)
        ]
        seed["line_coefficients"]["tiger_tail"] = [
            [10.0, 0.0, 0.0] for _ in range(6)
        ]
        result = evaluate_live_seed(
            seed,
            self.live_quote("600009"),
            cfg,
            "2026-07-30",
        )
        self.assertFalse(result["cross_ok"])
        self.assertFalse(result["yellow_ok"])
        self.assertEqual(result["matched_count"], 2)
        self.assertTrue(result["observation_yellow_ok"])
        self.assertEqual(result["observation_matched_count"], 3)

    def test_forward_adjustment_matches_the_user_chart(self):
        bars = [
            Bar("2025-08-07", 43.0, 43.42, 41.64, 42.35, 1, 1),
            Bar("2026-07-31", 20.5, 21.52, 20.29, 21.01, 1, 1),
        ]
        event = SimpleNamespace(
            category=1,
            year=2026,
            month=6,
            day=17,
            fenhong=0.2,
            peigu=0.0,
            peigujia=0.0,
            songzhuangu=0.3,
        )
        adjusted = forward_adjust_bars(bars, [event])
        self.assertEqual(
            (
                adjusted[0].open,
                adjusted[0].high,
                adjusted[0].low,
                adjusted[0].close,
            ),
            (32.92, 33.25, 31.88, 32.42),
        )
        self.assertEqual(adjusted[1], bars[1])

    def test_trend_case_contains_a_visible_cross_and_real_yellow_bars(self):
        payload = json.loads(
            (Path(__file__).resolve().parents[1] / "results" / "trend_case.json")
            .read_text(encoding="utf-8")
        )
        bars = payload["bars"]
        dragon = payload["dragon"]
        tiger = payload["tiger"]
        cross_index = next(
            index
            for index, bar in enumerate(bars)
            if bar["date"] == payload["cross_date"]
        )
        self.assertLessEqual(dragon[cross_index - 1], tiger[cross_index - 1])
        self.assertGreater(dragon[cross_index], tiger[cross_index])
        for yellow_date in payload["yellow_dates"]:
            index = next(
                index
                for index, bar in enumerate(bars)
                if bar["date"] == yellow_date
            )
            self.assertGreater(
                dragon[index],
                min(bars[index]["open"], bars[index]["close"]),
            )

    def test_trend_case_overlays_signal_evidence_on_one_full_wave_chart(self):
        html = _trend_case_chart()
        self.assertNotIn("信号形成放大图", html)
        self.assertNotIn('class="trend-case-signal"', html)
        self.assertIn("完整波段 · 龙虎线与黄柱", html)
        self.assertIn("2/5 回看上穿", html)
        self.assertIn("趋势开始", html)
        self.assertEqual(html.count('class="trend-case-canvas"'), 1)
        self.assertEqual(html.count('class="case-arrow-start"'), 1)
        self.assertEqual(html.count('class="case-arrow-end"'), 1)
        self.assertEqual(html.count('class="case-exit-target"'), 1)
        self.assertEqual(html.count('class="case-cross-guide"'), 1)
        self.assertEqual(html.count('class="case-dragon-line"'), 1)
        self.assertEqual(html.count('class="case-tiger-line"'), 1)
        self.assertEqual(html.count('class="case-line-label dragon"'), 1)
        self.assertEqual(html.count('class="case-line-label tiger"'), 1)
        self.assertEqual(html.count('class="case-yellow-body qualified"'), 2)
        self.assertEqual(html.count('class="case-yellow-body contextual"'), 6)

    def test_yellow_window_can_extend_after_the_cross_without_looking_before(self):
        cross = [False, True, False, False, False, False, False]
        yellow = [True, False, False, False, False, False, True]
        self.assertEqual(
            cross_yellow_pair(
                cross,
                yellow,
                end_index=6,
                cross_lookback_days=6,
                yellow_consecutive_days=1,
                before_days=0,
                after_days=5,
            )[:2],
            (1, 6),
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
            "status": "上升趋势中",
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
        self.assertIn("data-tracking-code", _position_row(position))
        self.assertIn("data-live-time", _position_row(position))
        self.assertIn("data-live-return", _position_row(position))
        self.assertIn("上升趋势中", _position_row(position))
        self.assertIn("data-live-time", _evaluation_row(item, observation=True))
        self.assertIn("quote.server_time", LIVE_SCRIPT)
        self.assertIn('row.querySelector("[data-live-time]")', LIVE_SCRIPT)
        self.assertIn("time.textContent =", LIVE_SCRIPT)
        self.assertIn("formatQuoteTime", LIVE_SCRIPT)
        self.assertIn("paintLivePools", LIVE_SCRIPT)
        self.assertIn("paintLiveTracking", LIVE_SCRIPT)
        self.assertIn("data-area-secondary-count", LIVE_SCRIPT)
        self.assertIn("tracking_codes", LIVE_SCRIPT)
        self.assertIn('row.querySelector("[data-live-return]")', LIVE_SCRIPT)

    def test_report_separates_live_and_settled_dates_and_defers_video(self):
        item = SimpleNamespace(
            code="301516",
            name="中远通",
            market=0,
            date="2026-07-30",
            close=14.43,
            change_pct=-8.44,
            chart='<svg aria-label="最近42日K线、龙线和虎线"></svg>',
            cross_ok=True,
            cross_date="2026-07-28",
            bottom_ok=True,
            bottom_date="2026-07-30",
            yellow_ok=True,
            yellow_count=1,
            limit_up_ok=True,
            limit_up_date="2026-07-07",
            matched_count=4,
            eligible=True,
            selected=True,
        )
        observations = [
            SimpleNamespace(
                code=f"60010{index}",
                name=f"观察示例{index}",
                market=1,
                date="2026-07-30",
                close=10.0 + index,
                change_pct=float(index),
                chart='<svg aria-label="最近42日K线、龙线和虎线"></svg>',
                cross_ok=True,
                cross_date="2026-07-28",
                bottom_ok=True,
                bottom_date="2026-07-30",
                yellow_ok=False,
                yellow_count=0,
                limit_up_ok=False,
                limit_up_date="",
                matched_count=2,
                observation_yellow_ok=True,
                observation_yellow_date="2026-07-30",
                observation_yellow_count=1,
                observation_matched_count=3,
                eligible=True,
                selected=False,
            )
            for index in range(8)
        ]
        observations[1].yellow_ok = True
        observations[1].yellow_count = 1
        tracked = {
            "code": "600100",
            "name": "主选跟踪",
            "market": 1,
            "entry_price": 10.0,
            "entry_date": "2026-07-20",
            "last_close": 10.5,
            "last_date": "2026-07-30",
            "return_pct": 5.0,
            "holding_days": 8,
            "missing_streak": 0,
            "status": "上升趋势中",
        }
        html = render_report(
            [item, *observations],
            {
                "near_match_minimum": 3,
                "bottom_lookback_days": 5,
                "cross_lookback_days": 5,
                "limit_up_lookback_days": 42,
                "yellow_consecutive_days": 1,
            },
            5209,
            [],
            {
                "active": [tracked],
                "closed": [],
                "secondary_active": [],
                "secondary_closed": [],
            },
            [],
        )
        self.assertIn("data-live-trade-date", html)
        self.assertIn("data-close-trade-date", html)
        self.assertIn('preload="none"', html)
        self.assertIn('class="pool-table"', html)
        self.assertIn("中远通 最近42日K线", html)
        self.assertIn("真实案例 · 海南华铁", html)
        self.assertIn("信号确认", html)
        self.assertIn("建议结束", html)
        self.assertIn('class="case-dragon-line"', html)
        self.assertIn('class="case-tiger-line"', html)
        self.assertIn('class="case-yellow-body qualified"', html)
        self.assertIn("通达信前复权日线", html)
        self.assertIn("2025-02-11 / 2025-02-13 · 8.92元", html)
        self.assertIn("默认展示优先级最高的 5 只", html)
        self.assertIn("展开更多：其余 1 只观察标的", html)
        self.assertNotIn("观察示例0", html)
        self.assertEqual(html.count("观察示例1"), 1)
        self.assertIn("首次入选信号在自然显示期限内", html)
        self.assertIn("10 个交易日内收盘较信号日上涨 5%", html)
        self.assertNotIn("首次达到5%中位数", html)
        self.assertNotIn("hero-aigc-v2-poster.webp;base64", html)


if __name__ == "__main__":
    unittest.main()
