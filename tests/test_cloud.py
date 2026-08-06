import json
import unittest
from unittest.mock import patch
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
from simple_strategy import THIRD_TIER
from strategy_contract import ENTRY_LABEL, FROZEN_CANDIDATE_ID, LIVE_STRATEGY_ID


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
            "entry_breakout_high_5": 10.3,
            "next_breakout_high_5": 10.4,
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

    def test_live_universe_keeps_pending_entry_target_and_previews_st_cancellation(self):
        order = {
            "execution_id": "entry_600004_2026-07-30",
            "code": "600004",
            "name": "原普通股票",
            "market": 1,
            "area": "main",
            "entry_trigger_date": "2026-07-30",
            "entry_trigger_close": 10.5,
        }
        payload = {
            "trade_date": "2026-07-30",
            "live_universe": [self.live_seed("600001")],
            "strategy": {"pending_entry_execution": [order]},
            "results": [],
        }

        self.assertEqual(
            [item["code"] for item in collect_targets(payload)],
            ["600001", "600004"],
        )
        quote = {
            **self.live_quote("600004"),
            "name": "ST新名称",
        }
        tracking = build_live_tracking(payload, {"600004": quote})["main"][0]
        self.assertTrue(tracking["provisional_cancel"])
        self.assertFalse(tracking["provisional_entry_execution"])
        self.assertEqual(tracking["status"], "待观察中")
        self.assertEqual(tracking["operation"], "取消买入待收盘")

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

    def test_live_tracking_marks_sell_trigger_as_provisional_until_close(self):
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
        self.assertFalse(main["trend_ended"])
        self.assertTrue(main["provisional_exit"])
        self.assertEqual(main["status"], "待观察中")
        self.assertEqual(main["operation"], "卖出触发 · 等待收盘")
        self.assertAlmostEqual(main["live_return_pct"], 20.0)
        self.assertIn("回撤2%", main["exit_reason"])
        self.assertFalse(secondary["trend_ended"])
        self.assertEqual(secondary["status"], "上升趋势中")
        self.assertAlmostEqual(secondary["live_return_pct"], 8.0)
        self.assertEqual(
            collect_tracking_codes(payload, tracking),
            {"main": ["600001"], "secondary": ["603648"]},
        )

    def test_live_name_change_to_st_previews_exit_and_blocks_pool_entry(self):
        payload = {
            "trade_date": "2026-07-30",
            "config": {
                "bottom_lookback_days": 5,
                "cross_lookback_days": 8,
                "limit_up_lookback_days": 42,
                "yellow_consecutive_days": 1,
                "yellow_before_cross_days": 2,
                "yellow_after_cross_days": 7,
            },
            "live_universe": [self.live_seed("600001")],
            "strategy": {
                "active": [
                    {
                        "code": "600001",
                        "name": "原普通股票",
                        "market": 1,
                        "entry_price": 10.0,
                        "entry_date": "2026-07-20",
                        "last_close": 10.2,
                        "last_date": "2026-07-30",
                        "return_pct": 2.0,
                        "best_return_pct": 2.0,
                        "holding_days": 8,
                    }
                ],
                "secondary_active": [],
            },
        }
        quote = {**self.live_quote("600001"), "name": "ST新名称"}

        tracking = build_live_tracking(payload, {"600001": quote})["main"][0]
        pools = build_live_pools(payload, {"600001": quote}, set())

        self.assertEqual(tracking["name"], "ST新名称")
        self.assertTrue(tracking["provisional_exit"])
        self.assertIn("ST", tracking["exit_reason"])
        self.assertEqual(tracking["operation"], "卖出触发 · 等待收盘")
        self.assertEqual(pools["main"], [])
        self.assertEqual(pools["secondary"], [])

    def test_live_tracking_previews_the_sixtieth_following_day_exit(self):
        payload = {
            "strategy": {
                "active": [
                    {
                        "code": "600001",
                        "name": "主选",
                        "market": 1,
                        "entry_price": 10.0,
                        "entry_date": "2026-05-01",
                        "last_close": 10.5,
                        "last_date": "2026-07-30",
                        "return_pct": 5.0,
                        "best_return_pct": 5.0,
                        "holding_days": 60,
                    }
                ],
                "secondary_active": [],
            }
        }
        tracking = build_live_tracking(
            payload,
            {"600001": self.live_quote("600001")},
        )["main"][0]
        self.assertFalse(tracking["trend_ended"])
        self.assertTrue(tracking["provisional_exit"])
        self.assertEqual(tracking["operation"], "卖出触发 · 等待收盘")
        self.assertIn("60个后续交易日", tracking["exit_reason"])

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
        self.assertEqual(snapshot["live_seed_format"], 6)
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
        self.assertEqual(seed["next_breakout_high_5"], 10.4)
        legacy_seed = unpack_live_seed(
            snapshot["live_universe"][0][:-1],
            3,
        )
        self.assertEqual(legacy_seed["next_breakout_high_5"], 0.0)

    def test_pending_secondary_d2_is_only_a_close_confirmation_preview(self):
        seed = self.live_seed("600020")
        seed["base_date"] = "2026-07-31"
        seed["line_coefficients"].update(
            {
                "dragon": [9.7, 0.0, 0.0],
                "tiger": [9.0, 0.0, 0.0],
                "previous_dragon": [8.8, 0.0, 0.0],
                "previous_tiger": [9.0, 0.0, 0.0],
                "dragon_tail": [
                    [value, 0.0, 0.0]
                    for value in [8.8, 8.8, 8.8, 8.8, 8.8, 9.7]
                ],
                "tiger_tail": [[9.0, 0.0, 0.0] for _ in range(6)],
            }
        )
        payload = {
            "trade_date": "2026-07-31",
            "config": {
                "bottom_lookback_days": 5,
                "cross_lookback_days": 8,
                "limit_up_lookback_days": 42,
                "yellow_consecutive_days": 1,
                "yellow_before_cross_days": 2,
                "yellow_after_cross_days": 7,
            },
            "live_universe": [seed],
            "strategy": {
                "pending_secondary": [
                    {
                        "setup_id": "secondary_600020_2026-07-30",
                        "code": "600020",
                        "name": "待确认",
                        "market": 1,
                        "area": "secondary",
                        "origin_area": "secondary",
                        "setup_date": "2026-07-30",
                        "setup_price": 10.0,
                        "last_date": "2026-07-31",
                        "last_close": 10.0,
                        "setup_elapsed_bars": 1,
                        "setup_cross_age": 0,
                        "setup_cross_lookback_days": 8,
                        "confirmation_d1_dragon": 9.7,
                        "strategy_version": LIVE_STRATEGY_ID,
                    }
                ]
            },
        }
        settled_strategy = json.loads(json.dumps(payload["strategy"]))
        quote = {
            **self.live_quote("600020"),
            "price": 9.7,
            "server_time": "2026-08-03T10:30:00+08:00",
        }
        tracking = build_live_tracking(payload, {"600020": quote})["secondary"][0]
        self.assertFalse(tracking["trend_ended"])
        self.assertTrue(tracking["provisional_entry"])
        self.assertEqual(tracking["status"], "待观察中")
        self.assertEqual(tracking["operation"], "买点触发 · 等待收盘")
        self.assertEqual(tracking["holding_days"], 2)
        self.assertIn("盘中满足D+2低风险确认条件", tracking["status_detail"])
        self.assertIn("下一可交易日开盘执行买入", tracking["status_detail"])
        self.assertEqual(payload["strategy"], settled_strategy)

        quote["price"] = 9.69
        tracking = build_live_tracking(payload, {"600020": quote})["secondary"][0]
        self.assertFalse(tracking["provisional_entry"])
        self.assertEqual(tracking["operation"], "等待D+2收盘确认")
        self.assertEqual(payload["strategy"], settled_strategy)

    def test_pending_entry_execution_is_only_previewed_intraday(self):
        order = {
            "execution_id": "entry_600020_2026-07-30",
            "code": "600020",
            "name": "待执行买入",
            "market": 1,
            "area": "main",
            "setup_date": "2026-07-28",
            "setup_price": 10.0,
            "entry_trigger_date": "2026-07-30",
            "entry_trigger_close": 10.6,
        }
        payload = {
            "trade_date": "2026-07-30",
            "strategy": {"pending_entry_execution": [order]},
        }
        before = json.loads(json.dumps(payload, ensure_ascii=False))

        tracking = build_live_tracking(
            payload,
            {"600020": self.live_quote("600020")},
        )["main"][0]

        self.assertEqual(payload, before)
        self.assertTrue(tracking["pending_entry_execution"])
        self.assertTrue(tracking["provisional_entry_execution"])
        self.assertFalse(tracking["execution_blocked"])
        self.assertEqual(tracking["status"], "买点已确认")
        self.assertEqual(tracking["operation"], "开盘买入待结算")
        self.assertEqual(tracking["entry_price"], 10.0)

    def test_pending_entry_execution_does_not_assume_a_fill_at_one_word_limit_up(self):
        payload = {
            "trade_date": "2026-07-30",
            "strategy": {
                "pending_entry_execution": [
                    {
                        "execution_id": "entry_600020_2026-07-30",
                        "code": "600020",
                        "name": "待执行买入",
                        "market": 1,
                        "area": "main",
                        "setup_date": "2026-07-28",
                        "setup_price": 10.0,
                        "entry_trigger_date": "2026-07-30",
                        "entry_trigger_close": 10.6,
                    }
                ]
            },
        }
        quote = {
            **self.live_quote("600020"),
            "price": 11.0,
            "open": 11.0,
            "high": 11.0,
            "low": 11.0,
        }

        tracking = build_live_tracking(payload, {"600020": quote})["main"][0]

        self.assertFalse(tracking["provisional_entry_execution"])
        self.assertTrue(tracking["execution_blocked"])
        self.assertEqual(tracking["entry_price"], 0.0)
        self.assertEqual(tracking["operation"], "等待可成交开盘")

    def test_pending_entry_preview_cancels_on_the_fifth_blocked_open(self):
        payload = {
            "trade_date": "2026-07-30",
            "strategy": {
                "pending_entry_execution": [
                    {
                        "execution_id": "entry_600020_2026-07-25",
                        "code": "600020",
                        "name": "待执行买入",
                        "market": 1,
                        "area": "secondary",
                        "setup_date": "2026-07-23",
                        "setup_price": 10.0,
                        "entry_trigger_date": "2026-07-25",
                        "entry_trigger_close": 10.6,
                        "execution_wait_bars": 4,
                        "last_execution_attempt_date": "2026-07-30",
                    }
                ]
            },
        }
        quote = {
            **self.live_quote("600020"),
            "price": 11.0,
            "open": 11.0,
            "high": 11.0,
            "low": 11.0,
        }

        tracking = build_live_tracking(payload, {"600020": quote})["secondary"][0]

        self.assertFalse(tracking["provisional_entry_execution"])
        self.assertTrue(tracking["provisional_cancel"])
        self.assertEqual(tracking["operation"], "取消买入待收盘")
        self.assertIn("连续5个交易日一字涨停无法买入", tracking["status_detail"])

    def test_pending_entry_preview_uses_market_date_when_quote_is_missing(self):
        payload = {
            "trade_date": "2026-07-30",
            "strategy": {
                "pending_entry_execution": [
                    {
                        "execution_id": "entry_600020_2026-07-25",
                        "code": "600020",
                        "name": "停牌待执行",
                        "market": 1,
                        "area": "secondary",
                        "setup_date": "2026-07-23",
                        "setup_price": 10.0,
                        "entry_trigger_date": "2026-07-25",
                        "entry_trigger_close": 10.6,
                        "execution_wait_bars": 4,
                        "last_execution_attempt_date": "2026-07-30",
                    }
                ]
            },
        }

        tracking = build_live_tracking(
            payload,
            {},
            live_trade_date="2026-07-31",
        )["secondary"][0]

        self.assertTrue(tracking["provisional_cancel"])
        self.assertEqual(tracking["operation"], "取消买入待收盘")
        self.assertIn("连续5个交易日停牌或开盘价缺失", tracking["status_detail"])

    def test_pending_exit_execution_previews_open_without_settling(self):
        order = {
            "execution_id": "exit_600001_2026-07-30",
            "position_id": "600001_2026-07-20",
            "code": "600001",
            "name": "待执行卖出",
            "market": 1,
            "area": "main",
            "entry_date": "2026-07-20",
            "entry_price": 8.0,
            "holding_days": 8,
            "last_date": "2026-07-30",
            "last_close": 10.0,
            "return_pct": 25.0,
            "exit_trigger_date": "2026-07-30",
            "exit_trigger_close": 10.0,
            "exit_reason": "趋势结束：高点回撤2%",
        }
        payload = {
            "trade_date": "2026-07-30",
            "strategy": {"pending_exit_execution": [order]},
        }
        before = json.loads(json.dumps(payload, ensure_ascii=False))

        tracking = build_live_tracking(
            payload,
            {"600001": self.live_quote("600001")},
        )["main"][0]

        self.assertEqual(payload, before)
        self.assertFalse(tracking["trend_ended"])
        self.assertTrue(tracking["pending_exit_execution"])
        self.assertTrue(tracking["provisional_exit_execution"])
        self.assertFalse(tracking["execution_blocked"])
        self.assertEqual(tracking["status"], "卖点已确认")
        self.assertEqual(tracking["operation"], "开盘卖出待结算")
        self.assertEqual(tracking["preview_exit_price"], 10.0)
        self.assertAlmostEqual(tracking["preview_exit_return_pct"], 25.0)

    def test_pending_exit_execution_waits_through_one_word_limit_down(self):
        payload = {
            "trade_date": "2026-07-30",
            "strategy": {
                "pending_exit_execution": [
                    {
                        "execution_id": "exit_600001_2026-07-30",
                        "position_id": "600001_2026-07-20",
                        "code": "600001",
                        "name": "原普通股票",
                        "market": 1,
                        "area": "main",
                        "entry_date": "2026-07-20",
                        "entry_price": 10.0,
                        "holding_days": 8,
                        "last_date": "2026-07-30",
                        "last_close": 10.0,
                        "return_pct": 0.0,
                        "exit_trigger_date": "2026-07-30",
                        "exit_trigger_close": 10.0,
                        "exit_reason": "股票名称含 ST",
                    }
                ]
            },
        }
        quote = {
            **self.live_quote("600001"),
            "name": "ST待执行卖出",
            "price": 9.5,
            "open": 9.5,
            "high": 9.5,
            "low": 9.5,
        }

        targets = collect_targets(payload)
        tracking = build_live_tracking(payload, {"600001": quote})["main"][0]

        self.assertEqual([target["code"] for target in targets], ["600001"])
        self.assertFalse(tracking["provisional_exit_execution"])
        self.assertTrue(tracking["execution_blocked"])
        self.assertIsNone(tracking["preview_exit_price"])
        self.assertEqual(tracking["operation"], "等待可成交开盘")

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
                "dragon_value",
                "tiger_value",
                "yellow_line_value",
                "tier",
                "line_gap_abs",
                "prior_three_gap_abs",
                "prior_three_gap_max",
                "company_intro",
                "industry",
                "concepts",
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

    def test_intraday_bottom_waits_for_zig_rebound_confirmation(self):
        cfg = {
            "bottom_lookback_days": 2,
            "cross_lookback_days": 5,
            "limit_up_lookback_days": 42,
            "yellow_consecutive_days": 1,
        }
        seed = self.live_seed("600010", bottom_age=-1, limit_age=-1)
        seed.update(
            {
                "zig16_state": 2,
                "zig16_candidate_value": 8.0,
                "zig16_candidate_age": 0,
                "zig16_candidate_date": "2026-07-30",
                "zig16_candidate_signal_ok": True,
            }
        )
        unconfirmed_quote = self.live_quote("600010")
        unconfirmed_quote["price"] = 7.8
        unconfirmed = evaluate_live_seed(
            seed,
            unconfirmed_quote,
            cfg,
            "2026-07-30",
        )
        self.assertFalse(unconfirmed["bottom_ok"])

        confirmed_quote = self.live_quote("600010")
        confirmed_quote["price"] = 9.3
        confirmed = evaluate_live_seed(
            seed,
            confirmed_quote,
            cfg,
            "2026-07-30",
        )
        self.assertTrue(confirmed["bottom_ok"])
        self.assertEqual(confirmed["bottom_date"], "2026-07-30")

    def test_intraday_recent_bottom_falls_back_to_third_tier(self):
        cfg = {
            "bottom_lookback_days": 2,
            "cross_lookback_days": 8,
            "limit_up_lookback_days": 42,
            "yellow_consecutive_days": 1,
            "yellow_before_cross_days": 2,
            "yellow_after_cross_days": 7,
            "line_gap_max_abs": 0.5,
        }
        seed = self.live_seed("600011", bottom_age=0, limit_age=-1)
        pools = build_live_pools(
            {
                "trade_date": "2026-07-30",
                "config": cfg,
                "live_universe": [seed],
            },
            {"600011": self.live_quote("600011")},
        )
        self.assertEqual([row["code"] for row in pools[THIRD_TIER]], ["600011"])
        self.assertEqual(pools["main"], [])
        self.assertEqual(pools["secondary"], [])

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
        case = next(
            item
            for item in payload["cancelled_cases"]
            if item.get("code") == "603300"
        )
        bars = case["bars"]
        dragon = case["wave_dragon"]
        tiger = case["wave_tiger"]
        cross_index = next(
            index
            for index, bar in enumerate(bars)
            if bar["date"] == case["cross_date"]
        )
        self.assertLessEqual(dragon[cross_index - 1], tiger[cross_index - 1])
        self.assertGreater(dragon[cross_index], tiger[cross_index])
        self.assertEqual(case["qualified_yellow_dates"], ["2025-01-24", "2025-01-27"])
        for yellow_date in case["yellow_dates"]:
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
        payload = json.loads(
            (Path(__file__).resolve().parents[1] / "results" / "trend_case.json")
            .read_text(encoding="utf-8")
        )
        primary_case = payload["primary_case"]
        bars = primary_case["bars"]

        def x_at(trade_date):
            index = next(
                index
                for index, bar in enumerate(bars)
                if bar["date"] == trade_date
            )
            return 45.0 + (900.0 - 45.0 - 48.0) * index / max(1, len(bars) - 1)

        entry_x = x_at(primary_case["entry_date"])
        exit_x = x_at(primary_case["exit_date"])
        html = _trend_case_chart()
        self.assertNotIn("信号形成放大图", html)
        self.assertNotIn('class="trend-case-signal"', html)
        self.assertIn("完整波段 · 龙虎线与有效黄柱", html)
        self.assertEqual(payload["frozen_live_strategy_id"], LIVE_STRATEGY_ID)
        self.assertEqual(payload["frozen_candidate_id"], FROZEN_CANDIDATE_ID)
        self.assertEqual(primary_case["candidate_id"], FROZEN_CANDIDATE_ID)
        self.assertNotEqual(
            primary_case["entry_trigger_date"],
            primary_case["entry_date"],
        )
        self.assertNotEqual(
            primary_case["exit_trigger_date"],
            primary_case["exit_date"],
        )
        self.assertIn(
            f"真实案例 · {primary_case['name']} {primary_case['code']}",
            html,
        )
        self.assertIn(
            f"{primary_case['signal_date']} / {primary_case['entry_trigger_date']} / "
            f"{primary_case['entry_date']}",
            html,
        )
        self.assertIn(
            f"{primary_case['exit_trigger_date']} / {primary_case['exit_date']}",
            html,
        )
        self.assertIn(
            '<div class="case-pin start" data-case-pin="start"><b>买入执行</b>'
            f"<small>{primary_case['entry_date']}</small>",
            html,
        )
        self.assertIn(
            '<div class="case-pin end" data-case-pin="end"><b>卖出执行</b>'
            f"<small>{primary_case['exit_date']}</small>",
            html,
        )
        self.assertIn(
            'class="case-arrow-start" data-case-leader="start" '
            f'data-target-x="{entry_x:.1f}"',
            html,
        )
        self.assertIn(
            'class="case-arrow-end" data-case-leader="end" '
            f'data-target-x="{exit_x:.1f}"',
            html,
        )
        self.assertIn("02-05 回看上穿", html)
        self.assertIn("02-11 首次可见", html)
        self.assertIn("查看候选取消反例", html)
        self.assertIn("买入执行", html)
        self.assertEqual(html.count('class="trend-case-canvas"'), 2)
        self.assertEqual(html.count('class="case-pin-rail'), 2)
        self.assertEqual(html.count('data-case-pin="'), 5)
        self.assertEqual(html.count('data-case-leader="'), 5)
        self.assertEqual(html.count('class="case-arrow-start"'), 2)
        self.assertEqual(html.count('class="case-arrow-peak"'), 1)
        self.assertEqual(html.count('class="case-arrow-end"'), 2)
        self.assertEqual(html.count('class="case-start-target"'), 2)
        self.assertEqual(html.count('class="case-exit-target"'), 1)
        self.assertEqual(html.count('class="case-cancel-target"'), 1)
        self.assertEqual(html.count('class="case-cross-guide"'), 2)
        self.assertEqual(html.count('class="case-dragon-line"'), 2)
        self.assertEqual(html.count('class="case-tiger-line"'), 2)
        self.assertEqual(html.count('class="case-line-label dragon"'), 2)
        self.assertEqual(html.count('class="case-line-label tiger"'), 2)
        self.assertEqual(html.count('class="case-yellow-body qualified"'), 3)
        self.assertIn("信号形成 / 买点触发 / 买入执行", html)
        self.assertIn("syncTrendCaseLeaders", LIVE_SCRIPT)
        self.assertIn("ResizeObserver", LIVE_SCRIPT)

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

    @patch("report_ui._read_result_json", return_value={})
    def test_report_separates_live_and_settled_dates_and_defers_video(self, _read_result):
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
        self.assertIn("联合验证数据待生成", html)
        self.assertNotIn("真实案例 · 海南华铁", html)
        self.assertIn("默认展示优先级最高的 5 只", html)
        self.assertIn("展开更多：其余 1 只观察标的", html)
        self.assertNotIn("观察示例0", html)
        self.assertEqual(html.count("观察示例1"), 1)
        self.assertIn("data-live-operation", html)
        self.assertIn(ENTRY_LABEL, html)
        self.assertIn("买点收盘确认后等待下一可交易日开盘执行", html)
        self.assertNotIn("基础双信号研究 · 非主次选绩效", html)
        self.assertNotIn("首次达到5%中位数", html)
        self.assertNotIn("hero-aigc-v2-poster.webp;base64", html)


if __name__ == "__main__":
    unittest.main()
