import sys
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy_tracker import (
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
        state, _ = update_state(
            empty_state(),
            [row("2026-07-19", selected=True, cross=True, cross_date="2026-07-19", close=setup_close, dragon=dragon)],
            "2026-07-19",
        )
        state, events = update_state(
            state,
            [row("2026-07-20", selected=True, cross=True, cross_date="2026-07-19", close=entry_close, dragon=dragon)],
            "2026-07-20",
        )
        self.assertEqual(events[-1]["type"], "entry_triggered")
        self.assertEqual(state["active"], [])
        self.assertEqual(len(state["pending_entry_execution"]), 1)
        state, events = update_state(
            state,
            [row("2026-07-21", selected=True, cross=True, cross_date="2026-07-19", close=entry_close, open_price=entry_close, dragon=dragon)],
            "2026-07-21",
        )
        self.assertEqual(events[0]["type"], "entry_executed")
        self.assertEqual(state["active"][0]["status"], "趋势开始")
        return state

    def start_secondary(self, *, setup_close=10.0, entry_close=10.5):
        candidate = row(
            "2026-07-19", close=setup_close,
            cross=True, cross_date="2026-07-19", limit_up=True, yellow=True,
        )
        state, _ = update_state(empty_state(), [candidate], "2026-07-19")
        confirmation = row(
            "2026-07-20", close=entry_close,
            cross=True, cross_date="2026-07-19", limit_up=True, yellow=True,
        )
        state, events = update_state(state, [confirmation], "2026-07-20")
        self.assertEqual(events[-1]["type"], "entry_triggered")
        execution = row(
            "2026-07-21", close=entry_close, open_price=entry_close,
            cross=True, cross_date="2026-07-19", limit_up=True, yellow=True,
        )
        state, events = update_state(state, [execution], "2026-07-21")
        self.assertEqual(events[0]["type"], "entry_executed")
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

    def test_closed_position_waits_for_a_fresh_later_signal_before_reentry(self):
        state = self.start_main()
        state, _ = update_state(
            state,
            [row("2026-07-22", selected=True, cross=True, close=12.0)],
            "2026-07-22",
        )
        state, events = update_state(
            state,
            [row("2026-07-23", selected=True, cross=True, close=11.3)],
            "2026-07-23",
        )
        self.assertEqual(state["active"], [])
        self.assertEqual([event["type"] for event in events], ["exit_triggered"])

        state, events = update_state(
            state,
            [row("2026-07-24", selected=True, cross=True, close=12.5, open_price=11.4)],
            "2026-07-24",
        )
        self.assertEqual([event["type"] for event in events], ["removed"])
        self.assertEqual(state["active"], [])

        state, events = update_state(
            state,
            [
                row(
                    "2026-07-25",
                    selected=True,
                    cross=True,
                    cross_date="2026-07-25",
                    close=12.5,
                    next_breakout_high=13.0,
                )
            ],
            "2026-07-25",
        )
        self.assertEqual(events[0]["type"], "setup_added")
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-26",
                    selected=True,
                    cross=True,
                    cross_date="2026-07-25",
                    close=13.2,
                    entry_breakout_high=13.0,
                )
            ],
            "2026-07-26",
        )
        self.assertEqual(events[-1]["type"], "entry_triggered")
        self.assertEqual(state["active"], [])
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-27",
                    selected=True,
                    cross=True,
                    cross_date="2026-07-25",
                    close=13.4,
                    open_price=13.3,
                )
            ],
            "2026-07-27",
        )
        self.assertEqual(events[0]["type"], "entry_executed")
        self.assertEqual(state["active"][0]["entry_date"], "2026-07-27")
        self.assertEqual(state["active"][0]["entry_price"], 13.3)

    def test_cancelled_main_setup_cannot_reuse_the_same_cross_date(self):
        state, events = update_state(
            empty_state(),
            [
                row(
                    "2026-07-20",
                    selected=True,
                    cross=True,
                    cross_age=0,
                    cross_date="2026-07-20",
                )
            ],
            "2026-07-20",
        )
        self.assertEqual(events[-1]["type"], "setup_added")
        self.assertEqual(
            state["consumed_signals"],
            [{"code": "600001", "cross_date": "2026-07-20"}],
        )

        state, events = update_state(
            state,
            [row("2026-07-21", dragon_above=False)],
            "2026-07-21",
        )
        self.assertEqual(state["pending_main"], [])
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
                    selected=True,
                    cross=True,
                    cross_age=2,
                    cross_date="2026-07-20",
                )
            ],
            "2026-07-22",
        )
        self.assertEqual(events, [])
        self.assertEqual(state["pending_main"], [])

        state, events = update_state(
            state,
            [
                row(
                    "2026-07-23",
                    selected=True,
                    cross=True,
                    cross_age=0,
                    cross_date="2026-07-23",
                )
            ],
            "2026-07-23",
        )
        self.assertEqual(events[-1]["type"], "setup_added")
        self.assertEqual(len(state["pending_main"]), 1)

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
            [
                row(
                    "2026-07-23",
                    cross=True,
                    cross_age=0,
                    cross_date="2026-07-23",
                    limit_up=True,
                    yellow=True,
                )
            ],
            "2026-07-23",
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

    def test_entry_trigger_waits_for_next_open_and_same_day_rerun_is_idempotent(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True, next_breakout_high=10.4)],
            "2026-07-20",
        )
        state, events = update_state(
            state,
            [row("2026-07-21", selected=True, cross=True, close=10.5)],
            "2026-07-21",
        )
        self.assertEqual([event["type"] for event in events], ["entry_triggered"])
        self.assertEqual(state["active"], [])
        self.assertEqual(len(state["pending_entry_execution"]), 1)

        state, events = update_state(
            state,
            [row("2026-07-21", selected=True, cross=True, close=10.6)],
            "2026-07-21",
        )
        self.assertEqual(events, [])
        self.assertEqual(len(state["pending_entry_execution"]), 1)
        self.assertEqual(state["active"], [])

        state, events = update_state(
            state,
            [row("2026-07-22", selected=True, cross=True, open_price=10.8, close=11.0)],
            "2026-07-22",
        )
        self.assertEqual(events[0]["type"], "entry_executed")
        self.assertEqual(state["active"][0]["entry_date"], "2026-07-22")
        self.assertEqual(state["active"][0]["entry_price"], 10.8)
        self.assertEqual(state["active"][0]["entry_trigger_date"], "2026-07-21")

    def test_one_word_limit_up_defers_entry_then_uses_first_tradable_open(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", selected=True, cross=True, close=10.5)],
            "2026-07-21",
        )
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-22",
                    selected=True,
                    cross=True,
                    open_price=11.0,
                    close=11.0,
                    one_word_limit_up=True,
                )
            ],
            "2026-07-22",
        )
        self.assertEqual(events[0]["type"], "entry_execution_blocked")
        self.assertEqual(state["active"], [])
        self.assertEqual(
            state["pending_entry_execution"][0]["execution_wait_bars"],
            1,
        )
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-22",
                    selected=True,
                    cross=True,
                    open_price=11.0,
                    close=11.0,
                    one_word_limit_up=True,
                )
            ],
            "2026-07-22",
        )
        self.assertEqual(events, [])
        self.assertEqual(
            state["pending_entry_execution"][0]["execution_wait_bars"],
            1,
        )
        state, events = update_state(
            state,
            [row("2026-07-23", selected=True, cross=True, open_price=11.2, close=11.4)],
            "2026-07-23",
        )
        self.assertEqual(events[0]["type"], "entry_executed")
        self.assertEqual(state["active"][0]["entry_price"], 11.2)

    def test_blocked_entry_is_cancelled_when_the_dragon_tiger_relation_breaks(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", selected=True, cross=True, close=10.5)],
            "2026-07-21",
        )

        state, events = update_state(
            state,
            [
                row(
                    "2026-07-22",
                    selected=False,
                    cross=False,
                    dragon_above=False,
                    open_price=11.0,
                    close=11.0,
                    one_word_limit_up=True,
                )
            ],
            "2026-07-22",
        )

        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual(state["active"], [])
        self.assertEqual(events[0]["type"], "entry_cancelled")
        self.assertIn("龙线不再高于虎线", events[0]["reason"])

    def test_new_cross_replaces_a_blocked_old_entry_order(self):
        state, _ = update_state(
            empty_state(),
            [
                row(
                    "2026-07-20",
                    selected=True,
                    cross=True,
                    cross_date="2026-07-20",
                )
            ],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [
                row(
                    "2026-07-21",
                    selected=True,
                    cross=True,
                    cross_date="2026-07-20",
                    close=10.5,
                )
            ],
            "2026-07-21",
        )

        state, events = update_state(
            state,
            [
                row(
                    "2026-07-22",
                    selected=True,
                    cross=True,
                    cross_date="2026-07-22",
                    open_price=11.0,
                    close=11.0,
                    one_word_limit_up=True,
                )
            ],
            "2026-07-22",
        )

        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual(len(state["pending_main"]), 1)
        self.assertEqual(
            state["pending_main"][0]["setup_cross_date"],
            "2026-07-22",
        )
        self.assertEqual(
            [event["type"] for event in events],
            ["entry_cancelled", "setup_added"],
        )

    def test_missing_open_never_falls_back_to_close_for_entry_execution(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", selected=True, cross=True, close=10.5)],
            "2026-07-21",
        )
        missing_open = row(
            "2026-07-22",
            selected=True,
            cross=True,
            close=11.0,
        )
        missing_open.pop("open")

        state, events = update_state(
            state,
            [missing_open],
            "2026-07-22",
        )

        self.assertEqual([event["type"] for event in events], ["entry_execution_blocked"])
        self.assertEqual(state["active"], [])
        self.assertEqual(len(state["pending_entry_execution"]), 1)
        self.assertEqual(
            state["pending_entry_execution"][0]["operation"],
            "暂停执行买入",
        )

        state, events = update_state(
            state,
            [row("2026-07-23", selected=True, cross=True, open_price=10.8, close=11.1)],
            "2026-07-23",
        )
        self.assertEqual(events[0]["type"], "entry_executed")
        self.assertEqual(state["active"][0]["entry_price"], 10.8)

    def test_missing_open_cancels_when_the_original_signal_recalculates_away(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True, cross_age=0)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", selected=True, cross=True, cross_age=1, close=10.5)],
            "2026-07-21",
        )
        missing_open = row(
            "2026-07-22",
            selected=False,
            cross=False,
            dragon_above=True,
            close=11.0,
        )
        missing_open.pop("open")

        state, events = update_state(
            state,
            [missing_open],
            "2026-07-22",
        )

        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual([event["type"] for event in events], ["entry_cancelled"])
        self.assertIn("重算消失", events[0]["reason"])

    def test_suspended_entry_is_cancelled_after_five_waiting_sessions(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", selected=True, cross=True, close=10.5)],
            "2026-07-21",
        )

        for day in range(22, 27):
            state, events = update_state(state, [], f"2026-07-{day:02d}")

        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual(state["active"], [])
        self.assertEqual(events[0]["type"], "entry_cancelled")
        self.assertIn("连续5个交易日", events[0]["reason"])
        self.assertIn("行情缺失", events[0]["reason"])

    def test_one_word_limit_up_entry_cancels_after_five_sessions(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", selected=True, cross=True, close=10.5)],
            "2026-07-21",
        )
        for day in range(22, 27):
            state, events = update_state(
                state,
                [
                    row(
                        f"2026-07-{day:02d}",
                        selected=True,
                        cross=True,
                        open_price=11.0,
                        close=11.0,
                        one_word_limit_up=True,
                    )
                ],
                f"2026-07-{day:02d}",
            )
        self.assertEqual(state["pending_entry_execution"], [])
        self.assertEqual(state["active"], [])
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

    def test_success_stats_use_completed_waves_only(self):
        state = self.start_main()
        state, _ = update_state(state, [row("2026-07-22", close=11.55, dragon_above=True, cross=True)], "2026-07-22")
        stats = strategy_stats(state)
        self.assertEqual(stats["sample_count"], 0)
        self.assertIsNone(stats["current_success_rate"])
        self.assertAlmostEqual(stats["active_average_return"], 10.0)

        state, _ = update_state(
            state,
            [row("2026-07-23", close=11.0, dragon_above=False)],
            "2026-07-23",
        )
        stats = strategy_stats(state)
        self.assertEqual(stats["sample_count"], 0)
        self.assertEqual(stats["pending_exit_execution_count"], 1)
        state, _ = update_state(
            state,
            [row("2026-07-24", close=10.9, open_price=11.0)],
            "2026-07-24",
        )
        stats = strategy_stats(state)
        self.assertEqual(stats["sample_count"], 1)
        self.assertEqual(stats["current_success_rate"], 100.0)
        self.assertAlmostEqual(stats["all_average_return"], (11.0 / 10.5 - 1) * 100)

    def test_secondary_stats_include_closed_success_and_realized_return(self):
        state = empty_state()
        state["secondary_closed"] = [
            {"exit_return_pct": 10.0},
            {"exit_return_pct": -5.0},
        ]
        stats = secondary_strategy_stats(state)
        self.assertEqual(stats["closed_success_rate"], 50.0)
        self.assertAlmostEqual(stats["realized_compound_return"], 4.5)

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
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True, cross_age=7)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", close=10.5, dragon_above=True, cross=False)],
            "2026-07-21",
        )
        state, events = update_state(
            state,
            [row("2026-07-22", close=10.6, dragon_above=True, cross=False)],
            "2026-07-22",
        )
        self.assertEqual(state["active"][0]["status"], "趋势开始")
        state, events = update_state(
            state,
            [row("2026-07-23", close=10.7, dragon_above=True, cross=False)],
            "2026-07-23",
        )
        self.assertEqual(len(state["active"]), 1)
        self.assertEqual(state["closed"], [])
        self.assertEqual(state["active"][0]["status"], "上升趋势中")
        self.assertEqual(events, [])

    def test_short_lived_signal_is_cancelled_before_buy(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True, cross_age=0, cross_lookback_days=5)],
            "2026-07-20",
        )
        state, events = update_state(
            state,
            [row("2026-07-21", close=9.8, cross=False, dragon_above=True)],
            "2026-07-21",
        )
        self.assertEqual(state["pending_main"], [])
        self.assertEqual(state["active"], [])
        self.assertEqual(events[0]["type"], "setup_cancelled")
        self.assertIn("重算消失", events[0]["reason"])

    def test_recalculated_signal_erasure_after_buy_only_warns(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True, cross_age=0, cross_lookback_days=5)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", selected=True, close=10.5, cross=True)],
            "2026-07-21",
        )
        state, events = update_state(
            state,
            [row("2026-07-22", close=10.2, cross=False, dragon_above=True)],
            "2026-07-22",
        )
        self.assertEqual(state["active"][0]["status"], "趋势开始")
        state, events = update_state(
            state,
            [row("2026-07-23", close=10.2, cross=False, dragon_above=True)],
            "2026-07-23",
        )
        self.assertEqual(len(state["active"]), 1)
        self.assertEqual(state["closed"], [])
        self.assertEqual(state["active"][0]["status"], "待观察中")
        self.assertEqual(state["active"][0]["operation"], "谨慎持有")
        self.assertTrue(state["active"][0]["signal_repainted_after_entry"])
        self.assertEqual(events[0]["type"], "trend_warning")

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

    def test_primary_selection_is_not_duplicated_in_secondary(self):
        strict = row(
            "2026-07-20", selected=True, cross=True, limit_up=True, yellow=True
        )
        state, _ = update_state(empty_state(), [strict], "2026-07-20")
        self.assertEqual(len(state["pending_main"]), 1)
        self.assertEqual(len(state["secondary_active"]), 0)
        self.assertEqual(len(state["pending_secondary"]), 0)

    def test_secondary_is_promoted_to_primary(self):
        candidate = row(
            "2026-07-20", cross=True, limit_up=True, yellow=True
        )
        state, _ = update_state(empty_state(), [candidate], "2026-07-20")
        strict = row(
            "2026-07-21", close=10.5, selected=True,
            cross=True, limit_up=True, yellow=True,
        )
        state, events = update_state(state, [strict], "2026-07-21")
        self.assertEqual(state["active"], [])
        self.assertEqual(len(state["pending_entry_execution"]), 1)
        self.assertEqual(
            {event["type"] for event in events},
            {"setup_promoted", "entry_triggered"},
        )
        execution = row(
            "2026-07-22", close=10.7, open_price=10.6, selected=True,
            cross=True, limit_up=True, yellow=True,
        )
        state, events = update_state(state, [execution], "2026-07-22")
        self.assertEqual(len(state["active"]), 1)
        self.assertEqual(len(state["secondary_active"]), 0)
        self.assertEqual(state["secondary_closed"], [])
        self.assertEqual(state["active"][0]["entry_date"], "2026-07-22")
        self.assertEqual(state["active"][0]["entry_price"], 10.6)
        self.assertEqual(state["active"][0]["last_close"], 10.7)
        self.assertEqual(state["active"][0]["origin_area"], "secondary")
        self.assertEqual(
            {event["type"] for event in events},
            {"entry_executed"},
        )

    def test_close_must_strictly_break_previous_five_day_high(self):
        state, _ = update_state(
            empty_state(),
            [
                row(
                    "2026-07-20",
                    selected=True,
                    cross=True,
                    next_breakout_high=10.5,
                )
            ],
            "2026-07-20",
        )
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-21",
                    selected=True,
                    cross=True,
                    close=10.5,
                    entry_breakout_high=10.5,
                    next_breakout_high=10.5,
                )
            ],
            "2026-07-21",
        )
        self.assertEqual(state["active"], [])
        self.assertEqual(events, [])
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-22",
                    selected=True,
                    cross=True,
                    close=10.51,
                    entry_breakout_high=10.5,
                )
            ],
            "2026-07-22",
        )
        self.assertEqual(events[-1]["type"], "entry_triggered")
        self.assertEqual(state["active"], [])
        self.assertEqual(
            state["pending_entry_execution"][0]["operation"],
            "下一交易日开盘买入",
        )

    def test_missing_breakout_high_never_falls_back_to_old_five_percent_rule(self):
        state, _ = update_state(
            empty_state(),
            [
                row(
                    "2026-07-20",
                    selected=True,
                    cross=True,
                    next_breakout_high=None,
                    entry_breakout_high=None,
                )
            ],
            "2026-07-20",
        )
        state, events = update_state(
            state,
            [
                row(
                    "2026-07-21",
                    selected=True,
                    cross=True,
                    close=20.0,
                    next_breakout_high=None,
                    entry_breakout_high=None,
                )
            ],
            "2026-07-21",
        )
        self.assertEqual(events, [])
        self.assertEqual(state["active"], [])
        self.assertIn("数据等待更新", state["pending_main"][0]["status_detail"])

    def test_tenth_day_can_enter_and_eleventh_day_cancels(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-01", selected=True, cross=True)],
            "2026-07-01",
        )
        state["pending_main"][0]["setup_elapsed_bars"] = 9
        state["last_trade_date"] = "2026-07-09"
        state, events = update_state(
            state,
            [row("2026-07-10", selected=True, cross=True, close=10.41)],
            "2026-07-10",
        )
        self.assertEqual(events[-1]["type"], "entry_triggered")
        self.assertEqual(len(state["pending_entry_execution"]), 1)

        state, _ = update_state(
            empty_state(),
            [row("2026-07-01", selected=True, cross=True)],
            "2026-07-01",
        )
        state["pending_main"][0]["setup_elapsed_bars"] = 10
        state["last_trade_date"] = "2026-07-10"
        state, events = update_state(
            state,
            [row("2026-07-11", selected=True, cross=True, close=10.41)],
            "2026-07-11",
        )
        self.assertEqual(state["pending_main"], [])
        self.assertEqual(events[0]["type"], "setup_cancelled")

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
            "active": [
                {
                    "code": "600001",
                    "entry_date": "2026-08-01",
                    "last_date": "2026-08-03",
                }
            ],
            "closed": [],
            "secondary_active": [],
            "secondary_closed": [],
            "pending_main": [
                {
                    "code": "600002",
                    "cross_date": "2026-07-30",
                    "status": "待观察中",
                }
            ],
            "pending_secondary": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(
                json.dumps(legacy, ensure_ascii=False),
                encoding="utf-8",
            )
            migrated = load_state(path)
        self.assertEqual(len(migrated["active"]), 1)
        self.assertEqual(migrated["pending_main"], [])
        self.assertEqual(
            migrated["active"][0]["strategy_version"],
            "legacy_before_break5_trail3_2",
        )
        self.assertEqual(migrated["strategy_migration"]["reset_pending_count"], 1)
        self.assertEqual(
            migrated["consumed_signals"],
            [{"code": "600002", "cross_date": "2026-07-30"}],
        )

        same_cross = row(
            "2026-08-04",
            selected=True,
            cross=True,
            cross_date="2026-07-30",
        )
        same_cross["code"] = "600002"
        migrated, events = update_state(migrated, [same_cross], "2026-08-04")
        self.assertEqual(events, [])
        self.assertEqual(migrated["pending_main"], [])

        new_cross = row(
            "2026-08-05",
            selected=True,
            cross=True,
            cross_date="2026-08-05",
        )
        new_cross["code"] = "600002"
        migrated, events = update_state(migrated, [new_cross], "2026-08-05")
        self.assertEqual(events[-1]["type"], "setup_added")
        self.assertEqual(len(migrated["pending_main"]), 1)

    def test_replay_state_stops_at_requested_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp)
            for trade_date, close, selected in (
                ("2026-07-20", 10.0, True),
                ("2026-07-21", 9.5, False),
            ):
                payload = {
                    "trade_date": trade_date,
                    "results": [row(trade_date, close=close, selected=selected)],
                }
                path = results_dir / f"选股结果_{trade_date}.json"
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            state = replay_state(results_dir, "2026-07-20")
            self.assertEqual(state["last_trade_date"], "2026-07-20")
            self.assertEqual(state["pending_main"][0]["last_date"], "2026-07-20")


if __name__ == "__main__":
    unittest.main()
