import copy
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import company_metadata
import financial_metrics as fm


CODE = "600001"
AS_OF = "2026-09-20"
NOW = datetime(2026, 9, 20, 4, 0, tzinfo=timezone.utc)


def source_row(**overrides):
    row = {
        "SECURITY_CODE": CODE,
        "REPORT_DATE": "2026-06-30 00:00:00",
        "REPORT_TYPE": "中报",
        "NOTICE_DATE": "2026-08-20 00:00:00",
        "UPDATE_DATE": "2026-08-20 00:00:00",
        "TOTALOPERATEREVETZ": "12.5",
        "PARENTNETPROFITTZ": "8.25",
        "KCFJCXSYJLRTZ": "-3.75",
        "TOTALOPERATEREVE": "1200",
        "PARENTNETPROFIT": "200",
        "KCFJCXSYJLR": "180",
        "NETCASH_OPERATE_PK": "300",
    }
    row.update(overrides)
    return row


def payload(*rows):
    return {"success": True, "result": {"data": list(rows)}}


def financials(**overrides):
    result = fm.parse_financials(payload(source_row()), CODE, 1, AS_OF)
    result["as_of"] = AS_OF
    result.update(overrides)
    return result


class FinancialParsingTests(unittest.TestCase):
    def test_latest_disclosed_report_keeps_one_year_to_date_period(self):
        older = source_row(
            REPORT_DATE="2026-03-31", NOTICE_DATE="2026-04-20",
            TOTALOPERATEREVETZ=91, PARENTNETPROFITTZ=92,
            KCFJCXSYJLRTZ=93, PARENTNETPROFIT=10, NETCASH_OPERATE_PK=900,
        )
        result = fm.parse_financials(payload(source_row(), older), CODE, 1, AS_OF)
        self.assertEqual(result["report_date"], "2026-06-30")
        self.assertEqual(result["report_label"], "2026年中报")
        self.assertEqual(result["notice_date"], "2026-08-20")
        self.assertEqual(result["basis"], "year_to_date")
        self.assertEqual(result["revenue_yoy_pct"], 12.5)
        self.assertEqual(result["parent_profit_yoy_pct"], 8.25)
        self.assertEqual(result["adjusted_profit_yoy_pct"], -3.75)
        self.assertEqual(result["operating_cash_to_parent_profit"], 1.5)

    def test_partial_newer_report_does_not_borrow_older_values(self):
        older = source_row(REPORT_DATE="2026-03-31", NOTICE_DATE="2026-04-20")
        newer = source_row(
            TOTALOPERATEREVETZ=None, PARENTNETPROFITTZ="",
            KCFJCXSYJLRTZ="--", NETCASH_OPERATE_PK=None,
        )
        result = fm.parse_financials(payload(older, newer), CODE, 1, AS_OF)
        self.assertEqual(result["report_date"], "2026-06-30")
        for key in ("revenue_yoy_pct", "parent_profit_yoy_pct",
                    "adjusted_profit_yoy_pct", "operating_cash_to_parent_profit"):
            self.assertIsNone(result[key], key)
        self.assertEqual(result["parent_profit"], 200)
        self.assertEqual(result["cash_ratio_status"], "missing")

    def test_latest_update_of_same_period_is_selected_intact(self):
        initial = source_row(UPDATE_DATE="2026-08-20", TOTALOPERATEREVETZ=19)
        amended = source_row(UPDATE_DATE="2026-08-25", TOTALOPERATEREVETZ=20)
        result = fm.parse_financials(payload(amended, initial), CODE, 1, AS_OF)
        self.assertEqual(result["revenue_yoy_pct"], 20)

    def test_wrong_stock_future_notice_and_future_report_are_excluded(self):
        rows = [
            source_row(),
            source_row(SECURITY_CODE="600002", REPORT_DATE="2026-09-01",
                       TOTALOPERATEREVETZ=901),
            source_row(REPORT_DATE="2026-09-01", NOTICE_DATE="2026-09-21",
                       TOTALOPERATEREVETZ=902),
            source_row(REPORT_DATE="2026-09-30", NOTICE_DATE="2026-09-19",
                       TOTALOPERATEREVETZ=903),
            source_row(REPORT_DATE="bad-date", TOTALOPERATEREVETZ=904),
            source_row(NOTICE_DATE=None, TOTALOPERATEREVETZ=905),
        ]
        result = fm.parse_financials(payload(*rows), CODE, 1, AS_OF)
        self.assertEqual(result["revenue_yoy_pct"], 12.5)
        self.assertEqual(result["report_date"], "2026-06-30")

    def test_notice_on_cutoff_date_is_available(self):
        row = source_row(NOTICE_DATE=AS_OF)
        result = fm.parse_financials(payload(row), CODE, 1, AS_OF)
        self.assertEqual(result["notice_date"], AS_OF)

    def test_blank_boolean_and_nonfinite_numbers_are_missing_not_zero(self):
        values = [None, "", " ", "--", False, True, "NaN", "Infinity",
                  "-Infinity", float("nan"), float("inf"), float("-inf")]
        for value in values:
            with self.subTest(value=repr(value)):
                row = source_row(
                    TOTALOPERATEREVETZ=value, PARENTNETPROFITTZ=value,
                    KCFJCXSYJLRTZ=value, PARENTNETPROFIT=value,
                    NETCASH_OPERATE_PK=value,
                )
                result = fm.parse_financials(payload(row), CODE, 1, AS_OF)
                for key in ("revenue_yoy_pct", "parent_profit_yoy_pct",
                            "adjusted_profit_yoy_pct", "parent_profit",
                            "operating_cash_flow", "operating_cash_to_parent_profit"):
                    self.assertIsNone(result[key], key)
                self.assertEqual(result["cash_ratio_status"], "missing")

    def test_zero_growth_and_zero_cash_are_valid_numbers(self):
        row = source_row(TOTALOPERATEREVETZ=0, PARENTNETPROFITTZ="0",
                         KCFJCXSYJLRTZ="0.0", NETCASH_OPERATE_PK=0)
        result = fm.parse_financials(payload(row), CODE, 1, AS_OF)
        for key in ("revenue_yoy_pct", "parent_profit_yoy_pct",
                    "adjusted_profit_yoy_pct", "operating_cash_to_parent_profit"):
            self.assertEqual(result[key], 0, key)
        self.assertEqual(result["cash_ratio_status"], "ok")

    def test_zero_and_negative_parent_profit_make_ratio_unavailable(self):
        for denominator in (0, "0", -100, "-0.25"):
            with self.subTest(denominator=denominator):
                result = fm.parse_financials(
                    payload(source_row(PARENTNETPROFIT=denominator)), CODE, 1, AS_OF
                )
                self.assertIsNone(result["operating_cash_to_parent_profit"])
                self.assertEqual(result["cash_ratio_status"], "nonpositive_profit")
                self.assertEqual(result["parent_profit"], float(denominator))

    def test_negative_operating_cash_ratio_is_preserved(self):
        row = source_row(NETCASH_OPERATE_PK=-50)
        result = fm.parse_financials(payload(row), CODE, 1, AS_OF)
        self.assertEqual(result["operating_cash_to_parent_profit"], -0.25)
        self.assertEqual(result["cash_ratio_status"], "ok")

    def test_no_disclosed_report_and_failed_endpoint_raise(self):
        responses = [
            payload(), {"success": False, "message": "endpoint unavailable"},
            payload(source_row(NOTICE_DATE="2026-09-21")),
            payload(source_row(SECURITY_CODE="600002")),
        ]
        for response in responses:
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    fm.parse_financials(response, CODE, 1, AS_OF)

    @patch("financial_metrics._get_json")
    def test_fetch_requests_same_report_fields_and_disclosure_cutoff(self, get_json):
        get_json.return_value = payload(source_row())
        result = fm.fetch_financials(CODE, 1, AS_OF)
        get_json.assert_called_once()
        query = parse_qs(urlsplit(get_json.call_args.args[0]).query)
        self.assertEqual(query["reportName"], ["RPT_F10_FINANCE_MAINFINADATA"])
        self.assertIn(f'(SECURITY_CODE="{CODE}")', query["filter"][0])
        self.assertIn(f"(REPORT_DATE<='{AS_OF}')", query["filter"][0])
        self.assertIn(f"(NOTICE_DATE<='{AS_OF}')", query["filter"][0])
        self.assertTrue(set(source_row()).issubset(query["columns"][0].split(",")))
        self.assertEqual(result["operating_cash_to_parent_profit"], 1.5)
        self.assertIn("code=SH600001", result["source_url"])

    @patch("financial_metrics._get_json")
    def test_invalid_query_never_calls_endpoint(self, get_json):
        for code, cutoff in (("60001", AS_OF), ("bad", AS_OF), (CODE, "2026-02-30")):
            with self.subTest(code=code, cutoff=cutoff):
                with self.assertRaises(ValueError):
                    fm.fetch_financials(code, 1, cutoff)
        get_json.assert_not_called()


class FinancialEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache_path = Path(self.temporary.name) / "company_metadata.json"

    def save_entry(self, **entry):
        company_metadata._save_cache(
            self.cache_path, {"schema_version": 2, "stocks": {CODE: entry}}
        )

    def cached_entry(self):
        return company_metadata._load_cache(self.cache_path)["stocks"][CODE]

    def enrich(self, pools=None, now=NOW, as_of=AS_OF):
        pools = {"first": [{"code": CODE, "market": 1}]} if pools is None else pools
        errors = fm.enrich_financial_pools(
            pools, max_workers=1, cache_path=self.cache_path, as_of=as_of, now=now
        )
        return pools, errors

    @patch("financial_metrics.fetch_financials")
    def test_cache_is_fresh_before_twelve_hours_and_refreshes_at_boundary(self, fetch):
        fetched_at = NOW - timedelta(hours=12)
        self.save_entry(financials=financials(fetched_at=fetched_at.isoformat()))
        pools, errors = self.enrich(now=NOW - timedelta(seconds=1))
        fetch.assert_not_called()
        self.assertEqual(errors, [])
        self.assertFalse(pools["first"][0]["financials"]["stale"])
        fetch.return_value = financials(revenue_yoy_pct=44)
        pools, errors = self.enrich()
        fetch.assert_called_once_with(CODE, 1, AS_OF)
        self.assertEqual(errors, [])
        self.assertEqual(pools["first"][0]["financials"]["revenue_yoy_pct"], 44)
        self.assertEqual(self.cached_entry()["financials"]["fetched_at"], NOW.isoformat())

    @patch("financial_metrics.fetch_financials")
    def test_profile_thirty_day_cache_and_retry_do_not_suppress_financial_refresh(self, fetch):
        profile = {
            "company_intro": "主营测试业务。", "customer_summary": "",
            "industry": "测试行业", "concepts": ["测试概念"],
            "updated_at": (NOW - timedelta(days=29)).isoformat(),
            "retry_after": (NOW + timedelta(hours=1)).isoformat(),
        }
        self.assertTrue(company_metadata._cache_is_fresh(profile, NOW))
        self.assertEqual(company_metadata.CACHE_MAX_AGE_DAYS, 30)
        self.save_entry(**profile, financials=financials(
            fetched_at=(NOW - timedelta(hours=13)).isoformat()
        ))
        fetch.return_value = financials()
        self.enrich()
        fetch.assert_called_once()
        cached = self.cached_entry()
        for key, value in profile.items():
            self.assertEqual(cached[key], value, key)

    @patch("financial_metrics.fetch_financials")
    def test_expired_profile_does_not_expire_fresh_financials(self, fetch):
        profile = {"customer_summary": "", "updated_at": (NOW - timedelta(days=31)).isoformat()}
        self.assertFalse(company_metadata._cache_is_fresh(profile, NOW))
        self.save_entry(**profile, financials=financials(fetched_at=NOW.isoformat()))
        self.enrich()
        fetch.assert_not_called()

    @patch("financial_metrics.fetch_financials")
    def test_failure_keeps_stale_report_then_retries_after_two_hours(self, fetch):
        old = financials(fetched_at=(NOW - timedelta(days=1)).isoformat())
        self.save_entry(financials=old)
        fetch.side_effect = RuntimeError("offline fixture")
        pools, errors = self.enrich()
        self.assertEqual(len(errors), 1)
        self.assertIn("offline fixture", errors[0])
        self.assertEqual(pools["first"][0]["financials"]["report_date"], old["report_date"])
        self.assertTrue(pools["first"][0]["financials"]["stale"])
        cached = self.cached_entry()
        self.assertEqual(cached["financial_retry_after"], (NOW + timedelta(hours=2)).isoformat())
        self.assertEqual(cached["financial_as_of"], AS_OF)
        self.assertNotIn("retry_after", cached)
        self.assertNotIn("updated_at", cached)
        fetch.reset_mock()
        self.enrich(now=NOW + timedelta(hours=2) - timedelta(seconds=1))
        fetch.assert_not_called()
        fetch.side_effect = None
        fetch.return_value = financials(revenue_yoy_pct=88)
        pools, errors = self.enrich(now=NOW + timedelta(hours=2))
        fetch.assert_called_once()
        self.assertEqual(errors, [])
        self.assertFalse(pools["first"][0]["financials"]["stale"])
        self.assertNotIn("financial_retry_after", self.cached_entry())
        self.assertNotIn("financial_error", self.cached_entry())

    @patch("financial_metrics.fetch_financials")
    def test_failure_without_cache_does_not_create_zero_financials(self, fetch):
        fetch.side_effect = RuntimeError("offline fixture")
        pools, errors = self.enrich()
        self.assertEqual(len(errors), 1)
        self.assertEqual(pools["first"][0]["financials"], {})
        self.assertNotIn("financials", self.cached_entry())

    @patch("financial_metrics.fetch_financials")
    def test_historical_query_excludes_future_cache_and_ignores_other_cutoff_retry(self, fetch):
        self.save_entry(
            financials=financials(fetched_at=NOW.isoformat()),
            financial_as_of=AS_OF,
            financial_retry_after=(NOW + timedelta(hours=2)).isoformat(),
        )
        historical = fm.parse_financials(payload(source_row(
            REPORT_DATE="2026-03-31", NOTICE_DATE="2026-04-20",
        )), CODE, 1, "2026-06-01")
        fetch.return_value = historical
        pools, errors = self.enrich(as_of="2026-06-01")
        fetch.assert_called_once_with(CODE, 1, "2026-06-01")
        self.assertEqual(errors, [])
        self.assertEqual(pools["first"][0]["financials"]["report_date"], "2026-03-31")

    @patch("financial_metrics.fetch_financials")
    def test_future_cached_report_is_not_used_when_historical_fetch_fails(self, fetch):
        self.save_entry(financials=financials(fetched_at=NOW.isoformat()))
        fetch.side_effect = RuntimeError("offline fixture")
        pools, errors = self.enrich(as_of="2026-06-01")
        self.assertEqual(len(errors), 1)
        self.assertEqual(pools["first"][0]["financials"], {})

    @patch("financial_metrics.fetch_financials")
    def test_historical_fetch_then_current_failure_stays_stale_during_retry(self, fetch):
        historical_cutoff = "2026-06-01"
        fetch.return_value = fm.parse_financials(payload(source_row(
            REPORT_DATE="2026-03-31", NOTICE_DATE="2026-04-20",
        )), CODE, 1, historical_cutoff)
        pools, errors = self.enrich(as_of=historical_cutoff)
        self.assertEqual(errors, [])
        self.assertEqual(pools["first"][0]["financials"]["as_of"], historical_cutoff)
        self.assertFalse(pools["first"][0]["financials"]["stale"])

        fetch.reset_mock()
        fetch.side_effect = RuntimeError("today unavailable")
        pools, errors = self.enrich(now=NOW + timedelta(minutes=5))
        fetch.assert_called_once_with(CODE, 1, AS_OF)
        self.assertEqual(len(errors), 1)
        self.assertTrue(pools["first"][0]["financials"]["stale"])
        self.assertEqual(self.cached_entry()["financial_as_of"], AS_OF)
        self.assertEqual(self.cached_entry()["financials"]["as_of"], historical_cutoff)

        fetch.reset_mock()
        pools, errors = self.enrich(now=NOW + timedelta(minutes=10))
        fetch.assert_not_called()
        self.assertEqual(errors, [])
        self.assertTrue(pools["first"][0]["financials"]["stale"])
        self.assertEqual(pools["first"][0]["financials"]["report_date"], "2026-03-31")

        fetch.side_effect = None
        fetch.return_value = financials()
        pools, errors = self.enrich(now=NOW + timedelta(hours=2, minutes=5))
        fetch.assert_called_once_with(CODE, 1, AS_OF)
        self.assertEqual(errors, [])
        self.assertFalse(pools["first"][0]["financials"]["stale"])
        self.assertEqual(pools["first"][0]["financials"]["report_date"], "2026-06-30")
        self.assertEqual(self.cached_entry()["financials"]["as_of"], AS_OF)

    @patch("financial_metrics.fetch_financials")
    def test_legacy_cache_without_its_own_cutoff_is_refreshed(self, fetch):
        legacy = financials(fetched_at=NOW.isoformat())
        legacy.pop("as_of")
        self.save_entry(financials=legacy, financial_as_of=AS_OF)
        fetch.return_value = financials()
        self.enrich()
        fetch.assert_called_once_with(CODE, 1, AS_OF)
        self.assertEqual(self.cached_entry()["financials"]["as_of"], AS_OF)

    @patch("financial_metrics.fetch_financials")
    def test_duplicate_pool_aliases_fetch_once_and_receive_independent_copies(self, fetch):
        shared_row = {"code": CODE, "market": 1}
        pools = {
            "first": [shared_row], "main": [shared_row],
            "second": [{"code": CODE, "market": 1}],
            "secondary": [{"code": CODE, "market": 1}],
            "third": [{"code": CODE, "market": 1}],
        }
        fetch.return_value = financials()
        _, errors = self.enrich(pools)
        fetch.assert_called_once_with(CODE, 1, AS_OF)
        self.assertEqual(errors, [])
        expected = copy.deepcopy(shared_row["financials"])
        for rows in pools.values():
            self.assertEqual(rows[0]["financials"], expected)
        shared_row["financials"]["revenue_yoy_pct"] = 999
        self.assertEqual(pools["second"][0]["financials"], expected)
        self.assertEqual(self.cached_entry()["financials"], expected)

    @patch("financial_metrics.fetch_financials")
    def test_evaluation_objects_and_live_seeds_receive_values_without_aliasing(self, fetch):
        def evaluation(**overrides):
            fields = dict(code=CODE, market=1, eligible=True, bottom_ok=True, live_seed={})
            fields.update(overrides)
            return SimpleNamespace(**fields)

        first, duplicate = evaluation(), evaluation()
        excluded, not_bottom = evaluation(eligible=False), evaluation(bottom_ok=False)
        fetch.return_value = financials()
        errors = fm.enrich_financial_evaluations(
            [first, duplicate, excluded, not_bottom], max_workers=1,
            cache_path=self.cache_path, as_of=AS_OF, now=NOW,
        )
        self.assertEqual(errors, [])
        fetch.assert_called_once_with(CODE, 1, AS_OF)
        self.assertEqual(first.financials, duplicate.financials)
        self.assertEqual(first.live_seed["financials"], first.financials)
        self.assertIsNot(first.live_seed["financials"], first.financials)
        self.assertIsNot(first.financials, duplicate.financials)
        first.live_seed["financials"]["revenue_yoy_pct"] = 999
        self.assertEqual(first.financials["revenue_yoy_pct"], 12.5)
        self.assertFalse(hasattr(excluded, "financials"))
        self.assertFalse(hasattr(not_bottom, "financials"))
        self.assertEqual(excluded.live_seed, {})
        self.assertEqual(not_bottom.live_seed, {})

    @patch("financial_metrics.fetch_financials")
    def test_default_disclosure_cutoff_uses_china_date(self, fetch):
        fetch.return_value = financials()
        late_utc = datetime(2026, 9, 19, 17, 0, tzinfo=timezone.utc)
        self.enrich(now=late_utc, as_of="")
        fetch.assert_called_once_with(CODE, 1, "2026-09-20")


class FinancialBootstrapIntegrationTests(unittest.TestCase):
    def test_bootstrap_financials_use_settled_base_date(self):
        import cloud_daily

        base_date = "2026-06-01"
        evaluations = [SimpleNamespace(date=base_date)]
        for requested_cutoff in (base_date, None):
            with (
                self.subTest(requested_cutoff=requested_cutoff),
                patch("cloud_daily.screener.load_state", return_value={}),
                patch("cloud_daily.read_bootstrap_trade_date", return_value=base_date),
                patch("cloud_daily.screener.load_config", return_value={"workers": 1}),
                patch("cloud_daily.screener.scan_market", return_value=(evaluations, [], 1)),
                patch("cloud_daily.screener.scan_quality_error", return_value=""),
                patch("company_metadata.enrich_evaluations", return_value=[]),
                patch("financial_metrics.enrich_financial_evaluations", return_value=[]) as enrich,
                patch("cloud_daily.screener.is_intraday_snapshot", return_value=True),
            ):
                # Stop at the existing publication guard so the test cannot write reports.
                with self.assertRaisesRegex(RuntimeError, "拒绝把盘中数据"):
                    cloud_daily.bootstrap_live_snapshot(requested_cutoff)
                enrich.assert_called_once_with(evaluations, 1, as_of=base_date)


if __name__ == "__main__":
    unittest.main()
