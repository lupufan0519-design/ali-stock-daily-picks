import sys
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy_tracker import empty_state, replay_state, strategy_stats, update_state


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
):
    return {
        "code": "600001",
        "name": name,
        "market": 1,
        "date": date,
        "close": close,
        "selected": selected,
        "dragon_above_tiger": dragon_above,
        "eligible": eligible,
        "cross_ok": cross,
        "bottom_ok": bottom,
        "limit_up_ok": limit_up,
        "yellow_ok": yellow,
    }


class StrategyTrackerTests(unittest.TestCase):
    def test_add_warn_and_remove_on_second_missing_day(self):
        state, events = update_state(empty_state(), [row("2026-07-20", selected=True)], "2026-07-20")
        self.assertEqual(events[0]["type"], "added")
        self.assertEqual(len(state["active"]), 1)

        state, events = update_state(state, [row("2026-07-21", close=9.5, dragon_above=False)], "2026-07-21")
        self.assertEqual(state["active"][0]["missing_streak"], 1)
        self.assertEqual(events[0]["type"], "signal_lost")

        state, events = update_state(state, [row("2026-07-22", close=9.0, dragon_above=False)], "2026-07-22")
        self.assertEqual(len(state["active"]), 0)
        self.assertEqual(len(state["closed"]), 1)
        self.assertAlmostEqual(state["closed"][0]["exit_return_pct"], -10.0)
        self.assertEqual(events[0]["type"], "removed")

    def test_signal_restored_cancels_warning(self):
        state, _ = update_state(empty_state(), [row("2026-07-20", selected=True)], "2026-07-20")
        state, _ = update_state(state, [row("2026-07-21", dragon_above=False)], "2026-07-21")
        state, events = update_state(state, [row("2026-07-22", close=10.5, dragon_above=True)], "2026-07-22")
        self.assertEqual(state["active"][0]["missing_streak"], 0)
        self.assertEqual(events[0]["type"], "signal_restored")

    def test_same_day_rerun_is_idempotent(self):
        state, _ = update_state(empty_state(), [row("2026-07-20", selected=True)], "2026-07-20")
        state, _ = update_state(state, [row("2026-07-21", dragon_above=False)], "2026-07-21")
        state, _ = update_state(state, [row("2026-07-21", dragon_above=False)], "2026-07-21")
        self.assertEqual(state["active"][0]["missing_streak"], 1)
        self.assertEqual(state["active"][0]["holding_days"], 2)

    def test_stats_use_mark_to_market_and_closed_records(self):
        state, _ = update_state(empty_state(), [row("2026-07-20", selected=True)], "2026-07-20")
        state, _ = update_state(state, [row("2026-07-21", close=11.0, dragon_above=True)], "2026-07-21")
        stats = strategy_stats(state)
        self.assertEqual(stats["sample_count"], 1)
        self.assertEqual(stats["current_success_rate"], 100.0)
        self.assertAlmostEqual(stats["active_average_return"], 10.0)

    def test_secondary_adds_on_three_conditions_and_removes_immediately(self):
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
        self.assertEqual(len(state["secondary_active"]), 0)
        self.assertEqual(len(state["secondary_closed"]), 1)
        self.assertEqual(events[0]["type"], "secondary_removed")
        self.assertAlmostEqual(state["secondary_closed"][0]["exit_return_pct"], -5.0)

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
        self.assertEqual(state["secondary_closed"][0]["exit_reason"], "满足全部条件，升级进入主选区")
        self.assertEqual(
            {event["type"] for event in events},
            {"added", "secondary_promoted"},
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
