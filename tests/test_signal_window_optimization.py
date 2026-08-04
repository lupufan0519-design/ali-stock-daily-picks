from __future__ import annotations

import unittest
from unittest.mock import patch

from rolling_validation import ExecutionAssumptions, SignalPoint
from screener import Bar, Stock
from signal_failure_examples import failure_rows
from signal_repaint_comparison import measurement
from strategy_contract import (
    ENTRY_LABEL,
    EXECUTION_SCOPE,
    EXIT_LABEL,
    FROZEN_CANDIDATE_ID,
    LIVE_STRATEGY_ID,
    strategy_contract,
)
from signal_window_optimization import (
    CohortSamples,
    ENTRY_METHODS,
    EXIT_RULES,
    FROZEN_LIVE_STRATEGY_ID,
    Samples,
    WaveCaptureSamples,
    WaveSamples,
    append_wave_sample,
    balanced_candidate,
    candidate_summary,
    entry_for_method,
    exit_for_rule,
    exit_reason_for_trade,
    joint_trade_for_setup,
    risk_exit_index,
    signal_indices,
    trade_case_payload,
    user_long_wave_summary,
    wave_capture_stats,
)


def point(
    day: int,
    *,
    close: float = 10.0,
    dragon: float = 11.0,
    tiger: float = 10.0,
    base_signal: bool = False,
    cross_ok: bool = True,
    cross_age: int = 0,
    cross_lookback_days: int = 8,
    area: str = "",
    cross_date: str = "",
) -> SignalPoint:
    return SignalPoint(
        date=f"2026-07-{day:02d}",
        close=close,
        dragon=dragon,
        tiger=tiger,
        area=area,
        base_signal=base_signal,
        endpoint_cross=False,
        cross_ok=cross_ok,
        yellow_ok=base_signal,
        cross_age=cross_age,
        cross_lookback_days=cross_lookback_days,
        cross_date=cross_date,
    )


def bars(points: list[SignalPoint], highs: list[float] | None = None) -> list[Bar]:
    highs = highs or [item.close + 0.2 for item in points]
    return [
        Bar(
            date=item.date,
            open=item.close,
            high=high,
            low=item.close - 0.2,
            close=item.close,
            volume=1000.0,
            amount=10000.0,
        )
        for item, high in zip(points, highs)
    ]


class SignalWindowOptimizationTests(unittest.TestCase):
    def test_period_buckets_require_both_entry_and_exit_inside_period(self):
        samples = Samples()
        samples.add(1.0, 5, "2023-12-01", "2023-12-08")
        samples.add(2.0, 5, "2023-12-28", "2024-01-05")
        samples.add(3.0, 5, "2024-01-02", "2025-12-30")
        samples.add(4.0, 5, "2025-12-29", "2026-01-06")
        samples.add(5.0, 5, "2026-01-02", "2026-01-09")

        self.assertEqual(list(samples.returns), [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(list(samples.development), [1.0])
        self.assertEqual(list(samples.development_holding), [5])
        self.assertEqual(list(samples.validation), [3.0])
        self.assertEqual(list(samples.validation_holding), [5])
        self.assertEqual(list(samples.holdout), [5.0])
        self.assertEqual(list(samples.holdout_holding), [5])
        self.assertEqual(
            {year: len(values) for year, values in samples.by_completed_year.items()},
            {"2023": 1, "2024": 1, "2025": 1, "2026": 2},
        )

    def test_cohort_samples_forward_exit_date_to_area_buckets(self):
        samples = CohortSamples()
        samples.add(
            1.0,
            5,
            "2023-12-28",
            "2024-01-05",
            "main",
        )

        self.assertEqual(len(samples.combined.returns), 1)
        self.assertEqual(len(samples.main.returns), 1)
        self.assertEqual(len(samples.secondary.returns), 0)
        self.assertEqual(len(samples.combined.development), 0)
        self.assertEqual(len(samples.main.validation), 0)

    def test_candidate_summary_reports_completed_years_without_using_them_for_selection(self):
        samples = Samples()
        samples.add(5.0, 4, "2023-01-03", "2023-01-09")
        samples.add(-2.0, 6, "2024-02-01", "2024-02-09")
        samples.add(3.0, 3, "2026-03-02", "2026-03-05")

        summary = candidate_summary(
            ("signal_close", "relationship_end"),
            samples,
        )

        self.assertEqual(list(summary["by_completed_year"]), ["2023", "2024", "2026"])
        self.assertEqual(summary["positive_completed_years"], ["2023", "2026"])
        self.assertEqual(summary["positive_completed_year_count"], 2)
        self.assertEqual(summary["positive_completed_years_before_2026"], ["2023"])
        self.assertEqual(summary["positive_completed_year_count_before_2026"], 1)
        self.assertEqual(summary["completed_year_selection_use"], "report_only")
        self.assertEqual(summary["period_boundary_spanning_trade_count"], 0)
        self.assertEqual(
            summary["development_before_2024"]["median_holding_bars"],
            4.0,
        )
        self.assertEqual(
            summary["validation_2024_2025"]["median_holding_bars"],
            6.0,
        )

    def test_historical_failure_examples_use_final_chart_mode(self):
        with patch(
            "signal_failure_examples.replay_signals",
            return_value=[],
        ) as replay:
            rows, signal_count, excluded_count = failure_rows(
                [(Stock(0, "000898", "鞍钢股份"), [])],
                {},
                mode="retrospective",
            )

        self.assertEqual(rows, [])
        self.assertEqual(signal_count, 0)
        self.assertEqual(excluded_count, 0)
        self.assertEqual(replay.call_args.kwargs["mode"], "retrospective")

    def test_repaint_comparison_excludes_nonpositive_adjusted_prices(self):
        points = [point(day, close=10.0) for day in range(1, 75)]
        points[0] = point(1, close=-1.0, base_signal=True)
        measured = measurement(points, bars(points), 0)
        self.assertEqual(measured, {"excluded_nonpositive_price": True})

    def test_failure_examples_exclude_nonpositive_adjusted_prices(self):
        points = [point(day, close=10.0) for day in range(1, 75)]
        points[0] = point(1, close=-1.0, base_signal=True)
        points[1] = point(2, close=10.0, dragon=9.0, tiger=10.0)
        with patch(
            "signal_failure_examples.replay_signals",
            return_value=points,
        ):
            rows, signal_count, excluded_count = failure_rows(
                [(Stock(0, "000001", "示例"), bars(points))],
                {},
                mode="retrospective",
            )

        self.assertEqual(rows, [])
        self.assertEqual(signal_count, 1)
        self.assertEqual(excluded_count, 1)

    def test_every_signal_reappearance_is_counted(self):
        points = [
            point(1, base_signal=False),
            point(2, base_signal=True),
            point(3, base_signal=True),
            point(4, base_signal=False),
            point(5, base_signal=True),
        ]
        self.assertEqual(signal_indices(points), [1, 4])

    def test_pool_promotion_does_not_create_a_second_event(self):
        points = [
            point(1),
            point(2, area="secondary", cross_date="2026-07-01"),
            point(3, area="main", cross_date="2026-07-01"),
            point(4),
        ]
        self.assertEqual(signal_indices(points, "pool"), [1])

    def test_pool_lineage_releases_only_after_relationship_loss(self):
        points = [
            point(1, area="secondary", cross_date="2026-06-30"),
            point(2),
            point(3, area="secondary", cross_date="2026-06-30"),
            point(4, dragon=9.0, tiger=10.0, cross_ok=False),
            point(5, area="main", cross_date="2026-07-04"),
        ]
        self.assertEqual(signal_indices(points, "pool"), [0, 4])

    def test_cross_date_tail_drift_does_not_create_a_second_pool_setup(self):
        points = [
            point(1, area="secondary", cross_date="2026-06-30"),
            point(2),
            point(3, area="secondary", cross_date="2026-07-02"),
            point(4),
            point(5, area="main", cross_date="2026-07-04"),
        ]
        self.assertEqual(signal_indices(points, "pool"), [0])

    def test_holdout_changes_do_not_change_frozen_balanced_choice(self):
        def candidate(identifier: str, dev_geo: float, valid_geo: float, holdout: float) -> dict:
            period = lambda geo: {
                "sample_count": 250,
                "geometric_average_pct": geo,
                "positive_rate_pct": 60.0,
                "average_excluding_abs_50pct_outliers_pct": geo,
            }
            return {
                "id": identifier,
                "development_before_2024": period(dev_geo),
                "validation_2024_2025": period(valid_geo),
                "holdout_2026": {"sample_count": 999, "average_pct": holdout},
            }

        first = [candidate("a", 2.0, 2.0, -99.0), candidate("b", 1.0, 1.0, 99.0)]
        second = [candidate("a", 2.0, 2.0, 99.0), candidate("b", 1.0, 1.0, -99.0)]
        self.assertEqual(balanced_candidate(first)["id"], "a")
        self.assertEqual(balanced_candidate(second)["id"], "a")

    def test_breakout_is_cancelled_when_signal_erases_on_confirmation_close(self):
        points = [
            point(1, close=10.0, base_signal=True, cross_ok=True, cross_age=1),
            point(2, close=10.8, cross_ok=False, dragon=11.0, tiger=10.0),
            point(3, close=11.0),
        ]
        result = entry_for_method(
            points,
            bars(points, [10.2, 10.5, 11.1]),
            0,
            {"kind": "recent_high", "lookback": 1},
        )
        self.assertIsNone(result)

    def test_exit_threshold_uses_raw_entry_but_return_uses_cost_adjusted_fills(self):
        points = [
            point(1, close=10.0, base_signal=True, cross_ok=True),
            point(2, close=10.1),
            point(3, close=10.31),
            point(4, close=10.25),
            point(5, close=10.2),
        ]
        history = [
            Bar(
                date=item.date,
                open=open_price,
                high=max(open_price, item.close) + 0.1,
                low=min(open_price, item.close) - 0.1,
                close=item.close,
                volume=1000.0,
                amount=10000.0,
            )
            for item, open_price in zip(points, [10.0, 10.0, 10.2, 10.25, 10.2])
        ]
        assumptions = ExecutionAssumptions(
            commission_bps_per_side=200.0,
            exchange_fee_bps_per_side=0.0,
            regulatory_fee_bps_per_side=0.0,
            stamp_duty_bps_sell=0.0,
            slippage_bps_per_side=0.0,
        )
        trade = joint_trade_for_setup(
            Stock(1, "600001", "示例"),
            history,
            points,
            0,
            {"id": "signal_close", "label": "确认", "kind": "close", "delay": 0},
            {"id": "target_3", "label": "达到3%", "kind": "target", "target": 3.0},
            assumptions,
        )
        self.assertEqual(trade["entry_raw_price"], 10.0)
        self.assertEqual(trade["exit_trigger_index"], 2)
        self.assertLess(trade["return_pct"], 0.0)

    def test_cross_date_drift_does_not_cancel_a_still_valid_blocked_buy(self):
        points = [
            point(1, close=10.0, base_signal=True, cross_date="2026-06-30"),
            point(2, close=11.0, cross_date="2026-07-02"),
            point(3, close=10.8, cross_date="2026-07-02"),
        ]
        history = [
            Bar("2026-07-01", 10.0, 10.1, 9.9, 10.0, 1000.0, 10000.0),
            Bar("2026-07-02", 11.0, 11.0, 11.0, 11.0, 1000.0, 10000.0),
            Bar("2026-07-03", 10.8, 10.9, 10.7, 10.8, 1000.0, 10000.0),
        ]
        assumptions = ExecutionAssumptions(
            commission_bps_per_side=0.0,
            exchange_fee_bps_per_side=0.0,
            regulatory_fee_bps_per_side=0.0,
            stamp_duty_bps_sell=0.0,
            slippage_bps_per_side=0.0,
        )
        result = entry_for_method(
            points,
            history,
            0,
            {"kind": "close", "delay": 0},
            stock=Stock(1, "600001", "示例"),
            execution=assumptions,
        )
        self.assertEqual(result, (2, 10.8))

    def test_blocked_buy_is_cancelled_after_relationship_loss(self):
        points = [
            point(1, close=10.0, base_signal=True, cross_date="2026-06-30"),
            point(
                2,
                close=11.0,
                dragon=9.0,
                tiger=10.0,
                cross_ok=False,
                cross_date="2026-06-30",
            ),
            point(3, close=10.8, cross_date="2026-07-02"),
        ]
        history = [
            Bar("2026-07-01", 10.0, 10.1, 9.9, 10.0, 1000.0, 10000.0),
            Bar("2026-07-02", 11.0, 11.0, 11.0, 11.0, 1000.0, 10000.0),
            Bar("2026-07-03", 10.8, 10.9, 10.7, 10.8, 1000.0, 10000.0),
        ]
        assumptions = ExecutionAssumptions(
            commission_bps_per_side=0.0,
            exchange_fee_bps_per_side=0.0,
            regulatory_fee_bps_per_side=0.0,
            stamp_duty_bps_sell=0.0,
            slippage_bps_per_side=0.0,
        )
        result = entry_for_method(
            points,
            history,
            0,
            {"kind": "close", "delay": 0},
            stock=Stock(1, "600001", "示例"),
            execution=assumptions,
        )
        self.assertIsNone(result)

    def test_wave_peak_excludes_signal_day_and_stops_at_relationship_end(self):
        points = [point(day, close=10.0) for day in range(1, 63)]
        points[0] = point(1, close=10.0, base_signal=True)
        points[1] = point(2, close=10.4)
        points[2] = point(3, close=10.2, dragon=9.0, tiger=10.0)
        history = bars(points, [50.0, 11.0, 12.0] + [10.2] * 59)
        samples = WaveSamples()

        erased, end_index = append_wave_sample(samples, points, history, 0)

        self.assertFalse(erased)
        self.assertEqual(end_index, 2)
        self.assertAlmostEqual(samples.peak_high_returns[0], 20.0, places=4)
        self.assertEqual(samples.days_to_peak_high[0], 2)

    def test_label_erasure_is_only_an_exit_when_explicitly_requested(self):
        points = [
            point(1, base_signal=True, cross_ok=True),
            point(2, cross_ok=False, dragon=11.2, tiger=10.0),
            point(3, cross_ok=False, dragon=11.1, tiger=10.0),
            point(4, cross_ok=False, dragon=9.8, tiger=10.0),
        ]
        self.assertEqual(risk_exit_index(points, 0, 0), 3)
        self.assertEqual(
            risk_exit_index(points, 0, 0, exit_on_erasure=True),
            1,
        )

    def test_fixed_target_uses_confirmed_closing_price(self):
        points = [
            point(1, close=10.0, base_signal=True),
            point(2, close=10.4),
            point(3, close=10.6),
            point(4, close=10.1),
        ]
        exit_index = exit_for_rule(
            points,
            setup_index=0,
            entry_index=0,
            entry_price=10.0,
            hard_end=3,
            rule={"kind": "target", "target": 5.0},
        )
        self.assertEqual(exit_index, 2)

    def test_next_open_does_not_use_the_same_days_closing_signal(self):
        points = [
            point(1, close=10.0, base_signal=True, cross_ok=True),
            point(2, close=9.8, cross_ok=False, dragon=11.0, tiger=10.0),
        ]
        history = bars(points)
        history[1] = Bar(
            date=history[1].date,
            open=10.2,
            high=10.3,
            low=9.7,
            close=9.8,
            volume=1000.0,
            amount=10000.0,
        )

        next_open = entry_for_method(
            points,
            history,
            0,
            {"kind": "open", "delay": 1},
        )
        next_close = entry_for_method(
            points,
            history,
            0,
            {"kind": "close", "delay": 1},
        )

        self.assertEqual(next_open, (1, 10.2))
        self.assertIsNone(next_close)

    def test_price_and_recent_high_confirmations_use_only_prior_bars(self):
        points = [
            point(1, close=10.0, base_signal=True),
            point(2, close=10.2),
            point(3, close=10.5),
        ]
        history = bars(points, [10.3, 10.4, 10.6])

        threshold = entry_for_method(
            points,
            history,
            0,
            {"kind": "threshold", "threshold": 3.0},
        )
        breakout = entry_for_method(
            points,
            history,
            0,
            {"kind": "recent_high", "lookback": 2},
        )

        self.assertEqual(threshold, (2, 10.5))
        self.assertEqual(breakout, (2, 10.5))

    def test_short_confirmation_window_rejects_a_late_breakout(self):
        points = [
            point(1, close=10.0, base_signal=True),
            point(2, close=10.0),
            point(3, close=10.0),
            point(4, close=10.0),
            point(5, close=10.2),
        ]

        result = entry_for_method(
            points,
            bars(points),
            0,
            {
                "kind": "threshold",
                "threshold": 1.0,
                "max_wait": 3,
            },
        )

        self.assertIsNone(result)

    def test_low_risk_two_day_filter_fills_only_at_following_open(self):
        points = [
            point(1, close=10.0, dragon=9.8, tiger=9.0, base_signal=True),
            point(2, close=10.05, dragon=9.9, tiger=9.0),
            point(3, close=10.1, dragon=10.0, tiger=9.0),
            point(4, close=10.3, dragon=10.1, tiger=9.0),
        ]
        history = bars(points)
        history[3] = Bar(
            date=points[3].date,
            open=10.2,
            high=10.4,
            low=10.1,
            close=10.3,
            volume=1000.0,
            amount=10000.0,
        )
        assumptions = ExecutionAssumptions(
            commission_bps_per_side=0.0,
            exchange_fee_bps_per_side=0.0,
            regulatory_fee_bps_per_side=0.0,
            stamp_duty_bps_sell=0.0,
            slippage_bps_per_side=0.0,
        )
        method = next(item for item in ENTRY_METHODS if item["id"] == "low_risk_2")

        result = entry_for_method(
            points,
            history,
            0,
            method,
            stock=Stock(1, "600001", "示例"),
            execution=assumptions,
            include_trigger=True,
        )

        self.assertEqual(result, (3, 10.2, 2, 10.2))
        self.assertIn("较信号日收盘回撤不超过3%", method["label"])
        self.assertEqual(method["label"], ENTRY_LABEL)

    def test_frozen_hybrid_case_carries_the_shared_contract_identity(self):
        points = [
            point(
                day,
                close=10.0 + day * 0.1,
                dragon=10.0 + day * 0.05,
                tiger=9.0,
                base_signal=day == 1,
                area="secondary" if day == 1 else "",
                cross_date="2026-07-01",
            )
            for day in range(1, 7)
        ]
        history = bars(points)
        method = next(item for item in ENTRY_METHODS if item["id"] == "low_risk_2")
        exit_rule = next(
            item
            for item in EXIT_RULES
            if item["id"] == "wave_erasure_hybrid_or_10_10_weakening"
        )
        payload = trade_case_payload(
            Stock(1, "600001", "示例"),
            history,
            points,
            {
                "setup_index": 0,
                "entry_trigger_index": 2,
                "entry_index": 3,
                "entry_raw_price": 10.4,
                "entry_effective_price": 10.41,
                "exit_trigger_index": 4,
                "exit_index": 5,
                "exit_raw_price": 10.6,
                "exit_effective_price": 10.59,
                "return_pct": 1.73,
                "holding_bars": 2,
                "exit_reason": "dragon_tiger_weakening",
            },
            method,
            exit_rule,
        )

        self.assertEqual(payload["candidate_id"], FROZEN_CANDIDATE_ID)
        self.assertEqual(payload["execution_scope"], EXECUTION_SCOPE)
        self.assertEqual(payload["entry_rule"]["id"], "low_risk_2")
        self.assertEqual(
            payload["exit_rule"]["id"],
            "wave_erasure_hybrid_or_10_10_weakening",
        )
        self.assertEqual(payload["activation"], 10.0)
        self.assertEqual(payload["drawdown"], 10.0)
        self.assertEqual(payload["exit_rule"]["label"], EXIT_LABEL)
        self.assertEqual(payload["exit_reason"], "dragon_tiger_weakening")

    def test_frozen_optimizer_rules_are_driven_by_the_shared_contract(self):
        contract = strategy_contract()
        entry = next(item for item in ENTRY_METHODS if item["id"] == contract["entry_id"])
        exit_rule = next(item for item in EXIT_RULES if item["id"] == contract["exit_id"])

        self.assertEqual(entry["label"], contract["entry_label"])
        self.assertEqual(entry["delay"], contract["entry_delay_bars"])
        self.assertEqual(entry["max_pullback"], contract["entry_max_pullback_pct"])
        self.assertEqual(
            entry["require_above_dragon"],
            contract["require_close_above_dragon"],
        )
        self.assertEqual(
            entry["require_dragon_nonfalling"],
            contract["require_dragon_nonfalling"],
        )
        self.assertEqual(exit_rule["label"], contract["exit_label"])
        self.assertEqual(exit_rule["activation"], contract["profit_activation_pct"])
        self.assertEqual(exit_rule["drawdown"], contract["trailing_drawdown_pct"])
        self.assertEqual(
            exit_rule["weakening_confirm"],
            contract["weakening_confirmation_occurrences"],
        )
        self.assertEqual(
            exit_rule["exit_on_erasure"],
            contract["exit_on_true_erasure"],
        )

    def test_frozen_hybrid_exit_reason_identifies_line_weakening(self):
        points = [
            point(1, close=10.0, dragon=12.0, tiger=10.0, base_signal=True),
            point(2, close=10.2, dragon=11.8, tiger=10.1),
            point(3, close=10.3, dragon=11.6, tiger=10.2),
        ]
        rule = next(
            item
            for item in EXIT_RULES
            if item["id"] == "wave_erasure_hybrid_or_10_10_weakening"
        )

        reason = exit_reason_for_trade(points, 0, 0, 10.0, 2, rule)

        self.assertEqual(reason, "dragon_tiger_weakening")

    def test_frozen_hybrid_checks_weakening_on_the_entry_day_close(self):
        points = [
            point(1, close=10.0, dragon=12.0, tiger=10.0, base_signal=True),
            point(2, close=10.1, dragon=11.8, tiger=10.1),
            point(3, close=10.2, dragon=11.6, tiger=10.2),
            point(4, close=10.3, dragon=11.4, tiger=10.3),
            point(5, close=10.4, dragon=11.3, tiger=10.3),
        ]
        rule = next(
            item
            for item in EXIT_RULES
            if item["id"] == "wave_erasure_hybrid_or_10_10_weakening"
        )

        exit_index = exit_for_rule(points, 0, 3, 10.3, 4, rule)
        reason = exit_reason_for_trade(points, 0, 3, 10.3, exit_index, rule)

        self.assertEqual(exit_index, 3)
        self.assertEqual(reason, "dragon_tiger_weakening")

    def test_low_risk_filter_rejects_a_falling_dragon_line(self):
        points = [
            point(1, close=10.0, dragon=9.8, tiger=9.0, base_signal=True),
            point(2, close=10.05, dragon=9.9, tiger=9.0),
            point(3, close=10.1, dragon=9.7, tiger=9.0),
        ]
        method = next(item for item in ENTRY_METHODS if item["id"] == "low_risk_2")
        self.assertIsNone(entry_for_method(points, bars(points), 0, method))

    def test_long_wave_exit_uses_signal_erasure_before_other_conditions(self):
        points = [
            point(1, close=10.0, base_signal=True, cross_ok=True),
            point(2, close=10.2, cross_ok=True),
            point(3, close=10.0, cross_ok=False),
            point(4, close=9.0, cross_ok=False),
            point(5, close=9.2, cross_ok=False),
            point(6, close=9.1, cross_ok=False),
        ]
        history = [
            Bar("2026-07-01", 10.0, 10.1, 9.9, 10.0, 1000.0, 10000.0),
            Bar("2026-07-02", 10.1, 10.3, 10.0, 10.2, 1000.0, 10000.0),
            Bar("2026-07-03", 10.0, 10.1, 9.9, 10.0, 1000.0, 10000.0),
            Bar("2026-07-04", 9.0, 9.0, 9.0, 9.0, 1000.0, 10000.0),
            Bar("2026-07-05", 9.2, 9.3, 9.1, 9.2, 1000.0, 10000.0),
            Bar("2026-07-06", 9.1, 9.2, 9.0, 9.1, 1000.0, 10000.0),
        ]
        assumptions = ExecutionAssumptions(
            commission_bps_per_side=0.0,
            exchange_fee_bps_per_side=0.0,
            regulatory_fee_bps_per_side=0.0,
            stamp_duty_bps_sell=0.0,
            slippage_bps_per_side=0.0,
        )
        rule = next(
            item for item in EXIT_RULES
            if item["id"] == "wave_erasure_adaptive_5_8"
        )

        trade = joint_trade_for_setup(
            Stock(1, "600001", "示例"),
            history,
            points,
            0,
            next(item for item in ENTRY_METHODS if item["id"] == "signal_close"),
            rule,
            assumptions,
        )

        self.assertEqual(trade["entry_index"], 1)
        self.assertEqual(trade["exit_trigger_index"], 2)
        self.assertEqual(trade["exit_index"], 4)
        self.assertEqual(trade["exit_deferred_bars"], 1)
        self.assertEqual(trade["exit_reason"], "signal_recalculated_away")

    def test_long_wave_ma_exit_waits_for_two_confirming_closes(self):
        closes = [10.0] * 10 + [11.0, 12.0, 11.0, 9.0, 8.5, 8.0, 7.5, 7.4]
        points = [
            point(day, close=close, dragon=11.0, tiger=10.0)
            for day, close in enumerate(closes, start=1)
        ]
        rule = next(
            item for item in EXIT_RULES
            if item["id"] == "wave_erasure_ma_5_10"
        )

        exit_index = exit_for_rule(
            points,
            setup_index=9,
            entry_index=9,
            entry_price=10.0,
            hard_end=17,
            rule=rule,
        )

        self.assertEqual(exit_index, 16)

    def test_structure_exit_is_reachable_without_an_ma_condition(self):
        closes = [10.0, 10.1, 10.2, 10.3, 10.4, 9.5, 9.0]
        dragons = [11.0, 11.1, 11.2, 11.3, 11.4, 11.3, 11.2]
        points = [
            point(index + 1, close=close, dragon=dragon, tiger=10.0)
            for index, (close, dragon) in enumerate(zip(closes, dragons))
        ]
        rule = next(
            item for item in EXIT_RULES if item["id"] == "wave_erasure_structure_5"
        )

        self.assertNotIn("require_ma_and_structure", rule)
        points.append(point(8, close=8.8, dragon=11.1, tiger=10.0))
        self.assertEqual(exit_for_rule(points, 0, 0, 10.0, 7, rule), 6)

    def test_hybrid_exit_can_use_earlier_or_later_of_price_and_line_weakness(self):
        points = [
            point(1, close=10.0, dragon=12.0, tiger=10.0),
            point(2, close=10.5, dragon=11.8, tiger=10.1),
            point(3, close=10.7, dragon=11.6, tiger=10.2),
            point(4, close=11.0, dragon=11.7, tiger=10.2),
            point(5, close=10.4, dragon=11.8, tiger=10.2),
        ]
        either = next(
            item
            for item in EXIT_RULES
            if item["id"] == "wave_erasure_hybrid_or_10_5_weakening"
        )
        both = next(
            item
            for item in EXIT_RULES
            if item["id"] == "wave_erasure_hybrid_and_10_5_weakening"
        )

        either_index = exit_for_rule(points, 0, 0, 10.0, 4, either)
        both_index = exit_for_rule(points, 0, 0, 10.0, 4, both)

        self.assertEqual(either_index, 2)
        self.assertEqual(both_index, 4)

    def test_long_wave_family_selection_does_not_read_2026_holdout(self):
        def candidate(identifier: str, floor: float, holdout: float) -> dict:
            period = {
                "sample_count": 250,
                "geometric_average_pct": floor,
                "positive_rate_pct": 60.0,
                "average_excluding_abs_50pct_outliers_pct": floor,
            }
            return {
                "id": identifier,
                "entry_id": "signal_close",
                "exit_id": "wave_erasure_trail_5_8",
                "development_before_2024": dict(period),
                "validation_2024_2025": dict(period),
                "holdout_2026": {"sample_count": 999, "average_pct": holdout},
            }

        first = [candidate("a", 2.0, -99.0), candidate("b", 1.0, 99.0)]
        second = [candidate("a", 2.0, 99.0), candidate("b", 1.0, -99.0)]

        self.assertEqual(user_long_wave_summary(first)["balanced_id"], "a")
        self.assertEqual(user_long_wave_summary(second)["balanced_id"], "a")
        self.assertEqual(FROZEN_LIVE_STRATEGY_ID, LIVE_STRATEGY_ID)
        self.assertEqual(
            FROZEN_CANDIDATE_ID,
            "low_risk_2__wave_erasure_hybrid_or_10_10_weakening",
        )

    def test_wave_capture_reports_peak_giveback_and_realized_share(self):
        samples = WaveCaptureSamples()
        samples.add(net_return=8.0, peak_close_return=10.0)
        samples.add(net_return=3.0, peak_close_return=6.0)

        result = wave_capture_stats(samples)

        self.assertEqual(result["median_peak_giveback_pct"], 2.5)
        self.assertEqual(result["median_net_capture_ratio_pct"], 65.0)

    def test_wave_capture_uses_the_full_relationship_wave_as_the_ceiling(self):
        samples = WaveCaptureSamples()
        samples.add(
            net_return=8.0,
            peak_close_return=10.0,
            full_wave_peak_close_return=20.0,
        )
        samples.add(
            net_return=3.0,
            peak_close_return=6.0,
            full_wave_peak_close_return=6.0,
        )

        result = wave_capture_stats(samples)

        self.assertEqual(result["median_pre_exit_peak_close_return_pct"], 8.0)
        self.assertEqual(result["median_peak_close_return_pct"], 13.0)
        self.assertEqual(result["median_peak_giveback_pct"], 7.5)
        self.assertEqual(result["median_net_capture_ratio_pct"], 45.0)


if __name__ == "__main__":
    unittest.main()
