import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from intraday import build_live_payload, fetch_quotes, fetch_tencent_quotes, parse_tencent_quotes


class QuoteResilienceTests(unittest.TestCase):
    def test_one_failed_quote_batch_preserves_other_batches(self):
        targets = [{"code": str(i)} for i in range(81)]
        def fetch_batch(group):
            if group[0]["code"] == "80":
                raise TimeoutError("one batch offline")
            return {item["code"]: {"price": 10} for item in group}
        with patch("intraday.fetch_tencent_quote_group", side_effect=fetch_batch):
            quotes = fetch_tencent_quotes(targets)
        self.assertEqual(len(quotes), 80)
        self.assertNotIn("80", quotes)

    def test_current_st_name_overrides_old_seed_name(self):
        fields = ["0"] * 40
        fields[1], fields[2], fields[30] = "*ST新名", "000001", "20260923110000"
        raw = 'v_sz000001="' + "~".join(fields) + '";'
        quotes = parse_tencent_quotes(raw, [{"code": "000001", "market": 0, "name": "旧普通名称"}])
        self.assertEqual(quotes["000001"]["name"], "*ST新名")

    def test_primary_partial_quotes_survive_fallback_failure(self):
        targets = [{"code": "000001"}, {"code": "000002"}]
        good = {"000001": {"price": 10}}
        with patch("intraday.fetch_tencent_quotes", return_value=good), \
             patch("intraday.fetch_xmtdx_quotes", side_effect=RuntimeError("offline")) as fallback:
            quotes, source, _ = fetch_quotes(targets)
        fallback.assert_called_once_with([targets[1]])
        self.assertEqual(quotes, good)
        self.assertEqual(source, "tencent_partial")

    def test_supplemental_quotes_do_not_replace_primary_current_data(self):
        targets = [{"code": "000001"}, {"code": "000002"}]
        with patch("intraday.fetch_tencent_quotes", return_value={"000001": {"price": 10}}), \
             patch("intraday.fetch_xmtdx_quotes", return_value=({"000002": {"price": 20}}, "host")):
            quotes, _, _ = fetch_quotes(targets)
        self.assertEqual(quotes, {"000001": {"price": 10}, "000002": {"price": 20}})

    def test_total_quote_outage_publishes_pause_without_history_transitions(self):
        payload = {"trade_date": "2026-09-22", "live_universe": [], "config": {}}
        with patch("intraday.fetch_quotes", side_effect=RuntimeError("all providers offline")), \
             patch("intraday.load_history", return_value={"dates": []}), \
             patch("intraday.build_live_tracking", return_value={}), \
             patch("intraday.record_intraday_pools") as record:
            live = build_live_payload(payload, datetime(2026, 9, 23, 11, tzinfo=ZoneInfo("Asia/Shanghai")),
                                      trading_sessions=["2026-09-22", "2026-09-23"])
        self.assertEqual(live["selection_status"], "blocked")
        self.assertFalse(live["live_pools"]["available"])
        self.assertIn("all providers offline", live["quote_error"])
        self.assertFalse(live["_history_changed"])
        record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
