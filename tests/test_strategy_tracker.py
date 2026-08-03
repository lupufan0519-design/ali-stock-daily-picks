import sys
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy_tracker import (
    empty_state,
    replay_state,
    secondary_strategy_stats,
    strategy_stats,
    update_state,
)


def row(
    date,
    close=10.0,
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
    cross_lookback_days=11,
):
    return {
        "code": "600001",
        "name": name,
        "market": 1,
        "date": date,
        "close": close,
        "selected": selected,
        "dragon_above_tiger": dragon_above,
        "dragon_value": dragon,
        "tiger_value": tiger,
        "eligible": eligible,
        "cross_ok": cross,
        "bottom_ok": bottom,
        "limit_up_ok": limit_up,
        "yellow_ok": yellow,
        "cross_age": cross_age,
        "cross_lookback_days": cross_lookback_days,
    }


class StrategyTrackerTests(unittest.TestCase):
    def start_main(self, *, setup_close=10.0, entry_close=10.5, dragon=11.0):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True, close=setup_close, dragon=dragon)],
            "2026-07-20",
        )
        state, events = update_state(
            state,
            [row("2026-07-21", selected=True, cross=True, close=entry_close, dragon=dragon)],
            "2026-07-21",
        )
        self.assertEqual(events[-1]["type"], "trend_started")
        self.assertEqual(state["active"][0]["status"], "趋势开始")
        return state

    def start_secondary(self, *, setup_close=10.0, entry_close=10.5):
        candidate = row(
            "2026-07-20", close=setup_close,
            cross=True, limit_up=True, yellow=True,
        )
        state, _ = update_state(empty_state(), [candidate], "2026-07-20")
        confirmation = row(
            "2026-07-21", close=entry_close,
            cross=True, limit_up=True, yellow=True,
        )
        state, events = update_state(state, [confirmation], "2026-07-21")
        self.assertEqual(events[-1]["type"], "trend_started")
        return state

    def test_dragon_no_longer_above_tiger_ends_immediately(self):
        state = self.start_main()
        state, events = update_state(
            state,
            [row("2026-07-22", close=10.2, dragon_above=False)],
            "2026-07-22",
        )
        self.assertEqual(state["active"], [])
        self.assertEqual(state["closed"][0]["status"], "趋势结束")
        self.assertIn("龙线不再高于虎线", state["closed"][0]["exit_reason"])
        self.assertEqual(events[0]["type"], "removed")

    def test_same_day_rerun_does_not_duplicate_exit(self):
        state = self.start_main()
        state, _ = update_state(state, [row("2026-07-22", dragon_above=False)], "2026-07-22")
        state, _ = update_state(state, [row("2026-07-22", dragon_above=False)], "2026-07-22")
        self.assertEqual(state["active"], [])
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

    def test_peak_drawdown_five_percent_after_five_percent_profit_takes_profit(self):
        state = self.start_main()
        state, _ = update_state(
            state,
            [row("2026-07-22", close=12.0, cross=True)],
            "2026-07-22",
        )
        state, events = update_state(
            state,
            [row("2026-07-23", close=11.3, cross=True)],
            "2026-07-23",
        )
        self.assertEqual(state["active"], [])
        self.assertAlmostEqual(
            state["closed"][0]["exit_return_pct"],
            (11.3 / 10.5 - 1.0) * 100.0,
        )
        self.assertIn("回撤5%", state["closed"][0]["exit_reason"])
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
        self.assertEqual([event["type"] for event in events], ["removed"])

        state, events = update_state(
            state,
            [row("2026-07-24", selected=True, cross=True, close=12.5)],
            "2026-07-24",
        )
        self.assertEqual(events[0]["type"], "setup_added")
        self.assertEqual(state["active"], [])
        state, events = update_state(
            state,
            [row("2026-07-25", selected=True, cross=True, close=13.2)],
            "2026-07-25",
        )
        self.assertEqual(events[-1]["type"], "trend_started")
        self.assertEqual(state["active"][0]["entry_date"], "2026-07-25")

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
        self.assertIn("60个后续交易日", state["closed"][0]["exit_reason"])

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
        self.assertEqual(len(state["secondary_closed"]), 1)
        self.assertEqual(events[0]["type"], "secondary_removed")

    def test_natural_cross_label_expiry_is_not_an_exit_or_warning(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, cross=True, cross_age=10)],
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

    def test_recalculated_signal_erasure_after_buy_ends_trend(self):
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
        self.assertEqual(state["active"], [])
        self.assertIn("重算消失", state["closed"][0]["exit_reason"])
        self.assertEqual(events[0]["type"], "removed")

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
        self.assertEqual(state["closed"][0]["exit_reason"], "股票名称含 ST，不符合入选范围")
        self.assertEqual(events[0]["type"], "ineligible_removed")

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
        self.assertEqual(len(state["active"]), 1)
        self.assertEqual(len(state["secondary_active"]), 0)
        self.assertEqual(state["secondary_closed"], [])
        self.assertEqual(state["active"][0]["entry_date"], "2026-07-21")
        self.assertEqual(state["active"][0]["entry_price"], 10.5)
        self.assertEqual(state["active"][0]["last_close"], 10.5)
        self.assertEqual(state["active"][0]["origin_area"], "secondary")
        self.assertEqual(
            {event["type"] for event in events},
            {"setup_promoted", "trend_started"},
        )

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
