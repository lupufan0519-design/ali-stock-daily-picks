import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import daily_market_data as daily
import screener


def payload(rows=None, *, key="qfqday", symbol="sz002132", quote_date="20260922150000", volume="123"):
    quote = [""] * 50
    quote[1], quote[6], quote[30] = "恒星科技", volume, quote_date
    return {"code": 0, "data": {symbol: {
        key: rows or [["2026-09-21", "4.34", "4.30", "4.34", "4.27", "100"],
                      ["2026-09-22", "4.31", "4.21", "4.33", "4.18", "123"]],
        "qt": {symbol: quote},
    }}}


class DailyPricesTests(unittest.TestCase):
    def test_historical_suspension_requires_full_day_coverage(self):
        row = {"SECURITY_CODE": "002860", "SECUCODE": "002860.SZ", "SECURITY_TYPE_CODE": "058001001",
               "SUSPEND_START_TIME": "2026-09-22 09:30:00", "SUSPEND_END_TIME": "2026-10-13 15:00:00",
               "SUSPEND_EXPIRE": "连续停牌", "PREDICT_RESUME_DATE": "2026-10-14 00:00:00"}
        self.assertIn("002860", daily.parse_full_day_suspensions([row], "2026-09-22"))
        self.assertEqual(daily.parse_full_day_suspensions([row], "2026-09-21"), {})
        self.assertEqual(daily.parse_full_day_suspensions([row], "2026-10-14"), {})
        row.update(SUSPEND_START_TIME="2026-09-22 13:20:00", SUSPEND_END_TIME="2026-09-22 13:30:00")
        self.assertEqual(daily.parse_full_day_suspensions([row], "2026-09-22"), {})

    def test_prelisting_requires_explicit_status_or_future_listing_date(self):
        row = {"SECURITY_CODE": "001246", "SECUCODE": "001246.SZ", "LISTING_DATE": None,
               "CONTINUOUS_1WORD_NUM": "待上市"}
        self.assertIn("001246", daily.parse_prelisting_stocks([row], "2026-09-22"))
        row["CONTINUOUS_1WORD_NUM"] = None
        self.assertEqual(daily.parse_prelisting_stocks([row], "2026-09-22"), {})
        row["LISTING_DATE"] = "2026-09-23 00:00:00"
        self.assertIn("001246", daily.parse_prelisting_stocks([row], "2026-09-22"))
        self.assertEqual(daily.parse_prelisting_stocks([row], "2026-09-23"), {})

    def test_qfq_ohlc_mapping_is_not_stock_kline_column_order(self):
        data = daily.parse_daily_payload(payload(), "sz002132")
        self.assertEqual(data["bars"][-1], dict(date="2026-09-22", open=4.31, close=4.21,
                                              high=4.33, low=4.18, volume=123.0, amount=0.0))
        self.assertEqual(data["adjustment"], "qfq")
        self.assertEqual(data["response_series"], "qfqday")
        self.assertFalse(data["amount_available"])

    def test_qfq_endpoint_unadjusted_series_key_is_retained(self):
        data = daily.parse_daily_payload(payload(key="day"), "sz002132")
        self.assertEqual(data["response_series"], "day")
        self.assertIn("qfq", data["adjustment_evidence"])

    def test_future_candle_does_not_enter_asof_evaluation(self):
        data = daily.parse_daily_payload(payload(), "sz002132", through_date="2026-09-21")
        self.assertEqual(data["bars_end_date"], "2026-09-21")
        self.assertEqual(len(data["bars"]), 1)

    def test_wrong_symbol_and_empty_or_bad_price_are_rejected(self):
        with self.assertRaises(daily.DailyDataError):
            daily.parse_daily_payload(payload(), "sh600519")
        for value in ("nan", "inf", "-1", None, True):
            p = payload()
            p["data"]["sz002132"]["qfqday"][-1][1] = value
            with self.subTest(value=value), self.assertRaises((daily.DailyDataError, ValueError)):
                daily.parse_daily_payload(p, "sz002132")

    def test_duplicate_unordered_and_inconsistent_high_low_rejected(self):
        for rows in (
            [["2026-09-22", "4", "4", "4", "4", "1"]] * 2,
            [["2026-09-22", "4", "4", "4", "4", "1"], ["2026-09-21", "4", "4", "4", "4", "1"]],
            [["2026-09-22", "4", "4", "3", "4", "1"]],
        ):
            with self.assertRaises(daily.DailyDataError):
                daily.parse_daily_payload(payload(rows), "sz002132")

    def test_freshness_never_promotes_old_candles_to_current(self):
        data = daily.parse_daily_payload(payload(), "sz002132")
        self.assertTrue(daily.validate_freshness(data, "2026-09-22"))
        with self.assertRaises(daily.StaleDailyData):
            daily.validate_freshness(data, "2026-09-23")

    def test_only_current_zero_volume_quote_confirms_suspension(self):
        data = daily.parse_daily_payload(payload(quote_date="20260923103000", volume="0"), "sz002132")
        self.assertFalse(daily.validate_freshness(data, "2026-09-23"))
        self.assertTrue(data["suspended"])
        data["quote_date"] = "2026-09-22"
        with self.assertRaises(daily.StaleDailyData):
            daily.validate_freshness(data, "2026-09-23")

    def test_reference_sessions_are_real_market_dates_not_weekdays(self):
        data = daily.parse_daily_payload(payload(symbol="sh000001", key="day"), "sh000001")
        with patch.object(daily, "fetch_daily_prices", return_value=data):
            self.assertEqual(daily.fetch_reference_sessions("2026-09-21"), ["2026-09-21"])
            self.assertEqual(daily.fetch_market_sessions()["latest_session"], "2026-09-22")
        data["quote_date"] = "2026-09-23"
        with patch.object(daily, "fetch_daily_prices", return_value=data), self.assertRaises(daily.StaleDailyData):
            daily.fetch_market_sessions()

    def test_request_explicitly_asks_qfq_and_bounds_retries(self):
        with patch.object(daily, "_get_json", return_value=payload()) as getter:
            daily.fetch_daily_prices("sz002132", 180, through_date="2026-09-22")
        self.assertIn("qfq", getter.call_args.args[0])
        self.assertIn("2026-09-22", getter.call_args.args[0])
        with patch.object(daily, "_get_json", side_effect=TimeoutError("offline")) as getter, \
             patch.object(daily.time, "sleep"), self.assertRaisesRegex(daily.DailyDataError, "TimeoutError: offline"):
            daily.fetch_daily_prices("sz002132", attempts=2)
        self.assertEqual(getter.call_count, 2)
        self.assertIn("proxy.finance.qq.com", getter.call_args_list[0].args[0])
        self.assertIn("web.ifzq.gtimg.cn", getter.call_args_list[1].args[0])

    def test_reconstruction_cache_rejects_intraday_and_wrong_adjustment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = daily.parse_daily_payload(payload(), "sz002132")
            data["fetched_at"] = "2026-09-22T10:30:00+08:00"
            target = daily.save_daily_cache(data, "2026-09-22", root)
            self.assertIsNone(daily.load_daily_cache("sz002132", "2026-09-22", root))
            data["fetched_at"] = "2026-09-22T15:10:00+08:00"
            daily.save_daily_cache(data, "2026-09-22", root)
            self.assertEqual(daily.load_daily_cache("sz002132", "2026-09-22", root)["bars_end_date"], "2026-09-22")
            data["adjustment"] = "raw"
            daily.save_daily_cache(data, "2026-09-22", root)
            self.assertIsNone(daily.load_daily_cache("sz002132", "2026-09-22", root))
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["adjustment"], "raw")


class ScreenerHttpRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"_expected_trade_date": "2026-09-22", "workers": 5, "history_bars": 180}
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        output_patch = patch.object(screener, "OUTPUT_DIR", Path(folder.name))
        output_patch.start()
        self.addCleanup(output_patch.stop)
        for name in ("fetch_nontrading_evidence", "fetch_prelisting_evidence"):
            source_patch = patch.object(daily, name, return_value={"stocks": {}})
            source_patch.start()
            self.addCleanup(source_patch.stop)

    def test_confirmed_nontrading_records_do_not_request_or_evaluate_old_prices(self):
        self.cfg["_confirmed_suspensions"] = {"002860": {"SECURITY_NAME_ABBR": "星帅尔"}}
        self.cfg["_confirmed_prelisting"] = {"001246": {"CONTINUOUS_1WORD_NUM": "待上市"}}
        stocks = [screener.Stock(0, "002860", "星帅尔"), screener.Stock(0, "001246", "力勤资源")]
        with patch.object(daily, "fetch_daily_prices") as fetch, patch.object(screener, "evaluate") as evaluate:
            results, errors = screener.scan_http_daily(stocks, self.cfg)
        fetch.assert_not_called()
        evaluate.assert_not_called()
        self.assertEqual((results, errors), ([], []))
        self.assertEqual(self.cfg["_excluded_reason_counts"], {"suspended_confirmed": 1, "not_yet_listed": 1})

    def test_source_outage_fast_fails_after_initial_12_not_all_5000(self):
        universe = [screener.Stock(0, f"{n:06d}", "示例") for n in range(50)]
        with patch.object(daily, "fetch_daily_prices", side_effect=daily.DailyDataError("network unavailable")) as getter:
            results, errors = screener.scan_http_daily(universe, self.cfg)
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 50)
        self.assertEqual(getter.call_count, 12)
        self.assertIn("initial HTTP probe batch failed", errors[-1])

    def test_renamed_st_name_uses_current_quote_and_bad_bar_not_evaluated(self):
        data = daily.parse_daily_payload(payload(), "sz002132")
        data["quote_name"] = "*ST示例"
        item = SimpleNamespace(live_seed={})
        with patch.object(daily, "fetch_daily_prices", return_value=data), \
             patch.object(daily, "save_daily_cache"), patch.object(screener, "evaluate", return_value=item) as evaluate:
            results, errors = screener.scan_http_daily([screener.Stock(0, "002132", "旧公司名")], self.cfg)
        self.assertEqual(errors, [])
        evaluate.assert_not_called()
        self.assertEqual(results, [])
        self.assertEqual(self.cfg["_excluded_reason_counts"]["st_excluded"], 1)
        data["quote_name"] = "示例公司"
        data["bars_end_date"] = "2026-09-09"
        with patch.object(daily, "fetch_daily_prices", return_value=data), patch.object(screener, "evaluate") as evaluate:
            results, errors = screener.scan_http_daily([screener.Stock(0, "002132", "旧公司名")], self.cfg)
        evaluate.assert_not_called()
        self.assertEqual(results, [])
        self.assertIn("StaleDailyData", errors[0])

    def test_scan_routes_unhealthy_tdx_directly_to_http(self):
        cfg = {"workers": 5}
        reference = {"latest_session": "2026-09-22", "sessions": ["2026-09-21", "2026-09-22"]}
        universe = [screener.Stock(0, "002132", "恒星科技")]
        with patch("xmtdx.TdxClient.ping_all", return_value=[("example", 0.1)]), \
             patch.object(daily, "fetch_market_sessions", return_value=reference), \
             patch.object(screener, "reliable_universe", return_value=universe), \
             patch.object(screener, "probe_daily_hosts", return_value=[]), \
             patch.object(screener, "scan_http_daily", return_value=([], [])) as http, \
             patch.object(screener, "fetch_chunk") as tdx:
            result = screener.scan_market(cfg)
        tdx.assert_not_called()
        self.assertEqual(http.call_args.args[1]["_expected_trade_date"], "2026-09-22")
        self.assertEqual(result, ([], [], 1))
        self.assertEqual(cfg["_expected_trade_date"], "2026-09-22")
        self.assertEqual(cfg["_trading_dates"], reference["sessions"])
        self.assertEqual(cfg["_daily_scan_diagnostics"]["scanned"], 1)

    def test_explicit_asof_cannot_silently_use_an_older_reference_day(self):
        reference = {"latest_session": "2026-09-21", "sessions": ["2026-09-21"]}
        cfg = {"workers": 5, "_as_of_date": "2026-09-22"}
        with patch.object(daily, "fetch_market_sessions", return_value=reference), \
             self.assertRaisesRegex(RuntimeError, "未覆盖明确请求日期"):
            screener.scan_market(cfg)
        self.assertEqual(cfg["_daily_scan_diagnostics"]["error_count"], 1)
        self.assertEqual(cfg["_daily_scan_diagnostics"]["requested_trade_date"], "2026-09-22")

    def test_suspended_stock_four_candles_cannot_extend_four_market_days(self):
        item = SimpleNamespace(
            date="2026-09-22", bottom_date="2026-09-14", bottom_ok=True,
            bottom_price=4.1, tier="first", selected=True,
            cross_ok=False, limit_up_ok=False, yellow_ok=False, observation_yellow_ok=False,
            matched_count=1, observation_matched_count=1,
            live_seed={"bottom_date": "2026-09-14", "bottom_ok": True, "bottom_age": 2,
                       "zig16_candidate_date": "2026-09-14", "zig16_candidate_signal_ok": True},
        )
        cfg = {"bottom_lookback_days": 4, "_trading_dates": [
            "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
            "2026-09-21", "2026-09-22",
        ]}
        self.assertEqual(screener.audit_evaluation_windows([item], cfg), 1)
        self.assertFalse(item.bottom_ok)
        self.assertEqual(item.bottom_date, "")
        self.assertFalse(item.selected)
        self.assertEqual(item.tier, "")
        self.assertEqual(item.live_seed["bottom_age"], -1)
        self.assertFalse(item.live_seed["zig16_candidate_signal_ok"])

    def test_holiday_sessions_preserve_a_valid_four_session_signal(self):
        item = SimpleNamespace(
            date="2026-10-12", bottom_date="2026-09-30", bottom_ok=True,
            live_seed={"bottom_age": 1},
        )
        cfg = {"bottom_lookback_days": 4, "_trading_dates": [
            "2026-09-30", "2026-10-08", "2026-10-09", "2026-10-12",
        ]}
        self.assertEqual(screener.audit_evaluation_windows([item], cfg), 0)
        self.assertEqual(item.live_seed["bottom_age"], 3)


if __name__ == "__main__":
    unittest.main()
