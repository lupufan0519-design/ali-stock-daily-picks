import copy
import unittest

from selection_history import audit_history_signals, empty_history, record_intraday_pools, summarize


class SignalHistoryIntegrityTests(unittest.TestCase):
    SESSIONS = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22"]

    def history(self, trade_date="2026-09-22", bottom_date="2026-09-07", base_date=""):
        record = {"id": trade_date + ":first:002132", "code": "002132", "name": "恒星科技", "tier": "first", "trade_date": trade_date,
                  "bottom_date": bottom_date, "selected_price": 4.2, "current_price": 4.3, "current_date": "2026-09-23", "return_pct": 2.38}
        if base_date:
            record["signal_base_date"] = base_date
        history = empty_history(trade_date)
        history["dates"] = [{"trade_date": trade_date, "first": [record], "second": [], "third": [], "removed": [], "live_active_codes": ["002132"]}]
        return history

    def test_september_22_expired_signal_is_quarantined_without_erasing_original(self):
        original = self.history()
        source_copy = copy.deepcopy(original)
        result, report = audit_history_signals(original, self.SESSIONS, generated_at="2026-09-23T12:00:00+08:00")
        self.assertEqual(original, source_copy)
        day = result["dates"][0]
        self.assertEqual(day["first"], [])
        self.assertEqual(day["live_active_codes"], [])
        removed = day["removed"][0]
        self.assertEqual(removed["original_record"], source_copy["dates"][0]["first"][0])
        self.assertEqual(removed["invalid_reason"], "outside_signal_window")
        self.assertTrue(removed["outside_signal_window"])
        self.assertFalse(removed["performance_eligible"])
        self.assertEqual(report["outside_signal_window"], 1)
        self.assertEqual(result["summary"]["selection_count"], 0)
        self.assertEqual(result["summary"]["current_month"]["selection_count"], 0)
        repeated, report = audit_history_signals(result, self.SESSIONS, generated_at="2026-09-23T13:00:00+08:00")
        self.assertEqual(repeated, result)
        self.assertEqual(report["moved_count"], 0)

    def test_four_sessions_inclusive_boundary(self):
        for signal, invalid in [("2026-09-16", True), ("2026-09-17", False)]:
            result, report = audit_history_signals(self.history(bottom_date=signal, base_date="2026-09-21"), self.SESSIONS)
            self.assertEqual(report["moved_count"], int(invalid))
            if not invalid:
                self.assertEqual(result["dates"][0]["first"][0]["signal_integrity"], "window_verified")

    def test_holidays_are_not_guessed_as_weekday_sessions(self):
        result, report = audit_history_signals(self.history("2026-10-08", "2026-09-30", "2026-09-30"), ["2026-09-29", "2026-09-30", "2026-10-08"])
        self.assertEqual(report["moved_count"], 0)
        self.assertEqual(len(result["dates"][0]["first"]), 1)

    def test_fresh_next_session_is_not_removed_but_stale_base_is(self):
        fresh, report = audit_history_signals(self.history("2026-09-10", "2026-09-08"), self.SESSIONS, {"2026-09-10": "2026-09-09"})
        self.assertEqual(report["moved_count"], 0)
        self.assertEqual(len(fresh["dates"][0]["first"]), 1)
        stale, report = audit_history_signals(self.history("2026-09-11", "2026-09-09"), self.SESSIONS, {"2026-09-11": "2026-09-09"})
        self.assertEqual(report["stale_signal_base"], 1)
        self.assertEqual(stale["dates"][0]["removed"][0]["signal_base_date"], "2026-09-09")

    def test_sparse_ledger_proves_expiry_only_with_four_known_later_sessions(self):
        history = self.history()
        for day in ("2026-09-10", "2026-09-14", "2026-09-17"):
            history["dates"].append({"trade_date": day, "first": []})
        result, report = audit_history_signals(history)
        self.assertEqual(report["outside_signal_window"], 1)
        self.assertFalse(result["dates"][0]["first"])

    def test_missing_dates_remain_explicitly_unverified_not_fabricated(self):
        history = self.history()
        history["dates"][0]["first"][0].pop("bottom_date")
        result, report = audit_history_signals(history, self.SESSIONS)
        self.assertEqual(report["moved_count"], 0)
        self.assertEqual(result["dates"][0]["first"][0]["signal_integrity"], "legacy_unverified")
        self.assertNotIn("bottom_date", result["dates"][0]["first"][0])

    def test_unknown_future_and_same_day_signal_cannot_be_new_recommendations(self):
        for bottom_date, reason in [("2026-09-23", "invalid_signal_date"), ("2026-09-22", "unformed_signal"), ("2026-09-07", "outside_signal_window")]:
            row = {"code": "002132", "price": 4.21, "bottom_date": bottom_date}
            result, changed = record_intraday_pools(empty_history(), "2026-09-22", {"first": [row]}, {"002132"}, signal_base_date="2026-09-21", trading_dates=self.SESSIONS)
            self.assertTrue(changed)
            self.assertFalse(result["dates"][0]["first"])
            self.assertEqual(result["dates"][0]["removed"][0]["invalid_reason"], reason)

    def test_new_record_stores_signal_base_and_unknown_quotes_do_not_disappear(self):
        row = {"code": "002132", "price": 4.21, "bottom_date": "2026-09-17"}
        history, _ = record_intraday_pools(empty_history(), "2026-09-22", {"first": [row]}, {"002132"}, signal_base_date="2026-09-21", trading_dates=self.SESSIONS)
        record = history["dates"][0]["first"][0]
        self.assertEqual(record["signal_base_date"], "2026-09-21")
        self.assertEqual(record["signal_integrity"], "window_verified")
        again, _ = record_intraday_pools(history, "2026-09-22", {"first": []}, set(), signal_base_date="2026-09-21", trading_dates=self.SESSIONS)
        self.assertEqual(again["dates"][0]["live_active_codes"], ["002132"])
        self.assertFalse(again["dates"][0]["removed"])

    def test_corrected_then_valid_reentry_uses_new_price_and_first_seen(self):
        history, _ = audit_history_signals(self.history(), self.SESSIONS)
        row = {"code": "002132", "price": 4.5, "bottom_date": "2026-09-21"}
        result, _ = record_intraday_pools(history, "2026-09-22", {"first": [row]}, {"002132"}, "2026-09-22T14:00:00+08:00", signal_base_date="2026-09-21", trading_dates=self.SESSIONS)
        entry = result["dates"][0]["first"][0]
        self.assertEqual(entry["selected_price"], 4.5)
        self.assertEqual(entry["first_seen_at"], "2026-09-22T14:00:00+08:00")
        self.assertEqual(entry["bottom_date"], "2026-09-21")
        self.assertEqual(result["dates"][0]["removed"][0]["original_record"]["selected_price"], 4.2)

    def test_old_false_removal_is_preserved_but_not_called_true_signal_loss(self):
        history = self.history()
        event = {**history["dates"][0]["first"][0], "removal_reason": "可能见底信号消失", "removed_at": "2026-09-22T10:00:00+08:00"}
        history["dates"][0]["removed"] = [event]
        result, report = audit_history_signals(history, self.SESSIONS)
        corrected = result["dates"][0]["removed"][0]
        self.assertTrue(corrected["invalid_signal"])
        self.assertEqual(corrected["original_record"], event)
        self.assertEqual(report["reclassified_removals"], 1)
        self.assertEqual(result["summary"]["removed_count"], 0)
        self.assertEqual(result["summary"]["invalid_signal_count"], 1)

    def test_defensive_summary_excludes_invalid_and_missing_returns(self):
        history = self.history(bottom_date="2026-09-17")
        rows = history["dates"][0]["first"]
        rows.extend([{**rows[0], "invalid_signal": True}, {**rows[0], "performance_eligible": False}])
        rows.extend({**rows[0], "return_pct": invalid} for invalid in (None, "", False, float("nan"), float("inf")))
        summary = summarize(history["dates"], "2026-09-22")
        self.assertEqual(summary["selection_count"], 6)
        self.assertEqual(summary["evaluated_count"], 1)
        self.assertEqual(summary["success_rate_pct"], 100)


if __name__ == "__main__":
    unittest.main()
