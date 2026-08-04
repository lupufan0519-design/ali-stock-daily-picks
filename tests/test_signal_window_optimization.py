from __future__ import annotations

import unittest
from unittest.mock import patch

from rolling_validation import ExecutionAssumptions, SignalPoint
from screener import Bar, Stock
from signal_failure_examples import failure_rows
from signal_repaint_comparison import measurement
from signal_window_optimization import (
    WaveSamples,
    append_wave_sample,
    balanced_candidate,
    entry_for_method,
    exit_for_rule,
    joint_trade_for_setup,
    risk_exit_index,
    signal_indices,
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

    def test_same_cross_reappearance_is_consumed_but_new_cross_is_counted(self):
        points = [
            point(1, area="secondary", cross_date="2026-06-30"),
            point(2),
            point(3, area="secondary", cross_date="2026-06-30"),
            point(4),
            point(5, area="main", cross_date="2026-07-04"),
        ]
        self.assertEqual(signal_indices(points, "pool"), [0, 4])

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

    def test_blocked_buy_is_cancelled_when_a_different_cross_replaces_setup(self):
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


if __name__ == "__main__":
    unittest.main()
