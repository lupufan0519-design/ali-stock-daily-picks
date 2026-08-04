import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rolling_validation import ExecutionAssumptions
from screener import Bar, Stock
from strategy_contract import EXECUTION_SCOPE, FROZEN_CANDIDATE_ID, LIVE_STRATEGY_ID
from strategy_portfolio_validation import (
    DEFAULT_CANDIDATES,
    TradeRecord,
    build_report,
    candidate_trade_statistics,
    collect_candidate_trades,
    cost_scenario,
    resolve_candidates,
    simulate_portfolio,
    stable_order_key,
    trades_for_execution_scope,
)


ZERO_COSTS = ExecutionAssumptions(
    commission_bps_per_side=0.0,
    exchange_fee_bps_per_side=0.0,
    regulatory_fee_bps_per_side=0.0,
    stamp_duty_bps_sell=0.0,
    slippage_bps_per_side=0.0,
)


def trade(
    code: str,
    entry_date: str,
    exit_date: str,
    *,
    entry: float = 100.0,
    exit: float = 110.0,
    setup_date: str | None = None,
    area: str = "secondary",
) -> TradeRecord:
    return TradeRecord(
        candidate_id="entry__exit",
        code=code,
        name=code,
        area=area,
        setup_date=setup_date or entry_date,
        entry_date=entry_date,
        exit_date=exit_date,
        entry_raw_price=entry,
        entry_effective_price=entry,
        exit_raw_price=exit,
        exit_effective_price=exit,
        return_pct=(exit / entry - 1.0) * 100.0,
        holding_bars=1,
    )


def stock_bars(code: str, closes: dict[str, float]) -> list[Bar]:
    del code
    return [
        Bar(
            date=day,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000.0,
            amount=10000.0,
        )
        for day, close in sorted(closes.items())
    ]


class StrategyPortfolioValidationTests(unittest.TestCase):
    def test_formal_shortlist_contains_live_and_required_comparators(self):
        self.assertIn(FROZEN_CANDIDATE_ID, DEFAULT_CANDIDATES)
        self.assertIn(
            "low_risk_2__wave_erasure_trail_10_10",
            DEFAULT_CANDIDATES,
        )
        self.assertIn(
            "low_risk_2__wave_erasure_hybrid_or_8_3_weakening",
            DEFAULT_CANDIDATES,
        )
        self.assertIn("break_5day_high__trail_3_2", DEFAULT_CANDIDATES)

    def test_official_execution_scope_excludes_main_trades(self):
        trades = [
            trade("A", "2026-01-02", "2026-01-03", area="main"),
            trade("B", "2026-01-02", "2026-01-03", area="secondary"),
        ]

        scoped = trades_for_execution_scope(trades)

        self.assertEqual(EXECUTION_SCOPE, "secondary")
        self.assertEqual([item.code for item in scoped], ["B"])

    def test_report_metadata_uses_contract_and_can_omit_trade_rows(self):
        candidate = resolve_candidates([FROZEN_CANDIDATE_ID])[0]
        mocked_collection = (
            {FROZEN_CANDIDATE_ID: []},
            {},
            {},
            ["2026-01-02"],
        )
        with patch(
            "strategy_portfolio_validation.collect_candidate_trades",
            return_value=mocked_collection,
        ):
            report = build_report(
                {},
                [],
                [],
                1600,
                "2026-08-04",
                [candidate],
                ZERO_COSTS,
                [1.0, 2.0],
                include_trades=False,
            )

        self.assertEqual(report["meta"]["live_strategy_id"], LIVE_STRATEGY_ID)
        self.assertEqual(
            report["meta"]["frozen_candidate_id"], FROZEN_CANDIDATE_ID
        )
        self.assertEqual(report["meta"]["execution_scope"], "secondary")
        self.assertFalse(
            report["meta"]["forward_evaluation"][
                "historical_2026_is_blind_holdout"
            ]
        )
        payload = report["candidates"][FROZEN_CANDIDATE_ID]
        self.assertTrue(payload["trades_omitted"])
        self.assertNotIn("trades", payload)

    def test_same_day_exit_releases_capacity_before_entry(self):
        trades = [
            trade("A", "2026-01-02", "2026-01-03", exit=105.0),
            trade("B", "2026-01-03", "2026-01-04", exit=106.0),
        ]
        calendar = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
        bars_by_code = {
            "A": stock_bars("A", {day: 100.0 for day in calendar}),
            "B": stock_bars("B", {day: 100.0 for day in calendar}),
        }

        result = simulate_portfolio(
            trades,
            bars_by_code,
            calendar,
            ZERO_COSTS,
            max_positions=1,
            seed=11,
            cutoff="2026-01-04",
        )

        self.assertEqual(result["accepted_entries"], 2)
        self.assertEqual(result["completed_trades"], 2)
        self.assertEqual(result["capacity_rejections"], 0)

    def test_open_exit_keeps_capacity_and_is_marked_at_cutoff(self):
        open_trade = TradeRecord(
            candidate_id="entry__exit",
            code="A",
            name="A",
            area="secondary",
            setup_date="2026-01-01",
            entry_date="2026-01-02",
            exit_date=None,
            entry_raw_price=100.0,
            entry_effective_price=100.0,
            exit_raw_price=None,
            exit_effective_price=None,
            return_pct=None,
            holding_bars=None,
        )
        later = trade("B", "2026-01-03", "2026-01-04", exit=106.0)
        calendar = [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
        ]
        bars_by_code = {
            "A": stock_bars("A", {day: 100.0 for day in calendar}),
            "B": stock_bars("B", {day: 100.0 for day in calendar}),
        }

        result = simulate_portfolio(
            [open_trade, later],
            bars_by_code,
            calendar,
            ZERO_COSTS,
            max_positions=1,
            seed=11,
            cutoff="2026-01-04",
        )

        self.assertEqual(result["accepted_entries"], 1)
        self.assertEqual(result["completed_trades"], 0)
        self.assertEqual(result["open_positions_at_cutoff"], 1)
        self.assertEqual(result["capacity_rejections"], 1)
        self.assertAlmostEqual(result["open_position_market_value_at_cutoff"], 1_000_000.0)

    def test_collector_keeps_filled_entry_when_future_exit_never_completes(self):
        candidate = resolve_candidates([FROZEN_CANDIDATE_ID])[0]
        stock = Stock(0, "000001", "测试股票")
        bars = stock_bars(
            stock.code,
            {f"2026-01-{day:02d}": 10.0 for day in range(1, 7)},
        )
        points = [SimpleNamespace(area="secondary") for _ in range(5)]
        with (
            patch("strategy_portfolio_validation.replay_signals", return_value=points),
            patch("strategy_portfolio_validation.signal_indices", return_value=[0]),
            patch(
                "strategy_portfolio_validation.entry_for_method",
                return_value=(1, 10.0, 0, 10.0),
            ),
            patch("strategy_portfolio_validation.joint_trade_for_setup", return_value=None),
        ):
            records, diagnostics, _, calendar = collect_candidate_trades(
                {"minimum_history_bars": 1},
                [(stock, bars)],
                [candidate],
                ZERO_COSTS,
                cutoff="2026-01-05",
            )

        kept = records[FROZEN_CANDIDATE_ID]
        self.assertEqual(len(kept), 1)
        self.assertFalse(kept[0].is_completed)
        self.assertEqual(calendar[-1], "2026-01-05")
        self.assertEqual(
            diagnostics["candidate_portfolio_entry_count"][FROZEN_CANDIDATE_ID],
            1,
        )
        self.assertEqual(
            diagnostics["candidate_portfolio_open_at_cutoff_count"][
                FROZEN_CANDIDATE_ID
            ],
            1,
        )

    def test_single_trade_statistics_exclude_open_and_unmatured_tail(self):
        completed = trade("A", "2026-01-02", "2026-01-03", exit=110.0)
        tail_completed = TradeRecord(
            **{**completed.__dict__, "code": "B", "mature_sample": False}
        )
        open_trade = TradeRecord(
            **{
                **completed.__dict__,
                "code": "C",
                "exit_date": None,
                "exit_raw_price": None,
                "exit_effective_price": None,
                "return_pct": None,
                "holding_bars": None,
            }
        )

        result = candidate_trade_statistics(
            [completed, tail_completed, open_trade],
            ZERO_COSTS,
            1.0,
        )

        self.assertEqual(result["combined"]["overall"]["sample_count"], 1)

    def test_input_order_does_not_change_seed_result(self):
        trades = [
            trade("A", "2026-01-02", "2026-01-03", exit=101.0),
            trade("B", "2026-01-02", "2026-01-03", exit=103.0),
            trade("C", "2026-01-02", "2026-01-03", exit=107.0),
        ]
        calendar = ["2026-01-01", "2026-01-02", "2026-01-03"]
        bars_by_code = {
            code: stock_bars(code, {day: 100.0 for day in calendar})
            for code in ("A", "B", "C")
        }
        kwargs = dict(
            bars_by_code=bars_by_code,
            calendar=calendar,
            assumptions=ZERO_COSTS,
            max_positions=1,
            seed=47,
            cutoff="2026-01-03",
        )

        forward = simulate_portfolio(trades, **kwargs)
        reversed_input = simulate_portfolio(list(reversed(trades)), **kwargs)

        self.assertEqual(
            forward["accepted_trade_fingerprint"],
            reversed_input["accepted_trade_fingerprint"],
        )
        self.assertEqual(forward["periods"], reversed_input["periods"])

    def test_capacity_priority_cannot_see_candidate_or_future_exit(self):
        base = trade(
            "A",
            "2026-01-03",
            "2026-01-08",
            setup_date="2026-01-02",
        )
        comparator = TradeRecord(
            **{
                **base.__dict__,
                "candidate_id": "same_entry__different_exit",
                "exit_date": "2026-02-20",
                "exit_raw_price": 250.0,
                "exit_effective_price": 249.0,
                "return_pct": 149.0,
                "holding_bars": 30,
            }
        )

        self.assertNotEqual(base.uid, comparator.uid)
        self.assertEqual(
            stable_order_key(47, base),
            stable_order_key(47, comparator),
        )

    def test_post_boundary_prices_cannot_change_development_period(self):
        calendar = [
            "2023-12-28",
            "2023-12-29",
            "2023-12-31",
            "2024-01-02",
            "2024-01-03",
        ]
        common_closes = {
            "2023-12-28": 100.0,
            "2023-12-29": 100.0,
            "2023-12-31": 105.0,
        }
        optimistic = simulate_portfolio(
            [trade("A", "2023-12-29", "2024-01-03", exit=130.0)],
            {
                "A": stock_bars(
                    "A",
                    {**common_closes, "2024-01-02": 125.0, "2024-01-03": 130.0},
                )
            },
            calendar,
            ZERO_COSTS,
            max_positions=1,
            seed=11,
            cutoff="2024-01-03",
        )
        adverse = simulate_portfolio(
            [trade("A", "2023-12-29", "2024-01-03", exit=60.0)],
            {
                "A": stock_bars(
                    "A",
                    {**common_closes, "2024-01-02": 65.0, "2024-01-03": 60.0},
                )
            },
            calendar,
            ZERO_COSTS,
            max_positions=1,
            seed=11,
            cutoff="2024-01-03",
        )

        self.assertEqual(
            optimistic["periods"]["development"],
            adverse["periods"]["development"],
        )
        self.assertNotEqual(
            optimistic["periods"]["overall"]["total_return_pct"],
            adverse["periods"]["overall"]["total_return_pct"],
        )

    def test_effective_prices_apply_costs_once(self):
        assumptions = ExecutionAssumptions(
            commission_bps_per_side=100.0,
            exchange_fee_bps_per_side=0.0,
            regulatory_fee_bps_per_side=0.0,
            stamp_duty_bps_sell=200.0,
            slippage_bps_per_side=0.0,
        )
        calendar = ["2026-01-01", "2026-01-02", "2026-01-03"]
        result = simulate_portfolio(
            [trade("A", "2026-01-02", "2026-01-03", entry=100.0, exit=110.0)],
            {"A": stock_bars("A", {day: 100.0 for day in calendar})},
            calendar,
            assumptions,
            max_positions=1,
            seed=11,
            cutoff="2026-01-03",
        )
        expected = (110.0 * 0.97 / (100.0 * 1.01) - 1.0) * 100.0

        self.assertAlmostEqual(
            result["periods"]["overall"]["total_return_pct"],
            expected,
            places=4,
        )

    def test_double_stress_scales_only_commission_and_slippage(self):
        assumptions = ExecutionAssumptions(
            commission_bps_per_side=3.0,
            exchange_fee_bps_per_side=0.341,
            regulatory_fee_bps_per_side=0.2,
            stamp_duty_bps_sell=5.0,
            slippage_bps_per_side=5.0,
        )
        base = cost_scenario(assumptions, 1.0)
        doubled = cost_scenario(assumptions, 2.0)

        self.assertAlmostEqual(
            doubled["buy_cost_bps"] - base["buy_cost_bps"], 8.0
        )
        self.assertAlmostEqual(
            doubled["sell_cost_bps"] - base["sell_cost_bps"], 8.0
        )
        self.assertAlmostEqual(
            doubled["sell_cost_bps"] - doubled["buy_cost_bps"], 5.0
        )

    def test_trade_period_stats_require_entry_and_exit_inside_period(self):
        trades = [
            trade("A", "2023-12-01", "2023-12-08", area="main"),
            trade("B", "2023-12-28", "2024-01-05", area="main"),
            trade("C", "2024-01-02", "2025-12-30", area="secondary"),
            trade("D", "2025-12-29", "2026-01-06", area="secondary"),
            trade("E", "2026-01-02", "2026-01-09", area="secondary"),
        ]

        result = candidate_trade_statistics(trades, ZERO_COSTS, 1.0)

        self.assertEqual(result["combined"]["overall"]["sample_count"], 5)
        self.assertEqual(result["combined"]["development"]["sample_count"], 1)
        self.assertEqual(result["combined"]["validation"]["sample_count"], 1)
        self.assertEqual(result["combined"]["holdout_2026"]["sample_count"], 1)
        self.assertEqual(result["combined"]["cross_boundary_excluded_count"], 2)
        self.assertEqual(result["main"]["development"]["sample_count"], 1)
        self.assertEqual(result["secondary"]["validation"]["sample_count"], 1)


if __name__ == "__main__":
    unittest.main()
