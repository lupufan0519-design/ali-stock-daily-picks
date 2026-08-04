import sys
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy_tracker import (
    CURRENT_STRATEGY_VERSION,
    empty_state,
    load_state,
    replay_state,
    save_state,
    secondary_strategy_stats,
    strategy_stats,
    update_state,
)
from intraday import build_live_tracking


def row(
    date,
    close=10.0,
    open_price=None,
    high=None,
    low=None,
    name="测试股票",
    selected=False,
    dragon_above=True,
    cross=False,
    bottom=False,
    limit_up=False,
    yellow=False,
    eligible=True,
    dragon=11.0,
    tiger=10.0,
    cross_age=-1,
    cross_lookback_days=8,
    cross_date=None,
    entry_breakout_high=10.4,
    next_breakout_high=10.4,
    one_word_limit_up=False,
    one_word_limit_down=False,
):
    actual_open = close if open_price is None else open_price
    actual_high = max(actual_open, close) + 0.1 if high is None else high
    actual_low = min(actual_open, close) - 0.1 if low is None else low
    return {
        "code": "600001",
        "name": name,
        "market": 1,
        "date": date,
        "open": actual_open,
        "high": actual_high,
        "low": actual_low,
        "close": close,
        "previous_close": close,
        "limit_up_price": close,
        "limit_down_price": close,
        "one_word_limit_up": one_word_limit_up,
        "one_word_limit_down": one_word_limit_down,
        "selected": selected,
        "dragon_above_tiger": dragon_above,
        "dragon_value": dragon,
        "tiger_value": tiger,
        "eligible": eligible,
        "cross_ok": cross,
        "cross_date": (
            cross_date
            if cross_date is not None
            else "2026-07-20"
            if cross
            else ""
        ),
        "bottom_ok": bottom,
        "limit_up_ok": limit_up,
        "yellow_ok": yellow,
        "cross_age": cross_age,
        "cross_lookback_days": cross_lookback_days,
        "entry_breakout_high_5": entry_breakout_high,
        "next_breakout_high_5": next_breakout_high,
    }


class StrategyTrackerTests(unittest.TestCase):
    def start_main(self, *, setup_close=10.0, entry_close=10.5, dragon=11.0):
        # 主选不再产生新持仓；该助手保留一笔迁移前主选持仓，继续覆盖
        # 旧 3%/2% 退出、锁板卖出和历史状态兼容回归。
        state = empty_state()
        state["last_trade_date"] = "2026-07-21"
        state["active"] = [
            {
                "position_id": "600001_2026-07-21",
                "code": "600001",
                "name": "测试股票",
                "market": 1,
                "entry_date": "2026-07-21",
                "entry_price": entry_close,
                "last_date": "2026-07-21",
                "last_close": entry_close,
                "return_pct": 0.0,
                "best_return_pct": 0.0,
                "worst_return_pct": 0.0,
                "holding_days": 1,
                "missing_streak": 0,
                "status": "趋势开始",
                "operation": "开盘已执行买入",
                "strategy_version": "break5_trail3_2_next_open_v2",
                "line_history": [
                    {
                        "date": "2026-07-21",
                        "dragon": dragon,
                        "tiger": 10.0,
                    }
                ],
                "selected_dates": ["2026-07-19", "2026-07-21"],
                "signal_setup_date": "2026-07-19",
                "signal_setup_price": setup_close,
                "setup_cross_date": "2026-07-19",
                "setup_cross_age": 0,
                "setup_cross_lookback_days": 8,
                "setup_elapsed_bars_at_entry": 2,
                "origin_area": "main",
            }
        ]
        return state

    def start_secondary(self, *, setup_close=10.0, entry_close=10.5):
        candidate = row(
            "2026-07-19", close=setup_close, dragon=9.5, tiger=9.0,
            cross=True, cross_date="2026-07-19", limit_up=True, yellow=True,
        )
        state, _ = update_state(empty_state(), [candidate], "2026-07-19")
        d1 = row(
            "2026-07-20", close=entry_close, dragon=9.6, tiger=9.0,
            cross=True, cross_date="2026-07-19", limit_up=True, yellow=True,
        )
        state, events = update_state(state, [d1], "2026-07-20")
        self.assertEqual(events, [])
        d2 = row(
            "2026-07-21", close=entry_close, dragon=9.7, tiger=9.0,
            cross=True, cross_date="2026-07-19", limit_up=True, yellow=True,
        )
        state, events = update_state(state, [d2], "2026-07-21")
        self.assertEqual(events[-1]["type"], "entry_triggered")
        execution = row(
            "2026-07-22", close=entry_close, open_price=entry_close,
            dragon=9.8, tiger=9.0,
            cross=True, cross_date="2026-07-19", limit_up=True, yellow=True,
        )
        state, events = update_state(state, [execution], "2026-07-22")
        self.assertEqual(events[0]["type"], "entry_executed")
        return state

    def secondary_order(
        self,
        *,
        setup_close=10.0,
        d1_dragon=9.6,
        d2_close=10.0,
        d2_dragon=9.7,
        cross_age=0,
        cross_date="2026-07-19",
    ):
        state, _ = update_state(
            empty_state(),
            [
                row(
                    "2026-07-19",
                    close=setup_close,
                    dragon=9.5,
                    tiger=9.0,
                    cross=True,
                    cross_age=cross_age,
                    cross_date=cross_date,
                    limit_up=True,
                    yellow=True,
                )
            ],
            "2026-07-19",
        )
        state, _ = update_state(
            state,
            [
                row(
                    "2026-07-20",
                    close=10.0,
                    dragon=d1_dragon,
                    tiger=9.0,
                    cross=True,
                    cross_date=cross_date,
                    limit_up=True,
                    yellow=True,
                )
            ],
            "2026-07-20",
        )
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-21",
                    close=d2_close,
                    dragon=d2_dragon,
                    tiger=9.0,
                    cross=True,
                    cross_date=cross_date,
                    limit_up=True,
                    yellow=True,
                )
            ],
            "2026-07-21",
        )
        self.assertEqual(events[-1]["type"], "entry_triggered")
        self.assertEqual(len(state["pending_entry_execution"]), 1)
        return state

    def test_dragon_no_longer_above_tiger_ends_immediately(self):
        state = self.start_main()
        state, events = update_state(
            state,
            [row("2026-07-22", close=10.2, dragon_above=False)],
            "2026-07-22",
        )
        self.assertEqual(state["active"], [])
        self.assertEqual(state["closed"], [])
        self.assertEqual(len(state["pending_exit_execution"]), 1)
        self.assertEqual(events[0]["type"], "exit_triggered")
        state, events = update_state(
            state,
            [row("2026-07-23", close=10.1, open_price=10.1)],
            "2026-07-23",
        )
        self.assertEqual(state["closed"][0]["status"], "趋势结束")
        self.assertIn("龙线不再高于虎线", state["closed"][0]["exit_reason"])
        self.assertEqual(events[0]["type"], "removed")

    def test_same_day_rerun_does_not_duplicate_exit(self):
        state = self.start_main()
        state, _ = update_state(state, [row("2026-07-22", dragon_above=False)], "2026-07-22")
        state, _ = update_state(state, [row("2026-07-22", dragon_above=False)], "2026-07-22")
        self.assertEqual(state["active"], [])
        self.assertEqual(len(state["pending_exit_execution"]), 1)
        self.assertEqual(state["closed"], [])
        state, _ = update_state(
            state,
            [row("2026-07-23", open_price=10.0)],
            "2026-07-23",
        )
        self.assertEqual(len(state["closed"]), 1)

    def test_two_post_entry_weakening_days_warn_without_exit(self):
        state = self.start_main(dragon=13.0)
        state, _ = update_state(
            state,
            [row("2026-07-22", close=10.6, dragon=12.0, cross=True)],
            "2026-07-22",
        )
        state, events = update_state(
            state,
            [row("2026-07-23", close=10.6, dragon=11.0, cross=True)],
            "2026-07-23",
        )
        self.assertEqual(len(state["active"]), 1)
        self.assertEqual(state["closed"], [])
        self.assertEqual(state["active"][0]["status"], "待观察中")
        self.assertEqual(events[0]["type"], "trend_warning")

    def test_peak_drawdown_two_percent_after_three_percent_profit_takes_profit(self):
        state = self.start_main()
        state, _ = update_state(
            state,
            [row("2026-07-22", close=11.0, cross=True)],
            "2026-07-22",
        )
        state, events = update_state(
            state,
            [row("2026-07-23", close=10.77, cross=True)],
            "2026-07-23",
        )
        self.assertEqual(state["active"], [])
        self.assertEqual(state["closed"], [])
        self.assertEqual(events[0]["type"], "exit_triggered")
        state, events = update_state(
            state,
            [row("2026-07-24", close=10.7, open_price=10.7, cross=True)],
            "2026-07-24",
        )
        self.assertAlmostEqual(
            state["closed"][0]["exit_return_pct"],
            (10.7 / 10.5 - 1.0) * 100.0,
        )
        self.assertIn("回撤2%", state["closed"][0]["exit_reason"])
        self.assertEqual(state["closed"][0]["status"], "趋势结束")
        self.assertEqual(events[0]["type"], "removed")

    def test_closed_legacy_main_does_not_reenter_and_new_cross_can_be_secondary(self):
        state = self.start_main()
        state, _ = update_state(state, [row("2026-07-22", dragon_above=False)], "2026-07-22")
        state, _ = update_state(state, [row("2026-07-23", open_price=10.0)], "2026-07-23")
        self.assertEqual(len(state["closed"]), 1)

        state, events = update_state(
            state,
            [row("2026-07-24", selected=True, cross=True, cross_date="2026-07-24")],
            "2026-07-24",
        )
        self.assertEqual([event["type"] for event in events], ["main_signal_observed"])
        self.assertEqual(state["pending_main"], [])
        self.assertEqual(state["active"], [])

        state, events = update_state(
            state,
            [row("2026-07-25", cross=True, cross_date="2026-07-24", limit_up=True, yellow=True)],
            "2026-07-25",
        )
        self.assertEqual(events, [])
        self.assertEqual(state["pending_secondary"], [])

        state, events = update_state(
            state,
            [row("2026-07-26", dragon_above=False, dragon=8.9, tiger=9.0)],
            "2026-07-26",
        )
        self.assertEqual(events, [])
        state, events = update_state(
            state,
            [row("2026-07-27", cross=True, cross_date="2026-07-27", limit_up=True, yellow=True)],
            "2026-07-27",
        )
        self.assertEqual(events[-1]["type"], "secondary_setup_added")
        self.assertEqual(len(state["pending_secondary"]), 1)

    def test_main_observation_tombstone_survives_reload(self):
        state, events = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True, cross_age=0, cross_date="2026-07-20")],
            "2026-07-20",
        )
        self.assertEqual(events[-1]["type"], "main_signal_observed")
        self.assertEqual(state["pending_main"], [])
        self.assertEqual(state["consumed_signals"], [{"code": "600001", "cross_date": "2026-07-20"}])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_state(path, state)
            state = load_state(path)

        state, events = update_state(
            state,
            [row("2026-07-21", cross=True, cross_age=1, cross_date="2026-07-20", limit_up=True, yellow=True)],
            "2026-07-21",
        )
        self.assertEqual(events, [])
        self.assertEqual(state["pending_secondary"], [])

        state, events = update_state(
            state,
            [row("2026-07-22", dragon_above=False, dragon=8.9, tiger=9.0)],
            "2026-07-22",
        )
        self.assertEqual(events, [])
        state, events = update_state(
            state,
            [row("2026-07-23", selected=True, cross=True, cross_age=0, cross_date="2026-07-23")],
            "2026-07-23",
        )
        self.assertEqual(events[-1]["type"], "main_signal_observed")
        self.assertEqual(state["pending_main"], [])

    def test_cancelled_secondary_setup_cannot_reuse_the_same_cross_date(self):
        candidate = row(
            "2026-07-20",
            cross=True,
            cross_age=0,
            cross_date="2026-07-20",
            limit_up=True,
            yellow=True,
        )
        state, events = update_state(empty_state(), [candidate], "2026-07-20")
        self.assertEqual(events[-1]["type"], "secondary_setup_added")

        state, events = update_state(
            state,
            [row("2026-07-21", dragon_above=False)],
            "2026-07-21",
        )
        self.assertEqual(state["pending_secondary"], [])
        self.assertEqual(events[-1]["type"], "setup_cancelled")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_state(path, state)
            state = load_state(path)

        state, events = update_state(
            state,
            [
                row(
                    "2026-07-22",
                    cross=True,
                    cross_age=2,
                    cross_date="2026-07-20",
                    limit_up=True,
                    yellow=True,
                )
            ],
            "2026-07-22",
        )
        self.assertEqual(events, [])
        self.assertEqual(state["pending_secondary"], [])

        state, events = update_state(
            state,
            [row("2026-07-23", dragon_above=False, dragon=8.9, tiger=9.0)],
            "2026-07-23",
        )
        self.assertEqual(events, [])
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-24",
                    cross=True,
                    cross_age=0,
                    cross_date="2026-07-24",
                    limit_up=True,
                    yellow=True,
                )
            ],
            "2026-07-24",
        )
        self.assertEqual(events[-1]["type"], "secondary_setup_added")
        self.assertEqual(len(state["pending_secondary"]), 1)

    def test_sixty_following_bars_end_tracking(self):
        state = self.start_main()
        state["active"][0]["holding_days"] = 60
        state["last_trade_date"] = "2026-08-01"
        state, _ = update_state(
            state,
            [row("2026-08-02")],
            "2026-08-02",
        )
        self.assertEqual(state["active"], [])
        self.assertIn(
            "60个后续交易日",
            state["pending_exit_execution"][0]["exit_reason"],
        )
        state, _ = update_state(
            state,
            [row("2026-08-03", open_price=10.0)],
            "2026-08-03",
        )
        self.assertIn("60个后续交易日", state["closed"][0]["exit_reason"])

    def test_sixtieth_following_bar_is_only_a_provisional_intraday_exit(self):
        state = self.start_main()
        position = state["active"][0]
        position["holding_days"] = 60
        position["last_date"] = "2026-08-01"
        position["last_close"] = 10.5
        state["last_trade_date"] = "2026-08-01"
        payload = {
            "trade_date": "2026-08-01",
            "strategy": state,
        }

        same_day = build_live_tracking(
            payload,
            {
                "600001": {
                    "price": 10.6,
                    "server_time": "2026-08-01T14:30:00+08:00",
                }
            },
        )["main"][0]
        self.assertFalse(same_day["provisional_exit"])

        next_day = build_live_tracking(
            payload,
            {
                "600001": {
                    "price": 10.6,
                    "server_time": "2026-08-02T10:00:00+08:00",
                }
            },
        )["main"][0]
        self.assertTrue(next_day["provisional_exit"])
        self.assertFalse(next_day["trend_ended"])
        self.assertEqual(next_day["operation"], "卖出触发 · 等待收盘")
        self.assertEqual(state["active"][0]["holding_days"], 60)
        self.assertEqual(state["active"][0]["last_date"], "2026-08-01")

        settled, _ = update_state(
            state,
            [row("2026-08-02", close=10.6, cross=True)],
            "2026-08-02",
        )
        self.assertEqual(settled["active"], [])
        self.assertIn(
            "60个后续交易日",
            settled["pending_exit_execution"][0]["exit_reason"],
        )
        settled, _ = update_state(
            settled,
            [row("2026-08-03", open_price=10.6)],
            "2026-08-03",
        )
        self.assertIn("60个后续交易日", settled["closed"][0]["exit_reason"])

    def test_d2_trigger_waits_for_next_open_and_same_day_rerun_is_idempotent(self):
        state = self.secondary_order()
        state, events = update_state(
            state,
            [row("2026-07-21", close=10.1, dragon=9.7, tiger=9.0, cross=True, cross_date="2026-07-19", limit_up=True, yellow=True)],
            "2026-07-21",
        )
        self.assertEqual(events, [])
        self.assertEqual(len(state["pending_entry_execution"]), 1)
        self.assertEqual(state["secondary_active"], [])

        state, events = update_state(
            state,
            [row("2026-07-22", open_price=10.8, close=11.0, dragon=9.8, tiger=9.0, cross=True, cross_date="2026-07-19", limit_up=True, yellow=True)],
            "2026-07-22",
        )
        self.assertEqual(events[0]["type"], "entry_executed")
        self.assertEqual(state["secondary_active"][0]["entry_date"], "2026-07-22")
        self.assertEqual(state["secondary_active"][0]["entry_price"], 10.8)
        self.assertEqual(state["secondary_active"][0]["entry_trigger_date"], "2026-07-21")

    def test_one_word_limit_up_defers_entry_then_uses_first_tradable_open(self):
        state = self.secondary_order()
        locked = row(
            "2026-07-22", open_price=11.0, close=11.0, dragon=9.8, tiger=9.0,
            cross=True, cross_date="2026-07-19", limit_up=True, yellow=True,
            one_word_limit_up=True,
        )
        state, events = update_state(state, [locked], "2026-07-22")
        self.assertEqual(events[0]["type"], "entry_execution_blocked")
        self.assertEqual(state["secondary_active"], [])
        self.assertEqual(state["pending_entry_execution"][0]["execution_wait_bars"], 1)
        state, events = update_state(state, [locked], "2026-07-22")
        self.assertEqual(events, [])
        self.assertEqual(state["pending_entry_execution"][0]["execution_wait_bars"], 1)

        state, events = update_state(
            state,
            [row("2026-07-23", open_price=11.2, close=11.4, dragon=9.9, tiger=9.0, cross=True, cross_date="2026-07-19", limit_up=True, yellow=True)],
            "2026-07-23",
        )
        self.assertEqual(events[0]["type"], "entry_executed")
        self.assertEqual(state["secondary_active"][0]["entry_price"], 11.2)

    def test_blocked_entry_is_cancelled_when_the_dragon_tiger_relation_breaks(self):
        state = self.secondary_order()
        state, events = update_state(
            state,
            [row("2026-07-22", open_price=11.0, close=11.0, dragon_above=False, dragon=8.9, tiger=9.0, cross=True, cross_date="2026-07-19", limit_up=True, yellow=True, one_word_limit_up=True)],
            "2026-07-22",
        )
        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual(state["secondary_active"], [])
        self.assertEqual(events[0]["type"], "entry_cancelled")
        self.assertIn("龙线不再高于虎线", events[0]["reason"])

    def test_cross_date_tail_drift_does_not_cancel_blocked_entry(self):
        state = self.secondary_order(cross_date="2026-07-19")
        state, events = update_state(
            state,
            [row("2026-07-22", open_price=11.0, close=11.0, dragon=9.8, tiger=9.0, cross=True, cross_date="2026-07-22", limit_up=True, yellow=True, one_word_limit_up=True)],
            "2026-07-22",
        )
        self.assertEqual(events[0]["type"], "entry_execution_blocked")
        self.assertEqual(len(state["pending_entry_execution"]), 1)
        self.assertEqual(state["pending_entry_execution"][0]["setup_cross_date"], "2026-07-19")

        state, events = update_state(
            state,
            [row("2026-07-23", open_price=11.1, close=11.2, dragon=9.9, tiger=9.0, cross=True, cross_date="2026-07-23", limit_up=True, yellow=True)],
            "2026-07-23",
        )
        self.assertEqual(events[0]["type"], "entry_executed")
        self.assertEqual(len(state["secondary_active"]), 1)
        self.assertEqual(state["secondary_active"][0]["setup_cross_date"], "2026-07-19")
        self.assertEqual(state["consumed_signals"], [{"code": "600001", "cross_date": "2026-07-19"}])

    def test_missing_open_never_falls_back_to_close_for_entry_execution(self):
        state = self.secondary_order()
        missing_open = row("2026-07-22", close=11.0, dragon=9.8, tiger=9.0, cross=True, cross_date="2026-07-19", limit_up=True, yellow=True)
        missing_open.pop("open")
        state, events = update_state(state, [missing_open], "2026-07-22")
        self.assertEqual([event["type"] for event in events], ["entry_execution_blocked"])
        self.assertEqual(state["secondary_active"], [])
        self.assertEqual(len(state["pending_entry_execution"]), 1)
        self.assertEqual(state["pending_entry_execution"][0]["operation"], "暂停执行买入")

        state, events = update_state(
            state,
            [row("2026-07-23", open_price=10.8, close=11.1, dragon=9.9, tiger=9.0, cross=True, cross_date="2026-07-19", limit_up=True, yellow=True)],
            "2026-07-23",
        )
        self.assertEqual(events[0]["type"], "entry_executed")
        self.assertEqual(state["secondary_active"][0]["entry_price"], 10.8)

    def test_missing_open_cancels_when_the_original_signal_recalculates_away(self):
        state = self.secondary_order(cross_age=0)
        missing_open = row("2026-07-22", close=11.0, dragon=9.8, tiger=9.0, cross=False, cross_date="", limit_up=True, yellow=True)
        missing_open.pop("open")
        state, events = update_state(state, [missing_open], "2026-07-22")
        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual([event["type"] for event in events], ["entry_cancelled"])
        self.assertIn("重算消失", events[0]["reason"])

    def test_suspended_entry_is_cancelled_after_five_waiting_sessions(self):
        state = self.secondary_order()
        for day in range(22, 27):
            state, events = update_state(state, [], f"2026-07-{day:02d}")
        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual(state["secondary_active"], [])
        self.assertEqual(events[0]["type"], "entry_cancelled")
        self.assertIn("连续5个交易日", events[0]["reason"])
        self.assertIn("行情缺失", events[0]["reason"])

    def test_one_word_limit_up_entry_cancels_after_five_sessions(self):
        state = self.secondary_order()
        for offset, day in enumerate(range(22, 27)):
            state, events = update_state(
                state,
                [row(f"2026-07-{day:02d}", open_price=11.0, close=11.0, dragon=9.8 + offset * 0.1, tiger=9.0, cross=True, cross_date="2026-07-19", limit_up=True, yellow=True, one_word_limit_up=True)],
                f"2026-07-{day:02d}",
            )
        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual(state["secondary_active"], [])
        self.assertEqual(events[0]["type"], "entry_cancelled")
        self.assertIn("连续5个交易日", events[0]["reason"])

    def test_one_word_limit_down_defers_exit_until_first_tradable_open(self):
        state = self.start_main()
        state, events = update_state(
            state,
            [row("2026-07-22", close=9.5, dragon_above=False)],
            "2026-07-22",
        )
        self.assertEqual(events[0]["type"], "exit_triggered")
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-23",
                    open_price=9.0,
                    close=9.0,
                    dragon_above=False,
                    one_word_limit_down=True,
                )
            ],
            "2026-07-23",
        )
        self.assertEqual(events[0]["type"], "exit_execution_blocked")
        self.assertEqual(state["closed"], [])
        self.assertEqual(len(state["pending_exit_execution"]), 1)
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-23",
                    open_price=9.0,
                    close=9.0,
                    dragon_above=False,
                    one_word_limit_down=True,
                )
            ],
            "2026-07-23",
        )
        self.assertEqual(events, [])
        self.assertEqual(
            state["pending_exit_execution"][0]["execution_wait_bars"],
            1,
        )
        state, events = update_state(
            state,
            [row("2026-07-24", open_price=8.8, close=9.1, dragon_above=False)],
            "2026-07-24",
        )
        self.assertEqual(events[0]["type"], "removed")
        self.assertEqual(state["closed"][0]["exit_trigger_date"], "2026-07-22")
        self.assertEqual(state["closed"][0]["exit_date"], "2026-07-24")
        self.assertEqual(state["closed"][0]["exit_price"], 8.8)

    def test_success_stats_use_completed_secondary_waves_only(self):
        state = self.start_secondary()
        stats = secondary_strategy_stats(state)
        self.assertEqual(stats["sample_count"], 0)
        self.assertEqual(stats["active_count"], 1)
        self.assertIsNone(stats["current_success_rate"])
        self.assertEqual(strategy_stats(state)["active_count"], 0)

        state, _ = update_state(
            state,
            [row("2026-07-23", close=11.0, dragon_above=False, dragon=8.9, tiger=9.0)],
            "2026-07-23",
        )
        stats = secondary_strategy_stats(state)
        self.assertEqual(stats["sample_count"], 0)
        self.assertEqual(stats["pending_exit_execution_count"], 1)

        state, _ = update_state(
            state,
            [row("2026-07-24", close=11.0, open_price=11.0)],
            "2026-07-24",
        )
        stats = secondary_strategy_stats(state)
        self.assertEqual(stats["sample_count"], 1)
        self.assertEqual(stats["current_success_rate"], 100.0)
        self.assertAlmostEqual(stats["all_average_return"], (11.0 / 10.5 - 1) * 100)

    def test_secondary_stats_include_only_versioned_current_closed_trades(self):
        state = empty_state()
        state["secondary_closed"] = [
            {"exit_return_pct": 10.0, "strategy_version": CURRENT_STRATEGY_VERSION},
            {"exit_return_pct": -5.0, "strategy_version": CURRENT_STRATEGY_VERSION},
            {"exit_return_pct": 50.0, "strategy_version": "legacy_strategy"},
            {"exit_return_pct": 80.0},
        ]
        stats = secondary_strategy_stats(state)
        self.assertEqual(stats["closed_success_rate"], 50.0)
        self.assertAlmostEqual(stats["realized_compound_return"], 4.5)
        self.assertEqual(stats["legacy_closed_count"], 2)

    def test_secondary_adds_on_three_conditions_and_ends_when_cross_relationship_disappears(self):
        state = self.start_secondary()
        self.assertEqual(len(state["secondary_active"]), 1)

        lost = row(
            "2026-07-22", close=10.2, dragon_above=False,
            cross=False, limit_up=True, yellow=True,
        )
        state, events = update_state(state, [lost], "2026-07-22")
        self.assertEqual(state["secondary_active"], [])
        self.assertEqual(len(state["pending_exit_execution"]), 1)
        self.assertEqual(events[0]["type"], "exit_triggered")
        state, events = update_state(
            state,
            [row("2026-07-23", close=10.1, open_price=10.1)],
            "2026-07-23",
        )
        self.assertEqual(len(state["secondary_closed"]), 1)
        self.assertEqual(events[0]["type"], "secondary_removed")

    def test_natural_cross_label_expiry_is_not_an_exit_or_warning(self):
        state = self.secondary_order(cross_age=5)
        state, events = update_state(
            state,
            [row("2026-07-22", close=10.1, open_price=10.0, dragon=9.8, tiger=9.0, cross=False, cross_date="")],
            "2026-07-22",
        )
        self.assertEqual([event["type"] for event in events], ["entry_executed"])
        self.assertEqual(len(state["secondary_active"]), 1)
        self.assertEqual(state["pending_exit_execution"], [])

        state, events = update_state(
            state,
            [row("2026-07-23", close=10.2, dragon=9.9, tiger=9.0, cross=False, cross_date="")],
            "2026-07-23",
        )
        self.assertEqual(events, [])
        self.assertEqual(len(state["secondary_active"]), 1)
        self.assertEqual(state["secondary_active"][0]["status"], "上升趋势中")

    def test_short_lived_secondary_signal_is_cancelled_before_buy(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", cross=True, cross_age=0, cross_lookback_days=5, cross_date="2026-07-20", limit_up=True, yellow=True, dragon=9.5, tiger=9.0)],
            "2026-07-20",
        )
        state, events = update_state(
            state,
            [row("2026-07-21", close=9.8, cross=False, cross_date="", dragon_above=True, dragon=9.6, tiger=9.0)],
            "2026-07-21",
        )
        self.assertEqual(state["pending_secondary"], [])
        self.assertEqual(state["secondary_active"], [])
        self.assertEqual(events[0]["type"], "setup_cancelled")
        self.assertIn("重算消失", events[0]["reason"])

    def test_recalculated_signal_erasure_on_entry_day_is_hard_exit(self):
        state = self.secondary_order(cross_age=0)
        state, events = update_state(
            state,
            [row("2026-07-22", close=10.2, open_price=10.0, cross=False, cross_date="", dragon_above=True, dragon=9.8, tiger=9.0)],
            "2026-07-22",
        )
        self.assertEqual(
            [event["type"] for event in events],
            ["entry_executed", "exit_triggered"],
        )
        self.assertEqual(state["secondary_active"], [])
        self.assertEqual(len(state["pending_exit_execution"]), 1)
        self.assertIn("重算消失", state["pending_exit_execution"][0]["exit_reason"])
        self.assertEqual(
            state["pending_exit_execution"][0]["entry_date"],
            "2026-07-22",
        )

    def test_secondary_accepts_bottom_instead_of_limit_up(self):
        candidate = row(
            "2026-07-20", cross=True, bottom=True, limit_up=False, yellow=True
        )
        state, events = update_state(empty_state(), [candidate], "2026-07-20")
        self.assertEqual(len(state["pending_secondary"]), 1)
        self.assertEqual(events[0]["type"], "secondary_setup_added")

        missing_yellow = row(
            "2026-07-20", cross=True, bottom=True, limit_up=True, yellow=False
        )
        state, events = update_state(empty_state(), [missing_yellow], "2026-07-20")
        self.assertEqual(state["secondary_active"], [])
        self.assertEqual(events, [])

    def test_st_cannot_enter_and_existing_position_is_removed(self):
        st_candidate = row(
            "2026-07-20", name="*ST示例", selected=True,
            cross=True, limit_up=True, yellow=True, eligible=False,
        )
        state, events = update_state(empty_state(), [st_candidate], "2026-07-20")
        self.assertEqual(state["active"], [])
        self.assertEqual(state["secondary_active"], [])
        self.assertEqual(events, [])

        state = self.start_main()
        state, events = update_state(
            state,
            [row("2026-07-22", name="ST测试", close=9.8, eligible=False)],
            "2026-07-22",
        )
        self.assertEqual(state["active"], [])
        self.assertEqual(
            state["pending_exit_execution"][0]["exit_reason"],
            "股票名称含 ST，不符合入选范围",
        )
        self.assertEqual(state["pending_exit_execution"][0]["name"], "ST测试")
        self.assertEqual(events[0]["type"], "exit_triggered")
        state, events = update_state(
            state,
            [row("2026-07-23", name="ST测试", close=9.7, open_price=9.7, eligible=False)],
            "2026-07-23",
        )
        self.assertEqual(state["closed"][0]["exit_reason"], "股票名称含 ST，不符合入选范围")
        self.assertEqual(events[0]["type"], "removed")

    def test_primary_selection_is_observed_and_blocks_same_cross_secondary(self):
        strict = row(
            "2026-07-20", selected=True, cross=True, cross_date="2026-07-20",
            limit_up=True, yellow=True,
        )
        state, events = update_state(empty_state(), [strict], "2026-07-20")
        self.assertEqual(events[0]["type"], "main_signal_observed")
        self.assertEqual(state["pending_main"], [])
        self.assertEqual(state["pending_secondary"], [])
        self.assertEqual(state["active"], [])

        secondary = row(
            "2026-07-21", cross=True, cross_date="2026-07-20",
            limit_up=True, yellow=True,
        )
        state, events = update_state(state, [secondary], "2026-07-21")
        self.assertEqual(events, [])
        self.assertEqual(state["pending_secondary"], [])

    def test_secondary_origin_remains_secondary_after_current_area_is_main(self):
        candidate = row(
            "2026-07-20", cross=True, cross_date="2026-07-20",
            limit_up=True, yellow=True, dragon=9.5, tiger=9.0,
        )
        state, _ = update_state(empty_state(), [candidate], "2026-07-20")
        d1_main = row(
            "2026-07-21", close=10.0, selected=True, cross=True,
            cross_date="2026-07-21", limit_up=True, yellow=True,
            dragon=9.6, tiger=9.0,
        )
        state, events = update_state(state, [d1_main], "2026-07-21")
        self.assertEqual(events, [])
        self.assertEqual(len(state["pending_secondary"]), 1)
        self.assertEqual(state["pending_main"], [])

        d2_main = row(
            "2026-07-22", close=10.0, selected=True, cross=True,
            cross_date="2026-07-22", limit_up=True, yellow=True,
            dragon=9.7, tiger=9.0,
        )
        state, events = update_state(state, [d2_main], "2026-07-22")
        self.assertEqual(events[-1]["type"], "entry_triggered")
        self.assertEqual(state["pending_entry_execution"][0]["area"], "secondary")

        execution = row(
            "2026-07-23", close=10.2, open_price=10.1, selected=True,
            cross=True, cross_date="2026-07-23", limit_up=True, yellow=True,
            dragon=9.8, tiger=9.0,
        )
        state, events = update_state(state, [execution], "2026-07-23")
        self.assertEqual(events[0]["type"], "entry_executed")
        self.assertEqual(state["active"], [])
        self.assertEqual(len(state["secondary_active"]), 1)
        self.assertEqual(state["secondary_active"][0]["origin_area"], "secondary")
        self.assertEqual(state["secondary_active"][0]["current_area"], "main")
        self.assertEqual(
            state["consumed_signals"],
            [{"code": "600001", "cross_date": "2026-07-20"}],
        )

    def test_d2_close_dragon_and_pullback_boundaries_are_inclusive(self):
        state = self.secondary_order(
            setup_close=10.0,
            d1_dragon=9.7,
            d2_close=9.7,
            d2_dragon=9.7,
        )
        self.assertEqual(len(state["pending_entry_execution"]), 1)

        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", close=10.0, dragon=9.5, tiger=9.0, cross=True, cross_date="2026-07-20", limit_up=True, yellow=True)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", close=10.0, dragon=9.7, tiger=9.0, cross=True, cross_date="2026-07-20")],
            "2026-07-21",
        )
        state, events = update_state(
            state,
            [row("2026-07-22", close=9.79, dragon=9.8, tiger=9.0, cross=True, cross_date="2026-07-20")],
            "2026-07-22",
        )
        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual(events[-1]["type"], "setup_cancelled")
        self.assertIn("低于龙线", events[-1]["reason"])

    def test_missing_d1_dragon_never_confirms_d2_entry(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", close=10.0, dragon=9.5, tiger=9.0, cross=True, cross_date="2026-07-20", limit_up=True, yellow=True)],
            "2026-07-20",
        )
        d1 = row("2026-07-21", close=10.0, dragon=9.6, tiger=9.0, cross=True, cross_date="2026-07-20")
        d1.pop("dragon_value")
        state, events = update_state(state, [d1], "2026-07-21")
        self.assertEqual(events, [])
        state, events = update_state(
            state,
            [row("2026-07-22", close=10.0, dragon=9.7, tiger=9.0, cross=True, cross_date="2026-07-20")],
            "2026-07-22",
        )
        self.assertEqual(state["pending_secondary"], [])
        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual(events[-1]["type"], "setup_cancelled")
        self.assertIn("数据缺失", events[-1]["reason"])

    def test_only_d2_close_can_confirm_entry(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", close=10.0, dragon=9.5, tiger=9.0, cross=True, cross_date="2026-07-20", limit_up=True, yellow=True)],
            "2026-07-20",
        )
        state, events = update_state(
            state,
            [row("2026-07-21", close=12.0, dragon=9.6, tiger=9.0, cross=True, cross_date="2026-07-20")],
            "2026-07-21",
        )
        self.assertEqual(events, [])
        self.assertEqual(len(state["pending_secondary"]), 1)
        self.assertEqual(state["pending_entry_execution"], [])

        state, events = update_state(
            state,
            [row("2026-07-22", close=10.0, dragon=9.7, tiger=9.0, cross=True, cross_date="2026-07-20")],
            "2026-07-22",
        )
        self.assertEqual(events[-1]["type"], "entry_triggered")
        self.assertEqual(len(state["pending_entry_execution"]), 1)

    def test_trailing_stop_is_inactive_before_three_percent_peak(self):
        state = self.start_main()
        state, _ = update_state(
            state,
            [row("2026-07-22", close=10.8, cross=True)],
            "2026-07-22",
        )
        state, _ = update_state(
            state,
            [row("2026-07-23", close=10.5, cross=True)],
            "2026-07-23",
        )
        self.assertEqual(len(state["active"]), 1)
        state, _ = update_state(
            state,
            [row("2026-07-24", close=11.0, cross=True)],
            "2026-07-24",
        )
        state, _ = update_state(
            state,
            [row("2026-07-25", close=10.78, cross=True)],
            "2026-07-25",
        )
        self.assertEqual(state["active"], [])
        self.assertIn(
            "回撤2%",
            state["pending_exit_execution"][0]["exit_reason"],
        )
        state, _ = update_state(
            state,
            [row("2026-07-26", close=10.7, open_price=10.7, cross=True)],
            "2026-07-26",
        )
        self.assertIn("回撤2%", state["closed"][0]["exit_reason"])

    def test_new_strategy_stats_exclude_legacy_positions(self):
        state = empty_state()
        state["active"] = [
            {"return_pct": 8.0, "strategy_version": "legacy_before_break5_trail3_2"}
        ]
        state["closed"] = [
            {"exit_return_pct": 9.0, "strategy_version": "legacy_before_break5_trail3_2"},
            {"exit_return_pct": 3.0, "strategy_version": state["strategy_version"]},
        ]
        stats = strategy_stats(state)
        self.assertEqual(stats["tracked_active_count"], 1)
        self.assertEqual(stats["active_count"], 0)
        self.assertEqual(stats["legacy_active_count"], 1)
        self.assertEqual(stats["sample_count"], 1)
        self.assertEqual(stats["all_average_return"], 3.0)

    def test_legacy_state_migration_keeps_positions_but_resets_old_pending(self):
        legacy = {
            "version": 1,
            "last_trade_date": "2026-08-03",
            "active": [{"code": "600001", "entry_date": "2026-08-01", "last_date": "2026-08-03"}],
            "closed": [],
            "secondary_active": [],
            "secondary_closed": [],
            "pending_main": [{"code": "600002", "cross_date": "2026-07-30", "status": "待观察中"}],
            "pending_secondary": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            migrated = load_state(path)
        self.assertEqual(len(migrated["active"]), 1)
        self.assertEqual(migrated["pending_main"], [])
        self.assertEqual(migrated["active"][0]["strategy_version"], "legacy_before_break5_trail3_2")
        self.assertEqual(migrated["strategy_migration"]["reset_pending_count"], 1)
        self.assertEqual(migrated["consumed_signals"], [{"code": "600002", "cross_date": "2026-07-30"}])

        same_cross = row("2026-08-04", selected=True, cross=True, cross_date="2026-07-30")
        same_cross["code"] = "600002"
        migrated, events = update_state(migrated, [same_cross], "2026-08-04")
        self.assertEqual(events, [])
        self.assertEqual(migrated["pending_main"], [])

        relationship_lost = row(
            "2026-08-05",
            dragon_above=False,
            dragon=8.9,
            tiger=9.0,
        )
        relationship_lost["code"] = "600002"
        migrated, events = update_state(
            migrated,
            [relationship_lost],
            "2026-08-05",
        )
        self.assertEqual(events, [])

        new_cross = row("2026-08-06", selected=True, cross=True, cross_date="2026-08-06")
        new_cross["code"] = "600002"
        migrated, events = update_state(migrated, [new_cross], "2026-08-06")
        self.assertEqual(events[-1]["type"], "main_signal_observed")
        self.assertEqual(migrated["pending_main"], [])

    def test_replay_state_stops_at_requested_date_and_main_is_observation_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp)
            for trade_date, close, selected in (
                ("2026-07-20", 10.0, True),
                ("2026-07-21", 9.5, False),
            ):
                payload = {
                    "trade_date": trade_date,
                    "results": [row(trade_date, close=close, selected=selected, cross=selected, cross_date=trade_date if selected else "")],
                }
                path = results_dir / f"选股结果_{trade_date}.json"
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            state = replay_state(results_dir, "2026-07-20")
            self.assertEqual(state["last_trade_date"], "2026-07-20")
            self.assertEqual(state["pending_main"], [])
            self.assertEqual(state["active"], [])
            self.assertEqual(state["consumed_signals"], [{"code": "600001", "cross_date": "2026-07-20"}])

    def test_d2_confirmation_rejects_falling_dragon_and_excess_pullback(self):
        cases = (
            ("D+2龙线低于D+1龙线", 10.0, 9.7, 10.0, 9.69),
            ("D+2收盘较信号日收盘回撤超过3%", 10.0, 9.0, 9.69, 9.0),
        )
        for expected_reason, setup_close, d1_dragon, d2_close, d2_dragon in cases:
            with self.subTest(expected_reason=expected_reason):
                state, _ = update_state(
                    empty_state(),
                    [row("2026-08-01", close=setup_close, dragon=8.9, tiger=8.0, cross=True, cross_age=0, cross_date="2026-08-01", limit_up=True, yellow=True)],
                    "2026-08-01",
                )
                state, _ = update_state(
                    state,
                    [row("2026-08-02", close=10.0, dragon=d1_dragon, tiger=8.0, cross=True, cross_date="2026-08-01")],
                    "2026-08-02",
                )
                state, events = update_state(
                    state,
                    [row("2026-08-03", close=d2_close, dragon=d2_dragon, tiger=8.0, cross=True, cross_date="2026-08-01")],
                    "2026-08-03",
                )
                self.assertEqual(state["pending_secondary"], [])
                self.assertEqual(state["pending_entry_execution"], [])
                self.assertEqual(events[-1]["reason"], expected_reason)
                self.assertIn(
                    {"code": "600001", "cross_date": "2026-08-01"},
                    state["consumed_signals"],
                )

    def test_current_trailing_exit_uses_inclusive_ten_ten_boundaries(self):
        state = self.start_secondary(entry_close=10.0)
        state, events = update_state(
            state,
            [row("2026-07-23", close=11.0, dragon=9.9, tiger=9.0, cross=True, cross_date="2026-07-19")],
            "2026-07-23",
        )
        self.assertEqual(events, [])
        state, events = update_state(
            state,
            [row("2026-07-24", close=9.9, dragon=10.0, tiger=9.0, cross=True, cross_date="2026-07-19")],
            "2026-07-24",
        )
        self.assertEqual(events[0]["type"], "exit_triggered")
        self.assertIn("浮盈达到10%后较最高收盘回撤10%", events[0]["reason"])

        state = self.start_secondary(entry_close=10.0)
        state, _ = update_state(
            state,
            [row("2026-07-23", close=10.999, dragon=9.9, tiger=9.0, cross=True, cross_date="2026-07-19")],
            "2026-07-23",
        )
        state, events = update_state(
            state,
            [row("2026-07-24", close=9.8, dragon=10.0, tiger=9.0, cross=True, cross_date="2026-07-19")],
            "2026-07-24",
        )
        self.assertEqual(events, [])
        self.assertEqual(len(state["secondary_active"]), 1)

    def test_weakening_uses_pending_history_and_can_exit_on_entry_day(self):
        state = self.secondary_order()
        self.assertEqual(
            [point["date"] for point in state["pending_entry_execution"][0]["line_history"]],
            ["2026-07-19", "2026-07-20", "2026-07-21"],
        )
        state, events = update_state(
            state,
            [row("2026-07-22", open_price=10.5, close=10.5, dragon=9.6, tiger=9.0, cross=True, cross_date="2026-07-19", one_word_limit_up=True)],
            "2026-07-22",
        )
        self.assertEqual(events[0]["type"], "entry_execution_blocked")
        state, events = update_state(
            state,
            [row("2026-07-23", open_price=10.4, close=10.4, dragon=9.5, tiger=9.0, cross=True, cross_date="2026-07-19")],
            "2026-07-23",
        )
        self.assertEqual(
            [event["type"] for event in events],
            ["entry_executed", "exit_triggered"],
        )
        self.assertIn("连续三点同步递减", events[-1]["reason"])
        self.assertEqual(state["secondary_active"], [])

    def test_current_position_exits_after_sixty_following_days(self):
        state = self.start_secondary()
        position = state["secondary_active"][0]
        position["holding_days"] = 60
        position["last_date"] = "2026-08-01"
        state["last_trade_date"] = "2026-08-01"
        state, events = update_state(
            state,
            [row("2026-08-02", close=10.6, dragon=10.0, tiger=9.0, cross=True, cross_date="2026-07-19")],
            "2026-08-02",
        )
        self.assertEqual(events[0]["type"], "exit_triggered")
        self.assertIn("60个后续交易日", events[0]["reason"])

    def test_pending_sell_is_irreversible_through_signal_restore_and_limit_down(self):
        state = self.secondary_order(cross_age=0)
        state, _ = update_state(
            state,
            [row("2026-07-22", close=10.2, open_price=10.0, dragon=9.8, tiger=9.0, cross=True, cross_date="2026-07-19")],
            "2026-07-22",
        )
        state, events = update_state(
            state,
            [row("2026-07-23", close=10.1, dragon=9.9, tiger=9.0, cross=False, cross_date="")],
            "2026-07-23",
        )
        self.assertEqual(events[0]["type"], "exit_triggered")
        original_reason = state["pending_exit_execution"][0]["exit_reason"]

        state, events = update_state(
            state,
            [row("2026-07-24", close=9.8, open_price=9.8, dragon=10.0, tiger=9.0, cross=True, cross_date="2026-07-19", one_word_limit_down=True)],
            "2026-07-24",
        )
        self.assertEqual(events[0]["type"], "exit_execution_blocked")
        self.assertEqual(state["pending_exit_execution"][0]["exit_reason"], original_reason)

        state, events = update_state(
            state,
            [row("2026-07-25", close=9.9, open_price=9.9, dragon=10.1, tiger=9.0, cross=True, cross_date="2026-07-19")],
            "2026-07-25",
        )
        self.assertEqual(events[0]["type"], "secondary_removed")
        self.assertEqual(state["secondary_closed"][0]["exit_reason"], original_reason)

    def test_intraday_current_erasure_is_hard_exit_and_holding_includes_today(self):
        state = self.secondary_order(cross_age=0)
        state, _ = update_state(
            state,
            [row("2026-07-22", close=10.2, open_price=10.0, dragon=9.8, tiger=9.0, cross=True, cross_date="2026-07-19")],
            "2026-07-22",
        )
        before = deepcopy(state)
        payload = {
            "trade_date": "2026-07-22",
            "strategy": state,
            "live_universe": [{"code": "600001"}],
        }
        live_signal = {
            "cross_ok": False,
            "dragon_above_tiger": True,
            "dragon_value": 9.9,
            "tiger_value": 9.0,
        }
        with patch("intraday.evaluate_live_seed", return_value=live_signal):
            item = build_live_tracking(
                payload,
                {"600001": {"price": 10.1, "server_time": "2026-07-23T10:00:00+08:00"}},
            )["secondary"][0]
        self.assertTrue(item["provisional_exit"])
        self.assertIn("重算消失", item["exit_reason"])
        self.assertEqual(item["holding_days"], 2)
        self.assertEqual(state, before)

    def test_intraday_d2_preview_matches_low_risk_boundaries_and_main_is_observation(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-08-01", close=10.0, dragon=9.6, tiger=9.0, cross=True, cross_age=0, cross_date="2026-08-01", limit_up=True, yellow=True)],
            "2026-08-01",
        )
        state, _ = update_state(
            state,
            [row("2026-08-02", close=10.0, dragon=9.7, tiger=9.0, cross=True, cross_date="2026-08-01")],
            "2026-08-02",
        )
        before = deepcopy(state)
        payload = {
            "trade_date": "2026-08-02",
            "strategy": state,
            "live_universe": [{"code": "600001"}],
        }
        live_signal = {
            "cross_ok": True,
            "dragon_above_tiger": True,
            "dragon_value": 9.7,
            "tiger_value": 9.0,
        }
        quote = {"600001": {"price": 9.7, "server_time": "2026-08-03T10:00:00+08:00"}}
        with patch("intraday.evaluate_live_seed", return_value=live_signal):
            item = build_live_tracking(payload, quote)["secondary"][0]
        self.assertTrue(item["provisional_entry"])
        self.assertEqual(item["operation"], "买点触发 · 等待收盘")
        self.assertEqual(state, before)

        stale_main = deepcopy(state["pending_secondary"][0])
        stale_main["area"] = "main"
        observation_payload = {
            "trade_date": "2026-08-02",
            "strategy": {"pending_main": [stale_main]},
            "live_universe": [{"code": "600001"}],
        }
        with patch("intraday.evaluate_live_seed", return_value=live_signal):
            main_item = build_live_tracking(observation_payload, quote)["main"][0]
        self.assertFalse(main_item["provisional_entry"])
        self.assertEqual(main_item["operation"], "仅观察")

    def test_current_state_header_still_clears_old_pending_and_keeps_tombstones(self):
        state = empty_state()
        state["pending_secondary"] = [
            {
                "code": "600010",
                "setup_cross_date": "2026-07-01",
                "strategy_version": "break5_trail3_2_next_open_v2",
            }
        ]
        state["pending_entry_execution"] = [
            {
                "code": "600011",
                "setup_cross_date": "2026-07-02",
                "strategy_version": "break5_trail3_2_next_open_v2",
                "area": "secondary",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_state(path, state)
            migrated = load_state(path)
        self.assertEqual(migrated["pending_secondary"], [])
        self.assertEqual(migrated["pending_entry_execution"], [])
        self.assertEqual(
            migrated["consumed_signals"],
            [
                {"code": "600010", "cross_date": "2026-07-01"},
                {"code": "600011", "cross_date": "2026-07-02"},
            ],
        )

    def test_cancelled_d2_lineage_blocks_tail_drift_until_relationship_loss(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-08-01", close=10.0, dragon=8.9, tiger=8.0, cross=True, cross_age=0, cross_date="2026-08-01", limit_up=True, yellow=True)],
            "2026-08-01",
        )
        state, _ = update_state(
            state,
            [row("2026-08-02", close=10.0, dragon=9.0, tiger=8.0, cross=True, cross_date="2026-08-02")],
            "2026-08-02",
        )
        state, events = update_state(
            state,
            [row("2026-08-03", close=9.69, dragon=9.0, tiger=8.0, cross=True, cross_date="2026-08-03")],
            "2026-08-03",
        )
        self.assertEqual(events[-1]["type"], "setup_cancelled")
        self.assertEqual(
            state["active_signal_lineages"],
            [{"code": "600001", "original_cross_date": "2026-08-01"}],
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_state(path, state)
            state = load_state(path)
        state, events = update_state(
            state,
            [row("2026-08-04", cross=True, cross_date="2026-08-04", limit_up=True, yellow=True, dragon=9.1, tiger=8.0)],
            "2026-08-04",
        )
        self.assertEqual(events, [])
        self.assertEqual(state["pending_secondary"], [])

        state, events = update_state(
            state,
            [row("2026-08-05", dragon_above=False, dragon=7.9, tiger=8.0)],
            "2026-08-05",
        )
        self.assertEqual(events, [])
        self.assertEqual(state["active_signal_lineages"], [])
        state, events = update_state(
            state,
            [row("2026-08-06", cross=True, cross_date="2026-08-06", limit_up=True, yellow=True, dragon=9.2, tiger=8.0)],
            "2026-08-06",
        )
        self.assertEqual(events[-1]["type"], "secondary_setup_added")
        self.assertEqual(len(state["pending_secondary"]), 1)


if __name__ == "__main__":
    unittest.main()
