import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import refresh_report_research
from report_ui import (
    LIVE_SCRIPT,
    STYLES,
    _cancelled_trend_case_chart,
    _execution_copy,
    _execution_summary,
    _layered_validation_section,
    _pending_entry_execution_row,
    _pending_exit_execution_row,
    _trend_case_chart,
    _validation_cohorts,
    render_report,
)


def bars():
    return [
        {"date": "2025-01-02", "open": 10.0, "high": 10.3, "low": 9.8, "close": 10.1},
        {"date": "2025-01-03", "open": 10.2, "high": 10.8, "low": 10.0, "close": 10.7},
        {"date": "2025-01-06", "open": 10.8, "high": 11.4, "low": 10.7, "close": 11.2},
        {"date": "2025-01-07", "open": 11.3, "high": 12.0, "low": 11.1, "close": 11.9},
        {"date": "2025-01-08", "open": 11.8, "high": 12.1, "low": 11.3, "close": 11.4},
        {"date": "2025-01-09", "open": 11.3, "high": 11.5, "low": 10.9, "close": 11.0},
    ]


def cancelled_case():
    return {
        "outcome": "cancelled",
        "code": "603300",
        "name": "海南华铁",
        "source": "通达信前复权日线",
        "cross_date": "2025-01-02",
        "signal_setup_date": "2025-01-03",
        "signal_price": 10.7,
        "cancel_date": "2025-01-06",
        "cancel_price": 11.2,
        "cancel_reason": "交叉信号被逐日重算抹去",
        "chart_caption": "1月3日形成候选，1月6日重算失效；没有买点和卖点。",
        "case_notes": [
            {"tone": "start", "label": "信号形成", "value": "2025-01-03"},
            {"tone": "end", "label": "候选取消", "value": "2025-01-06"},
            {"label": "结果", "value": "未成交"},
        ],
        "bars": bars(),
        "wave_dragon": [9.9, 10.15, 10.22, 10.5, 10.8, 10.9],
        "wave_tiger": [10.0, 10.1, 10.2, 10.35, 10.55, 10.7],
        "yellow_dates": ["2025-01-02"],
    }


def trade_case():
    return {
        "outcome": "trade",
        "code": "600001",
        "name": "合法案例",
        "source": "前复权日线",
        "cross_date": "2025-01-02",
        "signal_setup_date": "2025-01-02",
        "signal_date": "2025-01-02",
        "signal_price": 10.1,
        "entry_trigger_date": "2025-01-03",
        "entry_date": "2025-01-06",
        "entry_price": 10.82,
        "exit_trigger_date": "2025-01-08",
        "exit_date": "2025-01-09",
        "exit_price": 11.27,
        "return_pct": 4.16,
        "exit_return_pct": 4.16,
        "peak_date": "2025-01-07",
        "peak_close": 11.9,
        "peak_return_pct": 9.98,
        "exit_rule_id": "trail",
        "method": "同一状态机联合验证",
        "chart_caption": "1月3日收盘确认买点，1月6日开盘执行；1月8日收盘确认卖点，1月9日开盘执行。",
        "bars": bars(),
        "wave_dragon": [10.05, 10.2, 10.35, 10.55, 10.72, 10.8],
        "wave_tiger": [10.0, 10.12, 10.24, 10.4, 10.58, 10.7],
        "yellow_dates": ["2025-01-02"],
    }


def candidate(strategy_id, sample, success, average):
    return {
        "id": strategy_id,
        "entry_label": "收盘确认后下一交易日开盘买入",
        "exit_label": "收盘确认后下一交易日开盘卖出",
        "overall": {
            "sample_count": sample,
            "positive_rate_pct": success,
            "average_pct": average,
            "median_pct": average / 2,
            "median_holding_bars": 8,
        },
    }


def layered_payload():
    strategy_id = "formal-v1"
    cohort_data = {}
    for key, sample, success, average in (
        ("main", 40, 65.0, 4.2),
        ("secondary", 60, 58.0, 3.1),
        ("combined", 100, 61.0, 3.6),
        ("base_research", 180, 55.0, 2.0),
    ):
        row = candidate(strategy_id, sample, success, average)
        automatic = candidate("auto-v2", max(1, sample - 5), success + 2, average - 0.4)
        cohort_data[key] = {
            "setup_count": sample + 20,
            "optimization": {
                "selected_strategy_id": strategy_id,
                "selected_strategy": row,
                "frozen_live_strategy_id": strategy_id,
                "frozen_live_strategy": row,
                "automatic_recommended_id": "auto-v2",
                "automatic_recommended": automatic,
                "all_candidates": [row, automatic],
            },
        }
    return {
        "schema_version": 3,
        "meta": {
            "run_id": "run-20260804",
            "config_hash": "abcdef1234567890",
            "completed_trade_date": "2026-08-03",
            "execution_assumptions": {
                "entry": "收盘确认买点，下一交易日开盘执行",
                "exit": "收盘确认卖点，下一交易日开盘执行",
                "costs": "净收益已计回测假设费用",
            },
        },
        "coverage": {
            "analyzed_stock_count": 4998,
            "requested_stock_count": 5005,
            "error_count": 7,
        },
        "cohorts": cohort_data,
    }


class ReportUiTests(unittest.TestCase):
    def test_numeric_execution_assumptions_render_as_costed_net_returns(self):
        buy, sell, cost = _execution_copy({
            "meta": {
                "execution_assumptions": {
                    "commission_bps_per_side": 3.0,
                    "exchange_fee_bps_per_side": 0.341,
                    "regulatory_fee_bps_per_side": 0.2,
                    "stamp_duty_bps_sell": 5.0,
                    "slippage_bps_per_side": 5.0,
                    "buy_cost_bps": 8.541,
                    "sell_cost_bps": 13.541,
                    "commission_note": "未模拟单笔最低5元",
                    "execution_timing": "收盘确认指令，下一交易日开盘成交",
                }
            }
        })

        self.assertIn("下一交易日开盘", buy)
        self.assertIn("下一交易日开盘", sell)
        self.assertIn("净收益已计", cost)
        self.assertIn("8.541/13.541bp", cost)
        self.assertIn("未模拟单笔最低5元", cost)

    def test_execution_summary_deduplicates_shared_fill_timing(self):
        timing = "收盘确认指令，下一交易日开盘成交"
        self.assertEqual(_execution_summary(timing, timing), timing)
        self.assertEqual(
            _execution_summary("买点次日开盘", "卖点次日开盘"),
            "买点次日开盘；卖点次日开盘",
        )

    def test_cancelled_case_never_draws_buy_or_sell(self):
        html = _cancelled_trend_case_chart(cancelled_case())
        self.assertIn("候选取消", html)
        self.assertIn("未成交", html)
        self.assertEqual(html.count('data-case-leader="'), 2)
        self.assertNotIn("买入执行", html)
        self.assertNotIn("卖出执行", html)
        self.assertNotIn("波段高点", html)

    def test_schema3_cases_show_trade_then_fold_cancelled_example(self):
        payload = {
            "schema_version": 3,
            "primary_case": trade_case(),
            "cancelled_cases": [cancelled_case()],
        }
        with patch("report_ui._read_result_json", return_value=payload):
            html = _trend_case_chart()
        self.assertLess(html.index("合法案例"), html.index("海南华铁"))
        self.assertIn("查看候选取消反例", html)
        self.assertIn("1月6日重算失效", html)
        self.assertIn("买入执行", html)
        self.assertIn("卖出执行", html)

    def test_layered_validation_uses_one_strategy_and_labels_base_research(self):
        html = _layered_validation_section(layered_payload())
        self.assertIn("主选区 · 完整交易 40 笔", html)
        self.assertIn("次选区 · 完整交易 60 笔", html)
        self.assertIn("主次选合计 · 完整交易 100 笔", html)
        self.assertIn("历史回测成功率", html)
        self.assertIn("基础双信号研究（不代表主选或次选）", html)
        self.assertIn("formal-v1", html)
        self.assertIn("未启用的自动推荐研究对照", html)
        self.assertIn("当前没有驱动实时操作", html)
        self.assertNotIn("旧口径信号重绘", html)

    def test_validation_rejects_unversioned_or_unidentified_cohorts(self):
        valid = layered_payload()
        self.assertTrue(_validation_cohorts(valid))
        for payload in (
            {"cohorts": valid["cohorts"]},
            {**valid, "schema_version": 2},
            {**valid, "meta": {**valid["meta"], "run_id": ""}},
            {**valid, "cohorts": {"combined": valid["cohorts"]["combined"]}},
        ):
            self.assertEqual(_validation_cohorts(payload), {})

    def test_pending_execution_rows_keep_trigger_and_execution_separate(self):
        entry = {
            "code": "600001", "name": "买点待执行", "market": 1, "area": "main",
            "setup_date": "2026-08-01", "setup_price": 10, "entry_trigger_date": "2026-08-04",
            "entry_trigger_close": 10.8, "operation": "下一交易日开盘买入",
        }
        exit_item = {
            "code": "000001", "name": "卖点待执行", "market": 0, "area": "secondary",
            "entry_date": "2026-07-20", "entry_price": 10, "last_close": 11, "last_date": "2026-08-04",
            "return_pct": 10, "holding_days": 10, "exit_trigger_date": "2026-08-04",
            "exit_trigger_close": 11, "exit_trigger_return_pct": 10,
        }
        entry_html = _pending_entry_execution_row(entry)
        exit_html = _pending_exit_execution_row(exit_item, "secondary")
        self.assertIn("买点已确认", entry_html)
        self.assertIn("未建立持仓，不计收益", entry_html)
        self.assertIn("卖点已确认", exit_html)
        self.assertIn("未扣账户实际费用", exit_html)
        self.assertIn('data-pending-exit-execution="true"', exit_html)

    def test_report_uses_single_relative_poster_path_and_mobile_navigation(self):
        cfg = {
            "near_match_minimum": 3,
            "bottom_lookback_days": 5,
            "limit_up_lookback_days": 42,
            "yellow_consecutive_days": 1,
            "yellow_before_cross_days": 2,
            "yellow_after_cross_days": 7,
        }
        state = {
            "active": [], "closed": [], "secondary_active": [], "secondary_closed": [],
            "pending_entry_execution": [], "pending_exit_execution": [],
        }
        with patch("report_ui._validation_section", return_value='<section id="validation">验证</section>'):
            html = render_report([], cfg, 5211, [], state, [])
        self.assertEqual(html.count("hero-aigc-v2-poster.webp"), 1)
        self.assertNotIn("--cover-desktop:url", html)
        self.assertIn('href="#watch"', html)
        self.assertIn('href="#validation"', html)
        self.assertIn("data-live-coverage-count", html)
        self.assertIn("报告生成", html)
        self.assertIn("盘中行情更新", html)
        self.assertIn("table-scroll:not(.pool-table-shell)::before", STYLES)
        self.assertIn("setDockActive", LIVE_SCRIPT)

    def test_refresh_replaces_full_validation_section_and_last_script(self):
        source = """<!doctype html><html><head><script>head()</script><style>old</style></head><body>
        <!-- validation-section:start --><section id="validation"><section>old nested</section></section><!-- validation-section:end -->
        <script>(() => { oldLive(); })();</script></body></html>"""
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "latest.html"
            page.write_text(source, encoding="utf-8")
            with (
                patch("refresh_report_research._read_result_json", return_value=layered_payload()),
                patch("refresh_report_research._validation_section", return_value='<section id="validation">new validation</section>'),
            ):
                refresh_report_research.refresh(page)
            updated = page.read_text(encoding="utf-8")
        self.assertIn("head()", updated)
        self.assertIn("new validation", updated)
        self.assertNotIn("old nested", updated)
        self.assertIn(STYLES[:80], updated)
        self.assertIn(LIVE_SCRIPT[:40], updated)


if __name__ == "__main__":
    unittest.main()
