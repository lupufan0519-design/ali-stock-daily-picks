import tempfile
import unittest
from pathlib import Path

from selection_history import (
    empty_history,
    load_history,
    record_close,
    record_intraday_pools,
    refresh_history,
    write_history,
)
from simple_strategy import FIRST_TIER, SECOND_TIER, STRATEGY_VERSION, THIRD_TIER


def pick(code="600001", price=10.0):
    return {
        "code": code,
        "name": "示例股票",
        "market": 1,
        "price": price,
        "bottom_date": "2026-08-05",
        "dragon_value": 10.2,
        "tiger_value": 10.1,
        "yellow_line_value": 10.3,
        "line_gap_abs": 0.1,
        "prior_three_gap_abs": [0.2, 0.3, 0.1],
        "prior_three_gap_max": 0.3,
    }


class SelectionHistoryTests(unittest.TestCase):
    def test_legacy_same_day_candidate_moves_to_history_removal_audit(self):
        history = empty_history("2026-08-07")
        history.pop("visible_bottom_migration_version")
        invalid_record = {
            **pick(),
            "id": "2026-08-07:first:600001",
            "trade_date": "2026-08-07",
            "tier": FIRST_TIER,
            "bottom_date": "2026-08-07",
            "selected_price": 10.0,
            "current_price": 10.2,
            "current_date": "2026-08-08",
            "return_pct": 2.0,
        }
        history["dates"] = [
            {
                "trade_date": "2026-08-07",
                FIRST_TIER: [invalid_record],
                SECOND_TIER: [],
                THIRD_TIER: [],
                "removed": [],
                "live_active_codes": ["600001"],
            }
        ]

        history, changed = record_intraday_pools(
            history,
            "2026-08-08",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: []},
            set(),
            "2026-08-08T10:00:00+08:00",
        )

        day = history["dates"][0]
        self.assertTrue(changed)
        self.assertEqual(day[FIRST_TIER], [])
        self.assertEqual(day["live_active_codes"], [])
        self.assertEqual(len(day["removed"]), 1)
        self.assertTrue(day["removed"][0]["invalid_signal"])
        self.assertEqual(
            day["removed"][0]["removal_reason"],
            "可能见底信号当日尚未形成（历史纠正）",
        )
        self.assertEqual(history["summary"]["selection_count"], 0)
        self.assertEqual(history["summary"]["evaluated_count"], 0)
        self.assertEqual(history["visible_bottom_migration_version"], 1)

        repeated, changed_again = record_intraday_pools(
            history,
            "2026-08-08",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: []},
            set(),
            "2026-08-08T10:00:00+08:00",
        )
        self.assertFalse(changed_again)
        self.assertEqual(repeated, history)

    def test_corrected_signal_can_reappear_after_a_later_bar(self):
        history = empty_history("2026-08-07")
        history.pop("visible_bottom_migration_version")
        history["dates"] = [
            {
                "trade_date": "2026-08-07",
                FIRST_TIER: [
                    {
                        **pick(),
                        "trade_date": "2026-08-07",
                        "tier": FIRST_TIER,
                        "bottom_date": "2026-08-07",
                    }
                ],
                SECOND_TIER: [],
                THIRD_TIER: [],
                "removed": [],
                "live_active_codes": ["600001"],
            }
        ]
        valid = pick()
        valid["bottom_date"] = "2026-08-06"

        history, changed = record_intraday_pools(
            history,
            "2026-08-07",
            {FIRST_TIER: [], SECOND_TIER: [valid], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:05:00+08:00",
        )

        day = history["dates"][0]
        self.assertTrue(changed)
        self.assertEqual(day[FIRST_TIER], [])
        self.assertEqual(len(day[SECOND_TIER]), 1)
        self.assertEqual(day[SECOND_TIER][0]["bottom_date"], "2026-08-06")
        self.assertTrue(day["removed"][0]["active_again"])
        self.assertEqual(day["live_active_codes"], ["600001"])

    def test_history_correction_preserves_an_existing_removal_event(self):
        history = empty_history("2026-08-07")
        history.pop("visible_bottom_migration_version")
        prior_removal = {
            "id": "2026-08-07:removed:600001",
            "code": "600001",
            "name": "示例股票",
            "selected_tier": FIRST_TIER,
            "removed_at": "2026-08-07T10:05:00+08:00",
            "removal_reason": "可能见底信号消失",
            "removal_count": 1,
            "active_again": True,
            "restored_at": "2026-08-07T10:10:00+08:00",
        }
        history["dates"] = [
            {
                "trade_date": "2026-08-07",
                FIRST_TIER: [
                    {
                        **pick(),
                        "trade_date": "2026-08-07",
                        "tier": FIRST_TIER,
                        "bottom_date": "2026-08-07",
                    }
                ],
                SECOND_TIER: [],
                THIRD_TIER: [],
                "removed": [prior_removal],
                "live_active_codes": ["600001"],
            }
        ]

        history, changed = record_intraday_pools(
            history,
            "2026-08-08",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: []},
            set(),
            "2026-08-08T10:00:00+08:00",
        )

        removed = history["dates"][0]["removed"]
        self.assertTrue(changed)
        self.assertEqual(len(removed), 2)
        self.assertEqual(removed[0], prior_removal)
        self.assertEqual(
            removed[1]["id"],
            "2026-08-07:removed-correction:600001",
        )
        self.assertTrue(removed[1]["invalid_signal"])
        self.assertEqual(
            removed[1]["removed_at"],
            "2026-08-08T10:00:00+08:00",
        )

    def test_correction_and_normal_removal_have_independent_lifecycles(self):
        history = empty_history("2026-08-07")
        history.pop("visible_bottom_migration_version")
        history["dates"] = [
            {
                "trade_date": "2026-08-07",
                FIRST_TIER: [
                    {
                        **pick(),
                        "trade_date": "2026-08-07",
                        "tier": FIRST_TIER,
                        "bottom_date": "2026-08-07",
                    }
                ],
                SECOND_TIER: [],
                THIRD_TIER: [],
                "removed": [
                    {
                        "id": "2026-08-07:removed:600001",
                        "code": "600001",
                        "name": "示例股票",
                        "selected_tier": FIRST_TIER,
                        "removed_at": "2026-08-07T10:05:00+08:00",
                        "removal_reason": "可能见底信号消失",
                        "removal_count": 1,
                        "active_again": False,
                        "restored_at": "",
                    }
                ],
                "live_active_codes": ["600001"],
            }
        ]
        valid = pick()
        valid["bottom_date"] = "2026-08-06"

        history, _ = record_intraday_pools(
            history,
            "2026-08-07",
            {FIRST_TIER: [], SECOND_TIER: [valid], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:10:00+08:00",
        )
        removed = history["dates"][0]["removed"]
        normal = next(item for item in removed if not item.get("invalid_signal"))
        correction = next(item for item in removed if item.get("invalid_signal"))
        self.assertTrue(normal["active_again"])
        self.assertEqual(normal["restored_at"], "2026-08-07T10:10:00+08:00")
        self.assertTrue(correction["active_again"])
        self.assertEqual(
            correction["restored_at"],
            "2026-08-07T10:10:00+08:00",
        )

        history, _ = record_intraday_pools(
            history,
            "2026-08-07",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:15:00+08:00",
        )
        removed = history["dates"][0]["removed"]
        normal = next(item for item in removed if not item.get("invalid_signal"))
        correction = next(item for item in removed if item.get("invalid_signal"))
        self.assertEqual(normal["removed_at"], "2026-08-07T10:15:00+08:00")
        self.assertEqual(normal["removal_count"], 2)
        self.assertFalse(normal["active_again"])
        self.assertEqual(
            correction["removal_reason"],
            "可能见底信号当日尚未形成（历史纠正）",
        )
        self.assertEqual(correction["removed_at"], "2026-08-07T10:10:00+08:00")
        self.assertEqual(correction["removal_count"], 1)
        self.assertFalse(correction["active_again"])
        self.assertEqual(correction["restored_at"], "")
        self.assertEqual(history["summary"]["removed_count"], 1)

    def test_intraday_refresh_repairs_a_duplicated_removed_count(self):
        history = empty_history("2026-08-07")
        history["dates"] = [
            {
                "trade_date": "2026-08-07",
                FIRST_TIER: [],
                SECOND_TIER: [],
                THIRD_TIER: [],
                "removed": [
                    {
                        "id": "2026-08-07:removed:600001",
                        "code": "600001",
                    },
                    {
                        "id": "2026-08-07:removed-correction:600001",
                        "code": "600001",
                        "invalid_signal": True,
                    },
                ],
                "live_active_codes": [],
            }
        ]
        history["summary"]["removed_count"] = 2

        history, changed = record_intraday_pools(
            history,
            "2026-08-08",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: []},
            set(),
            "2026-08-08T10:00:00+08:00",
        )

        self.assertTrue(changed)
        self.assertEqual(history["summary"]["removed_count"], 1)

    def test_intraday_repaint_adds_removed_section_without_erasing_selection(self):
        history, changed = record_intraday_pools(
            empty_history(),
            "2026-08-07",
            {FIRST_TIER: [pick()], SECOND_TIER: [], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:00:00+08:00",
        )
        self.assertTrue(changed)
        self.assertEqual(history["dates"][0]["live_active_codes"], ["600001"])

        history, changed = record_intraday_pools(
            history,
            "2026-08-07",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:05:00+08:00",
        )
        day = history["dates"][0]
        self.assertTrue(changed)
        self.assertEqual(len(day[FIRST_TIER]), 1)
        self.assertEqual(day["live_active_codes"], [])
        self.assertEqual(len(day["removed"]), 1)
        self.assertEqual(day["removed"][0]["code"], "600001")
        self.assertEqual(day["removed"][0]["removal_reason"], "可能见底信号消失")
        self.assertEqual(history["summary"]["selection_count"], 1)
        self.assertEqual(history["summary"]["removed_count"], 1)

    def test_missing_quote_does_not_create_a_false_removal(self):
        history, _ = record_intraday_pools(
            empty_history(),
            "2026-08-07",
            {FIRST_TIER: [pick()], SECOND_TIER: [], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:00:00+08:00",
        )
        history, changed = record_intraday_pools(
            history,
            "2026-08-07",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: []},
            set(),
            "2026-08-07T10:05:00+08:00",
        )
        day = history["dates"][0]
        self.assertFalse(changed)
        self.assertEqual(day["live_active_codes"], ["600001"])
        self.assertEqual(day["removed"], [])

    def test_reappearing_signal_keeps_removal_audit_and_marks_restored(self):
        history, _ = record_intraday_pools(
            empty_history(),
            "2026-08-07",
            {FIRST_TIER: [pick()], SECOND_TIER: [], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:00:00+08:00",
        )
        history, _ = record_intraday_pools(
            history,
            "2026-08-07",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:05:00+08:00",
        )
        history, changed = record_intraday_pools(
            history,
            "2026-08-07",
            {FIRST_TIER: [], SECOND_TIER: [pick()], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:10:00+08:00",
        )
        removed = history["dates"][0]["removed"][0]
        self.assertTrue(changed)
        self.assertTrue(removed["active_again"])
        self.assertEqual(removed["restored_at"], "2026-08-07T10:10:00+08:00")
        self.assertEqual(history["dates"][0]["live_active_codes"], ["600001"])

    def test_close_record_preserves_intraday_removed_ledger(self):
        history, _ = record_intraday_pools(
            empty_history(),
            "2026-08-07",
            {FIRST_TIER: [pick()], SECOND_TIER: [], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:00:00+08:00",
        )
        history, _ = record_intraday_pools(
            history,
            "2026-08-07",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: []},
            {"600001"},
            "2026-08-07T10:05:00+08:00",
        )
        closed = record_close(
            history,
            "2026-08-07",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: []},
            [pick(price=9.8)],
            "2026-08-07T15:40:00+08:00",
        )
        day = closed["dates"][0]
        self.assertEqual(len(day[FIRST_TIER]), 1)
        self.assertEqual(len(day["removed"]), 1)

    def test_same_day_selection_waits_and_next_day_counts_success(self):
        history = record_close(
            empty_history(),
            "2026-08-06",
            {FIRST_TIER: [pick()], SECOND_TIER: []},
            [pick()],
        )
        self.assertEqual(history["summary"]["selection_count"], 1)
        self.assertEqual(history["summary"]["evaluated_count"], 0)
        self.assertIsNone(history["summary"]["success_rate_pct"])

        history = refresh_history(
            history,
            {"600001": {"price": 11.0}},
            "2026-08-07",
        )
        self.assertEqual(history["summary"]["evaluated_count"], 1)
        self.assertEqual(history["summary"]["success_count"], 1)
        self.assertAlmostEqual(history["summary"]["success_rate_pct"], 100.0)
        self.assertAlmostEqual(history["summary"]["average_return_pct"], 10.0)

    def test_only_close_record_advances_the_explicit_close_marker(self):
        history, _ = record_intraday_pools(
            empty_history("2026-08-11"),
            "2026-08-12",
            {FIRST_TIER: [pick()], SECOND_TIER: [], THIRD_TIER: []},
            {"600001"},
            "2026-08-12T10:00:00+08:00",
        )
        self.assertEqual(history["last_close_trade_date"], "")

        history = record_close(
            history,
            "2026-08-12",
            {FIRST_TIER: [pick()], SECOND_TIER: [], THIRD_TIER: []},
            [pick()],
            "2026-08-12T15:40:00+08:00",
        )
        self.assertEqual(history["last_close_trade_date"], "2026-08-12")

    def test_same_stock_on_different_dates_is_an_independent_selection(self):
        history = record_close(
            empty_history(),
            "2026-08-06",
            {FIRST_TIER: [pick()], SECOND_TIER: []},
            [pick()],
        )
        history = record_close(
            history,
            "2026-08-07",
            {FIRST_TIER: [], SECOND_TIER: [pick(price=11.0)]},
            [pick(price=11.0)],
        )
        self.assertEqual(history["summary"]["selection_count"], 2)
        self.assertEqual(history["summary"]["evaluated_count"], 1)

    def test_load_resets_an_old_strategy_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            write_history(path, {**empty_history(), "strategy_version": "old"})
            loaded = load_history(path)
            self.assertEqual(loaded["strategy_version"], STRATEGY_VERSION)
            self.assertEqual(loaded["dates"], [])

    def test_third_tier_is_recorded_in_history_and_summary(self):
        history = record_close(
            empty_history(),
            "2026-08-06",
            {FIRST_TIER: [], SECOND_TIER: [], THIRD_TIER: [pick()]},
            [pick()],
        )
        self.assertEqual(history["summary"]["selection_count"], 1)
        self.assertEqual(history["summary"]["third_tier_count"], 1)
        self.assertEqual(len(history["dates"][0][THIRD_TIER]), 1)


if __name__ == "__main__":
    unittest.main()
