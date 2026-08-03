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
    }


class StrategyTrackerTests(unittest.TestCase):
    def test_first_confirmed_weakening_becomes_warning(self):
        state, events = update_state(empty_state(), [row("2026-07-20", selected=True)], "2026-07-20")
        self.assertEqual(events[0]["type"], "added")
        self.assertEqual(len(state["active"]), 1)

        state, events = update_state(state, [row("2026-07-21", close=9.5, dragon_above=False)], "2026-07-21")
        self.assertEqual(len(state["active"]), 1)
        self.assertEqual(state["closed"], [])
        self.assertEqual(state["active"][0]["status"], "上升趋势中")
        self.assertEqual(state["active"][0]["missing_streak"], 1)
        self.assertEqual(events[0]["type"], "trend_warning")

    def test_same_day_rerun_does_not_duplicate_warning(self):
        state, _ = update_state(empty_state(), [row("2026-07-20", selected=True)], "2026-07-20")
        state, _ = update_state(state, [row("2026-07-21", dragon_above=False)], "2026-07-21")
        state, _ = update_state(state, [row("2026-07-21", dragon_above=False)], "2026-07-21")
        self.assertEqual(len(state["active"]), 1)
        self.assertEqual(state["closed"], [])

    def test_two_post_entry_weakening_days_warn_without_exit(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, dragon=13.0)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", dragon=12.0)],
            "2026-07-21",
        )
        self.assertEqual(len(state["active"]), 1)
        state, events = update_state(
            state,
            [row("2026-07-22", dragon=11.0)],
            "2026-07-22",
        )
        self.assertEqual(len(state["active"]), 1)
        self.assertEqual(state["closed"], [])
        self.assertEqual(state["active"][0]["status"], "上升趋势中")
        self.assertEqual(events[0]["type"], "trend_warning")

    def test_peak_drawdown_twenty_percent_takes_profit(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, close=10.0)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", close=15.0)],
            "2026-07-21",
        )
        state, events = update_state(
            state,
            [row("2026-07-22", close=12.0)],
            "2026-07-22",
        )
        self.assertEqual(state["active"], [])
        self.assertAlmostEqual(state["closed"][0]["exit_return_pct"], 20.0)
        self.assertIn("回撤20%", state["closed"][0]["exit_reason"])
        self.assertEqual(state["closed"][0]["status"], "趋势结束")
        self.assertEqual(events[0]["type"], "removed")

    def test_closed_position_waits_for_a_fresh_later_signal_before_reentry(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-07-20", selected=True, close=10.0)],
            "2026-07-20",
        )
        state, _ = update_state(
            state,
            [row("2026-07-21", selected=True, close=15.0)],
            "2026-07-21",
        )
        state, events = update_state(
            state,
            [row("2026-07-22", selected=True, close=12.0)],
            "2026-07-22",
        )
        self.assertEqual(state["active"], [])
        self.assertEqual([event["type"] for event in events], ["removed"])

        state, events = update_state(
            state,
            [row("2026-07-23", selected=True, close=12.5)],
            "2026-07-23",
        )
        self.assertEqual(events[0]["type"], "added")
        self.assertEqual(state["active"][0]["entry_date"], "2026-07-23")
        self.assertEqual(state["active"][0]["position_id"], "600001_2026-07-23")

    def test_sixty_following_bars_end_tracking(self):
        state, _ = update_state(
            empty_state(),
            [row("2026-01-01", selected=True)],
            "2026-01-01",
        )
        state["active"][0]["holding_days"] = 60
        state["last_trade_date"] = "2026-06-01"
        state, _ = update_state(
            state,
            [row("2026-06-02")],
            "2026-06-02",
        )
        self.assertEqual(state["active"], [])
        self.assertIn("60个后续交易日", state["closed"][0]["exit_reason"])

    def test_stats_use_mark_to_market_and_closed_records(self):
        state, _ = update_state(empty_state(), [row("2026-07-20", selected=True)], "2026-07-20")
        state, _ = update_state(state, [row("2026-07-21", close=11.0, dragon_above=True)], "2026-07-21")
        stats = strategy_stats(state)
        self.assertEqual(stats["sample_count"], 1)
        self.assertEqual(stats["current_success_rate"], 100.0)
        self.assertAlmostEqual(stats["active_average_return"], 10.0)

    def test_secondary_stats_include_closed_success_and_realized_return(self):
        state = empty_state()
        state["secondary_closed"] = [
            {"exit_return_pct": 10.0},
            {"exit_return_pct": -5.0},
        ]
        stats = secondary_strategy_stats(state)
        self.assertEqual(stats["closed_success_rate"], 50.0)
        self.assertAlmostEqual(stats["realized_compound_return"], 4.5)

    def test_secondary_adds_on_three_conditions_and_warns_on_weakening(self):
        candidate = row(
            "2026-07-20", cross=True, limit_up=True, yellow=True
        )
        state, events = update_state(empty_state(), [candidate], "2026-07-20")
        self.assertEqual(len(state["secondary_active"]), 1)
        self.assertEqual(events[0]["type"], "secondary_added")

        lost = row(
            "2026-07-21", close=9.5, dragon_above=False,
            cross=False, limit_up=True, yellow=True,
        )
        state, events = update_state(state, [lost], "2026-07-21")
        self.assertEqual(len(state["secondary_active"]), 1)
        self.assertEqual(state["secondary_closed"], [])
        self.assertEqual(events[0]["type"], "trend_warning")

    def test_secondary_accepts_bottom_instead_of_limit_up(self):
        candidate = row(
            "2026-07-20", cross=True, bottom=True, limit_up=False, yellow=True
        )
        state, events = update_state(empty_state(), [candidate], "2026-07-20")
        self.assertEqual(len(state["secondary_active"]), 1)
        self.assertEqual(events[0]["type"], "secondary_added")

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

        state, _ = update_state(empty_state(), [row("2026-07-20", selected=True)], "2026-07-20")
        state, events = update_state(
            state,
            [row("2026-07-21", name="ST测试", close=9.8, eligible=False)],
            "2026-07-21",
        )
        self.assertEqual(state["active"], [])
        self.assertEqual(state["closed"][0]["exit_reason"], "股票名称含 ST，不符合入选范围")
        self.assertEqual(events[0]["type"], "ineligible_removed")

    def test_primary_selection_is_not_duplicated_in_secondary(self):
        strict = row(
            "2026-07-20", selected=True, cross=True, limit_up=True, yellow=True
        )
        state, _ = update_state(empty_state(), [strict], "2026-07-20")
        self.assertEqual(len(state["active"]), 1)
        self.assertEqual(len(state["secondary_active"]), 0)

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
        self.assertEqual(state["active"][0]["entry_date"], "2026-07-20")
        self.assertEqual(state["active"][0]["entry_price"], 10.0)
        self.assertEqual(state["active"][0]["last_close"], 10.5)
        self.assertEqual(state["active"][0]["origin_area"], "secondary")
        self.assertEqual(
            {event["type"] for event in events},
            {"secondary_promoted"},
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
            self.assertEqual(state["active"][0]["last_date"], "2026-07-20")


if __name__ == "__main__":
    unittest.main()
