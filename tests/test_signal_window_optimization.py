from __future__ import annotations

import unittest
from unittest.mock import patch

from rolling_validation import SignalPoint
from screener import Bar, Stock
from signal_failure_examples import failure_rows
from signal_repaint_comparison import measurement
from signal_window_optimization import (
    WaveSamples,
    append_wave_sample,
    exit_for_rule,
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
) -> SignalPoint:
    return SignalPoint(
        date=f"2026-07-{day:02d}",
        close=close,
        dragon=dragon,
        tiger=tiger,
        area="",
        base_signal=base_signal,
        endpoint_cross=False,
        cross_ok=cross_ok,
        yellow_ok=base_signal,
        cross_age=cross_age,
        cross_lookback_days=cross_lookback_days,
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
        points = [point(day, close=10.0) for day in range(1, 72)]
        points[0] = point(1, close=-1.0, base_signal=True)
        measured = measurement(points, bars(points), 0)
        self.assertEqual(measured, {"excluded_nonpositive_price": True})

    def test_failure_examples_exclude_nonpositive_adjusted_prices(self):
        points = [point(day, close=10.0) for day in range(1, 72)]
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


if __name__ == "__main__":
    unittest.main()
