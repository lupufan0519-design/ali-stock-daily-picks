import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import refresh_report_research
from screener import Evaluation
from report_ui import (
    LIVE_SCRIPT,
    PRODUCTION_STRATEGY,
    RETURN_PRIORITY_CANDIDATE_ID,
    STYLES,
    _artifact_matches_grid,
    _cancelled_trend_case_chart,
    _cohort_candidate_for_id,
    _execution_copy,
    _execution_summary,
    _frozen_candidate_id,
    _layered_validation_section,
    _live_strategy_id,
    _pending_row,
    _pending_entry_execution_row,
    _pending_exit_execution_row,
    _portfolio_validation_panel,
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
        "exit_reason": None,
        "exit_rule_id": "wave_erasure_hybrid_or_10_10_weakening",
        "exit_rule_label": PRODUCTION_STRATEGY["exit_label"],
        "exit_rule": {
            "profit_activation_pct": 10.0,
            "trailing_drawdown_pct": 10.0,
        },
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
    live_strategy_id = PRODUCTION_STRATEGY["live_strategy_id"]
    candidate_id = PRODUCTION_STRATEGY["candidate_id"]
    cohort_data = {}
    for key, sample, success, average in (
        ("main", 40, 65.0, 4.2),
        ("secondary", 60, 58.0, 3.1),
        ("combined", 100, 61.0, 3.6),
        ("base_research", 180, 55.0, 2.0),
    ):
        row = candidate(candidate_id, sample, success, average)
        automatic = candidate("auto-v2", max(1, sample - 5), success + 2, average - 0.4)
        cohort_data[key] = {
            "setup_count": sample + 20,
            "optimization": {
                "selected_strategy_id": candidate_id,
                "selected_strategy": row,
                "live_strategy_id": live_strategy_id,
                "frozen_live_strategy_id": live_strategy_id,
                "frozen_live_strategy": {"live_strategy_id": live_strategy_id},
                "frozen_candidate_id": candidate_id,
                "frozen_candidate": row,
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
            "live_strategy_id": live_strategy_id,
            "frozen_candidate_id": candidate_id,
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
        "live_strategy_id": live_strategy_id,
        "frozen_candidate_id": candidate_id,
        "cohorts": cohort_data,
    }


def matching_case_payload():
    return {
        "schema_version": 3,
        "meta": {
            "run_id": "run-20260804",
            "config_hash": "abcdef1234567890",
            "completed_trade_date": "2026-08-03",
            "frozen_candidate_id": PRODUCTION_STRATEGY["candidate_id"],
        },
        "frozen_candidate_id": PRODUCTION_STRATEGY["candidate_id"],
        "primary_case": trade_case(),
        "cancelled_cases": [cancelled_case()],
    }


def portfolio_payload():
    def worst(exposure, rejections, cagr, drawdown):
        return {
            "average_exposure_pct": exposure,
            "capacity_rejections": rejections,
            "open_positions_at_cutoff": 2,
            "periods": {
                "development": {"cagr_pct": cagr + 1.0, "max_drawdown_pct": drawdown + 2.0},
                "validation": {"cagr_pct": cagr - 1.0, "max_drawdown_pct": drawdown - 1.0},
                "overall": {"cagr_pct": cagr, "max_drawdown_pct": drawdown},
            },
        }

    def scenario(values):
        return {
            "portfolios_by_area": {
                "secondary": {
                    str(slots): {"seed_summary": {"worst": worst(*metrics)}}
                    for slots, metrics in values.items()
                }
            }
        }

    return {
        "meta": {
            "completed_trade_date": "2026-08-03",
            "live_strategy_id": PRODUCTION_STRATEGY["live_strategy_id"],
            "frozen_candidate_id": PRODUCTION_STRATEGY["candidate_id"],
            "execution_scope": "secondary",
        },
        "candidates": {
            PRODUCTION_STRATEGY["candidate_id"]: {
                "execution_scope": "secondary",
                "exit_rule": {"id": PRODUCTION_STRATEGY["exit_id"]},
                "scenarios": {
                    "cost_1x": scenario({
                        5: (30.0, 210, 8.0, -52.0),
                        10: (22.0, 100, 6.0, -31.0),
                        20: (13.0, 33, 4.0, -18.0),
                    }),
                    "cost_2x": scenario({
                        5: (30.0, 210, 7.0, -54.0),
                        10: (22.0, 100, 5.0, -33.0),
                        20: (13.0, 33, 3.6, -20.0),
                    }),
                }
            },
            RETURN_PRIORITY_CANDIDATE_ID: {
                "execution_scope": "secondary",
                "exit_rule": {"id": "wave_erasure_trail_10_10"},
                "scenarios": {
                    "cost_1x": scenario({20: (18.0, 41, 4.7, -26.0)}),
                },
            },
        },
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
        payload = matching_case_payload()
        with patch("report_ui._read_result_json", return_value=payload):
            html = _trend_case_chart(layered_payload())
        self.assertLess(html.index("合法案例"), html.index("海南华铁"))
        self.assertIn("查看候选取消反例", html)
        self.assertIn("1月6日重算失效", html)
        self.assertIn("买入执行", html)
        self.assertIn("卖出执行", html)
        self.assertIn("浮盈达到10%后 · 高点回撤10%", html)

    def test_trend_case_requires_all_four_lineage_fields_to_match_grid(self):
        grid = layered_payload()
        case_payload = matching_case_payload()
        self.assertTrue(_artifact_matches_grid(case_payload, grid))
        with patch("report_ui._read_result_json", return_value=case_payload):
            self.assertIn("合法案例", _trend_case_chart(grid))

        for key, value in (
            ("run_id", "other-run"),
            ("config_hash", "other-hash"),
            ("completed_trade_date", "2026-08-01"),
            ("frozen_candidate_id", "other-candidate"),
        ):
            mismatch = matching_case_payload()
            mismatch["meta"][key] = value
            if key == "frozen_candidate_id":
                mismatch[key] = value
            with patch("report_ui._read_result_json", return_value=mismatch):
                self.assertEqual(_trend_case_chart(grid), "", key)

    def test_layered_validation_separates_main_observation_and_secondary_execution(self):
        with patch("report_ui._read_result_json", return_value={}):
            html = _layered_validation_section(layered_payload())
        self.assertIn("主选区 · 入选信号 60 次", html)
        self.assertIn("仅观察 · 不计绩效", html)
        self.assertIn("次选区 · 完整交易 60 笔", html)
        self.assertNotIn("主次选合计 · 完整交易", html)
        self.assertIn("历史回测成功率", html)
        self.assertIn("基础双信号研究（不代表主选或次选）", html)
        self.assertIn(PRODUCTION_STRATEGY["live_strategy_id"], html)
        self.assertIn(PRODUCTION_STRATEGY["candidate_id"], html)
        self.assertIn(PRODUCTION_STRATEGY["entry_label"], html)
        self.assertIn(PRODUCTION_STRATEGY["exit_label"], html)
        self.assertIn("未启用的自动推荐研究对照", html)
        self.assertIn("没有驱动实时操作", html)
        self.assertNotIn("旧口径信号重绘", html)

    def test_candidate_lookup_never_falls_back_to_another_candidate(self):
        payload = layered_payload()
        cohort = payload["cohorts"]["secondary"]
        self.assertEqual(_cohort_candidate_for_id(cohort, "missing-candidate"), {})
        self.assertEqual(_live_strategy_id(payload), PRODUCTION_STRATEGY["live_strategy_id"])
        self.assertEqual(_frozen_candidate_id(payload), PRODUCTION_STRATEGY["candidate_id"])

        payload["frozen_candidate_id"] = "missing-candidate"
        payload["meta"]["frozen_candidate_id"] = "missing-candidate"
        for current in payload["cohorts"].values():
            current["optimization"]["frozen_candidate_id"] = "missing-candidate"
        with patch("report_ui._read_result_json", return_value={}):
            html = _layered_validation_section(payload)
        self.assertIn("冻结候选数据缺失", html)
        self.assertNotIn("58.00% / +3.10%", html)

    def test_portfolio_panel_shows_matching_frozen_candidate_only(self):
        grid = layered_payload()
        portfolio = portfolio_payload()
        with patch("report_ui._read_result_json", return_value=portfolio):
            html = _portfolio_validation_panel(grid)
        self.assertIn("次选 · 正式策略仓位验证", html)
        self.assertIn("5 槽位", html)
        self.assertIn("10 槽位", html)
        self.assertIn("20 槽位", html)
        self.assertIn("整体账户CAGR", html)
        self.assertIn("+8.00%", html)
        self.assertIn("平均敞口", html)
        self.assertIn("容量拒绝", html)
        self.assertIn("截止持仓", html)
        self.assertIn("收益优先纯10/10", html)
        self.assertIn("只高 0.70 个百分点", html)
        self.assertIn("最大回撤却加深 8.00 个百分点", html)
        self.assertIn("佣金与滑点2×压力行", html)
        self.assertIn("排序只使用买入时已经知道", html)
        self.assertIn("未来卖不出的股票", html)
        self.assertIn("未结束持仓", html)
        self.assertIn("至少72根K线", html)
        self.assertIn("不是单笔成功率", html)
        self.assertIn("真正的forward验证", html)
        self.assertNotIn("2026盲测", html)

        mismatched = portfolio_payload()
        mismatched["meta"]["completed_trade_date"] = "2026-08-01"
        with patch("report_ui._read_result_json", return_value=mismatched):
            self.assertEqual(_portfolio_validation_panel(grid), "")
        wrong_candidate = portfolio_payload()
        wrong_candidate["meta"]["frozen_candidate_id"] = "another"
        with patch("report_ui._read_result_json", return_value=wrong_candidate):
            self.assertEqual(_portfolio_validation_panel(grid), "")
        missing = portfolio_payload()
        missing["candidates"] = {"another": next(iter(missing["candidates"].values()))}
        with patch("report_ui._read_result_json", return_value=missing):
            self.assertEqual(_portfolio_validation_panel(grid), "")
        wrong_scope = portfolio_payload()
        wrong_scope["meta"]["execution_scope"] = "combined"
        with patch("report_ui._read_result_json", return_value=wrong_scope):
            self.assertEqual(_portfolio_validation_panel(grid), "")
        incomplete = portfolio_payload()
        del incomplete["candidates"][PRODUCTION_STRATEGY["candidate_id"]]["scenarios"]["cost_1x"]["portfolios_by_area"]["secondary"]["10"]["seed_summary"]["worst"]["capacity_rejections"]
        with patch("report_ui._read_result_json", return_value=incomplete):
            self.assertEqual(_portfolio_validation_panel(grid), "")

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

    def test_pending_secondary_uses_d2_contract_and_main_is_observation_only(self):
        setup = {
            "code": "600001", "name": "候选", "market": 1,
            "setup_date": "2026-08-01", "setup_price": 10,
            "last_date": "2026-08-04", "last_close": 9.9,
            "setup_elapsed_bars": 2,
            "status_detail": "旧规则文字不应显示",
        }
        secondary_html = _pending_row(setup, "secondary")
        main_html = _pending_row(setup, "main")
        self.assertIn("第2个完整交易日", secondary_html)
        self.assertNotIn("旧规则文字不应显示", secondary_html)
        self.assertIn("不执行买卖", main_html)
        self.assertIn("不纳入生产绩效", main_html)

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
        self.assertIn("主选区 · 仅观察", html)
        self.assertIn("次选区 · 生产执行", html)
        self.assertNotIn('id="tracking-main-body"', html)
        self.assertIn(PRODUCTION_STRATEGY["entry_label"], html)
        self.assertIn(PRODUCTION_STRATEGY["exit_label"], html)
        self.assertNotIn("此前5日最高价", html)
        self.assertNotIn("回撤2%", html)

    def test_legacy_main_positions_remain_visible_without_entering_main_counts(self):
        cfg = {
            "near_match_minimum": 3,
            "bottom_lookback_days": 5,
            "limit_up_lookback_days": 42,
            "yellow_consecutive_days": 1,
            "yellow_before_cross_days": 2,
            "yellow_after_cross_days": 7,
        }
        active = {
            "code": "301516", "name": "中远通", "market": 0,
            "entry_date": "2026-07-20", "entry_price": 18.0,
            "last_date": "2026-08-03", "last_close": 19.2,
            "return_pct": 6.67, "holding_days": 10,
            "status": "上升趋势中", "operation": "继续持有",
            "status_detail": "策略切换前持仓继续管理",
        }
        pending_exit = {
            "code": "600001", "name": "待卖存量", "market": 1, "area": "main",
            "entry_date": "2026-07-21", "entry_price": 10.0,
            "last_date": "2026-08-03", "last_close": 10.8,
            "return_pct": 8.0, "holding_days": 9,
            "exit_trigger_date": "2026-08-03", "exit_trigger_close": 10.8,
            "exit_trigger_return_pct": 8.0,
        }
        state = {
            "active": [active], "closed": [],
            "secondary_active": [], "secondary_closed": [],
            "pending_entry_execution": [], "pending_exit_execution": [pending_exit],
        }
        with patch("report_ui._validation_section", return_value='<section id="validation">验证</section>'):
            html = render_report([], cfg, 5211, [], state, [])
        self.assertIn("策略切换前持仓", html)
        self.assertIn("仅存量管理，不计新策略绩效", html)
        self.assertIn("中远通", html)
        self.assertIn("待卖存量", html)
        self.assertIn('id="tracking-main-body"', html)
        self.assertIn('<strong class="kpi-value" data-area-main-count>0</strong>', html)
        self.assertNotIn("主选区已结束毛收益成功率", html)

    def test_secondary_live_signal_is_not_duplicated_when_already_tracked(self):
        cfg = {
            "near_match_minimum": 3,
            "bottom_lookback_days": 5,
            "limit_up_lookback_days": 42,
            "yellow_consecutive_days": 1,
            "yellow_before_cross_days": 2,
            "yellow_after_cross_days": 7,
        }
        evaluation = Evaluation(
            code="600001", name="重复标的", market=1, date="2026-08-04",
            open=10.0, high=10.5, low=9.8, close=10.2,
            previous_close=10.0, limit_up_price=11.0, limit_down_price=9.0,
            one_word_limit_up=False, one_word_limit_down=False,
            entry_breakout_high_5=10.4, change_pct=2.0,
            bottom_ok=True, cross_ok=True, limit_up_ok=False, yellow_ok=True,
            bottom_date="2026-08-04", cross_date="2026-08-01",
            limit_up_date="", yellow_date="2026-08-01", yellow_count=1,
            matched_count=3, observation_yellow_ok=True,
            observation_yellow_date="2026-08-01", observation_yellow_count=1,
            observation_matched_count=3, dragon_above_tiger=True,
            dragon_value=9.8, tiger_value=9.0, eligible=True, selected=False,
            chart="",
        )
        active = {
            "code": "600001", "name": "重复标的", "market": 1,
            "entry_date": "2026-08-01", "entry_price": 10.0,
            "last_date": "2026-08-04", "last_close": 10.2,
            "return_pct": 2.0, "holding_days": 3,
            "status": "上升趋势中", "operation": "继续持有",
            "strategy_version": PRODUCTION_STRATEGY["live_strategy_id"],
        }
        state = {
            "active": [], "closed": [],
            "secondary_active": [active], "secondary_closed": [],
            "pending_main": [], "pending_secondary": [],
            "pending_entry_execution": [], "pending_exit_execution": [],
        }

        with patch("report_ui._validation_section", return_value='<section id="validation">验证</section>'):
            html = render_report([evaluation], cfg, 5211, [], state, [])

        live_body = html.split('<tbody id="live-secondary-body">', 1)[1].split(
            "</tbody>", 1
        )[0]
        tracking_body = html.split(
            '<tbody id="tracking-secondary-body">', 1
        )[1].split("</tbody>", 1)[0]
        self.assertNotIn('data-live-code="600001"', live_body)
        self.assertEqual(tracking_body.count('data-tracking-code="600001"'), 1)
        self.assertIn("新信号 <strong data-live-secondary-count>0</strong>", html)
        self.assertIn("跟踪 <strong data-tracked-secondary-count>1</strong>", html)

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
