import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from intraday import build_live_payload, build_live_pools, evaluate_live_seed
from signal_freshness import (
    seed_transition_allowed, session_distance, signal_within_window,
)


CFG = {
    "bottom_lookback_days": 4, "cross_lookback_days": 8,
    "limit_up_lookback_days": 42, "yellow_consecutive_days": 1,
    "line_gap_max_abs": 0.5,
}
SESSIONS = [
    "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
    "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16",
    "2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22",
    "2026-09-23",
]


def seed(code="002132", base="2026-09-21", bottom="2026-09-21"):
    return {
        "code": code, "name": "测试股票", "market": 0, "eligible": True,
        "base_date": base, "bottom_date": bottom, "bottom_age": 0,
        "bottom_ok": True, "bottom_price": 4.18, "previous_close": 4.2,
        "min_close_15": 4.18, "typical_13": [4.3] * 13,
        "next_limit_price": 4.62, "limit_up_age": -1, "cross_age": -1,
        "dragon_value": 4.1, "tiger_value": 4.11, "yellow_line_value": 4.54,
        "prior_three_gap_abs": [0.01] * 3,
        "line_coefficients": {
            "dragon": [4.1, 0, 0], "tiger": [4.11, 0, 0],
            "previous_dragon": [4.1, 0, 0], "previous_tiger": [4.11, 0, 0],
            "dragon_tail": [[4.1, 0, 0]] * 6,
            "tiger_tail": [[4.11, 0, 0]] * 6,
            "yellow_tail": [[4.54, 0, 0]] * 6,
        },
        "body_low_tail": [4.18] * 5, "body_low_tail_dates": [base] * 5,
        "cross_tail_dates": [base] * 4,
    }


def quote(code="002132", day="2026-09-22", time="10:00:00"):
    return {
        "code": code, "name": "测试股票", "market": 0, "price": 4.21,
        "open": 4.31, "high": 4.33, "low": 4.18, "pre_close": 4.3,
        "change_pct": -2.09, "server_time": f"{day}T{time}+08:00",
    }


class SessionFreshnessTests(unittest.TestCase):
    def test_same_day_and_immediately_next_weekday_are_safe(self):
        self.assertTrue(seed_transition_allowed("2026-09-21", "2026-09-21"))
        self.assertTrue(seed_transition_allowed("2026-09-21", "2026-09-22"))
        self.assertTrue(seed_transition_allowed("2026-09-18", "2026-09-21"))
        self.assertFalse(seed_transition_allowed("2026-09-18", "2026-09-22"))

    def test_long_holiday_requires_real_sessions(self):
        sessions = ["2026-04-29", "2026-04-30", "2026-05-06"]
        self.assertFalse(seed_transition_allowed("2026-04-30", "2026-05-06"))
        self.assertTrue(seed_transition_allowed("2026-04-30", "2026-05-06", sessions))
        self.assertFalse(seed_transition_allowed("2026-04-29", "2026-05-06", sessions))
        self.assertFalse(seed_transition_allowed("2026-04-30", "2026-05-05", sessions))

    def test_signal_window_counts_actual_sessions_not_natural_days(self):
        self.assertTrue(signal_within_window("2026-09-18", "2026-09-23", 4, SESSIONS))
        self.assertFalse(signal_within_window("2026-09-17", "2026-09-23", 4, SESSIONS))
        self.assertFalse(signal_within_window("2026-09-07", "2026-09-22", 4, SESSIONS))
        self.assertEqual(session_distance("2026-09-07", "2026-09-22", SESSIONS), 11)

    def test_invalid_and_future_dates_fail_closed(self):
        for bad in ("", None, "2026-09-99", "20260921", "2026-9-21"):
            self.assertFalse(seed_transition_allowed(bad, "2026-09-22"))
            self.assertFalse(signal_within_window(bad, "2026-09-22", 4))
        self.assertFalse(seed_transition_allowed("2026-09-23", "2026-09-22"))
        self.assertFalse(signal_within_window("2026-09-23", "2026-09-22", 4))


class LiveSeedFreshnessTests(unittest.TestCase):
    def test_002132_stale_september_ninth_seed_cannot_select_on_22nd(self):
        cached = seed(base="2026-09-09", bottom="2026-09-07")
        cached.update(
            bottom_age=2, zig16_state=2, zig16_candidate_value=4.18,
            zig16_candidate_age=2, zig16_candidate_date="2026-09-07",
            zig16_candidate_signal_ok=True,
        )
        self.assertIsNone(evaluate_live_seed(cached, quote(), CFG, "2026-09-09"))
        self.assertIsNone(evaluate_live_seed(
            cached, quote(), CFG, "2026-09-09", trading_sessions=SESSIONS,
        ))

    def test_valid_next_session_and_same_day_baseline(self):
        next_day = evaluate_live_seed(seed(), quote(), CFG, "2026-09-21")
        self.assertTrue(next_day["bottom_ok"])
        self.assertEqual(next_day["tier"], "first")
        same_day = evaluate_live_seed(
            seed(base="2026-09-22"), quote(), CFG, "2026-09-22",
        )
        self.assertTrue(same_day["bottom_ok"])

    def test_real_holiday_calendar_allows_one_bar_reuse(self):
        cached = seed(base="2026-04-30", bottom="2026-04-29")
        sessions = ["2026-04-29", "2026-04-30", "2026-05-06"]
        self.assertIsNone(evaluate_live_seed(cached, quote(day="2026-05-06"), CFG, "2026-04-30"))
        self.assertTrue(evaluate_live_seed(
            cached, quote(day="2026-05-06"), CFG, "2026-04-30",
            trading_sessions=sessions,
        )["bottom_ok"])

    def test_signal_actual_date_overrides_bad_cached_age(self):
        for base in ("2026-09-21", "2026-09-22"):
            result = evaluate_live_seed(
                seed(base=base, bottom="2026-09-07"), quote(), CFG, base,
                trading_sessions=SESSIONS,
            )
            self.assertFalse(result["bottom_ok"])
            self.assertEqual(result["bottom_date"], "")
            self.assertEqual(result["tier"], "")

    def test_stopped_stock_old_quote_is_not_today_baseline(self):
        self.assertIsNone(evaluate_live_seed(
            seed(), quote(day="2026-09-21"), CFG, "2026-09-21",
            expected_trade_date="2026-09-22",
        ))

    def test_invalid_dates_and_older_quotes_cannot_use_baseline(self):
        for day in ("not-a-date", "2026-09-20", ""):
            self.assertIsNone(evaluate_live_seed(seed(), quote(day=day), CFG, "2026-09-21"))

    def test_old_stock_seed_is_rejected_even_when_global_base_current(self):
        self.assertIsNone(evaluate_live_seed(
            seed(base="2026-09-09"), quote(), CFG, "2026-09-21",
        ))

    def test_all_stale_seed_pools_unavailable(self):
        pools = build_live_pools({
            "trade_date": "2026-09-09", "config": CFG,
            "live_universe": [seed(base="2026-09-09")],
        }, {"002132": quote()})
        self.assertFalse(pools["available"])
        self.assertEqual(pools["first"], [])


class PayloadFreshnessTests(unittest.TestCase):
    def build(self, seeds, quotes, base="2026-09-21"):
        payload = {"trade_date": base, "config": CFG, "live_universe": seeds}
        with patch("intraday.fetch_quotes", return_value=(quotes, "fixture", "local")), \
                patch("intraday.load_history", return_value={"dates": []}), \
                patch("intraday.build_live_tracking", return_value={}), \
                patch("intraday.record_intraday_pools", return_value=({"dates": []}, True)) as record:
            result = build_live_payload(
                payload, datetime(2026, 9, 22, 10, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
                trading_sessions=SESSIONS[:-1], reference_trade_date="2026-09-22",
            )
        return result, record

    def test_old_base_blocks_selection_but_keeps_fresh_quote_status(self):
        result, record = self.build([seed(base="2026-09-09")], {"002132": quote()}, "2026-09-09")
        self.assertEqual(result["selection_status"], "blocked")
        self.assertTrue(result["strategy_is_stale"])
        self.assertFalse(result["is_stale"])
        self.assertEqual(result["signal_base_date"], "2026-09-09")
        self.assertFalse(result["live_pools"]["available"])
        self.assertEqual(result["quote_count"], 1)
        record.assert_not_called()

    def test_missing_or_stale_quotes_cannot_create_removals(self):
        for quotes in ({}, {"002132": quote(time="09:30:00")}, {"002132": quote(day="2026-09-21")}):
            result, record = self.build([seed()], quotes)
            self.assertEqual(result["selection_status"], "blocked")
            self.assertTrue(result["is_stale"])
            record.assert_not_called()

    def test_partial_quotes_update_valid_stocks_and_exclude_unknown_observations(self):
        result, record = self.build([seed(), seed("000001")], {"002132": quote()})
        self.assertEqual(result["selection_status"], "partial")
        self.assertTrue(result["live_pools"]["available"])
        self.assertEqual(record.call_args.args[3], ["002132"])
        self.assertEqual(record.call_args.kwargs["signal_base_date"], "2026-09-21")
        self.assertEqual(record.call_args.kwargs["trading_dates"], SESSIONS[:-1])

    def test_all_valid_quotes_are_ready(self):
        result, record = self.build([seed()], {"002132": quote()})
        self.assertEqual(result["selection_status"], "ready")
        self.assertFalse(result["strategy_is_stale"])
        self.assertEqual(result["evaluated_count"], 1)
        self.assertEqual(result["quote_timestamp"], "2026-09-22T10:00:00+08:00")
        record.assert_called_once()

    def test_old_stock_seed_not_marked_as_observed_during_partial_update(self):
        result, record = self.build(
            [seed(), seed("000001", base="2026-09-09")],
            {"002132": quote(), "000001": quote("000001")},
        )
        self.assertEqual(result["selection_status"], "partial")
        self.assertEqual(record.call_args.args[3], ["002132"])

    def test_morning_refresh_of_previous_close_never_backfills_yesterday_selection(self):
        payload = {
            "trade_date": "2026-09-22", "config": CFG,
            "live_universe": [seed(base="2026-09-22", bottom="2026-09-21")],
        }
        with patch("intraday.fetch_quotes", return_value=(
            {"002132": quote(time="15:00:00")}, "fixture", "local",
        )), patch("intraday.load_history", return_value={"dates": []}), \
                patch("intraday.build_live_tracking", return_value={}), \
                patch("intraday.record_intraday_pools") as record:
            result = build_live_payload(
                payload, datetime(2026, 9, 23, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                trading_sessions=SESSIONS[:-1], reference_trade_date="2026-09-22",
            )
        # Last-close data may be displayed, but it was not observed yesterday.
        self.assertEqual(result["live_trade_date"], "2026-09-22")
        self.assertTrue(result["live_pools"]["available"])
        self.assertFalse(result["_history_changed"])
        self.assertEqual(result["history"]["dates"], [])
        record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
