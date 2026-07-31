import math
import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from screener import Bar, Stock, append_line_coefficients, cross_yellow_pair, ema, has_yellow_segment, is_intraday_snapshot, is_st_name, limit_up_price, line_series, load_config, make_sparkline, price_limit_rate, rolling_cci, xma


class SignalMathTests(unittest.TestCase):
    def test_ema_known_values(self):
        self.assertEqual(ema([1, 2, 3], 3), [1.0, 1.5, 2.25])

    def test_price_limit_rounding_and_boards(self):
        self.assertEqual(limit_up_price(10.01, price_limit_rate(Stock(1, "600000", "浦发银行"))), 11.01)
        self.assertEqual(price_limit_rate(Stock(0, "300001", "特锐德")), Decimal("0.20"))
        self.assertEqual(price_limit_rate(Stock(1, "600000", "ST示例")), Decimal("0.05"))

    def test_st_is_excluded_and_limit_up_window_is_two_months(self):
        self.assertTrue(is_st_name("*ST示例"))
        self.assertTrue(is_st_name("ST示例"))
        self.assertFalse(is_st_name("普通股票"))
        config = load_config(ROOT / "config.json")
        self.assertFalse(config["include_st"])
        self.assertEqual(config["limit_up_lookback_days"], 42)
        self.assertEqual(config["yellow_consecutive_days"], 1)
        self.assertEqual(config["near_match_minimum"], 3)

    def test_cci_has_warmup(self):
        bars = [Bar(f"2026-01-{i:02d}", i, i + 1, i - 1, i, 1, 1) for i in range(1, 20)]
        cci = rolling_cci(bars)
        self.assertTrue(all(math.isnan(x) for x in cci[:13]))
        self.assertTrue(all(math.isfinite(x) for x in cci[13:]))

    def test_xma_uses_centered_partial_windows(self):
        self.assertEqual(xma([1, 2, 3, 4, 5], 3), [1.5, 2.0, 3.0, 4.0, 4.5])

    def test_next_bar_line_coefficients_match_full_formula(self):
        bars = [
            Bar(
                f"2026-01-{(i % 28) + 1:02d}",
                10 + i * 0.02,
                10.6 + i * 0.02,
                9.5 + i * 0.02,
                10.1 + i * 0.02,
                1,
                1,
            )
            for i in range(100)
        ]
        coefficients = append_line_coefficients(bars)
        low, high = 11.2, 12.7
        probe = Bar("2026-07-31", 12.0, high, low, 12.3, 1, 1)
        dragon, tiger = line_series([*bars, probe])

        def value(parts):
            return parts[0] + parts[1] * low + parts[2] * high

        self.assertAlmostEqual(value(coefficients["dragon"]), dragon[-1], places=8)
        self.assertAlmostEqual(value(coefficients["tiger"]), tiger[-1], places=8)
        self.assertAlmostEqual(
            value(coefficients["previous_dragon"]),
            dragon[-2],
            places=8,
        )
        self.assertAlmostEqual(
            value(coefficients["previous_tiger"]),
            tiger[-2],
            places=8,
        )
        for parts, expected in zip(coefficients["dragon_tail"], dragon[-6:]):
            self.assertAlmostEqual(value(parts), expected, places=8)
        for parts, expected in zip(coefficients["tiger_tail"], tiger[-6:]):
            self.assertAlmostEqual(value(parts), expected, places=8)

    def test_partial_body_below_dragon_is_yellow(self):
        bar = Bar("2026-07-22", 10.60, 10.72, 10.21, 10.25, 1, 1)
        self.assertFalse(has_yellow_segment(bar, 10.25))
        self.assertTrue(has_yellow_segment(bar, 10.26))

    def test_cross_pairs_with_yellow_in_two_day_neighborhood(self):
        cross = [False, False, False, True, False, False]
        for yellow_index in (1, 2, 3, 4, 5):
            yellow = [False] * 6
            yellow[yellow_index] = True
            pair = cross_yellow_pair(
                cross,
                yellow,
                end_index=5,
                cross_lookback_days=5,
                yellow_consecutive_days=1,
            )
            self.assertEqual(pair[0], 3)

    def test_cross_does_not_pair_with_yellow_three_days_away(self):
        pair = cross_yellow_pair(
            [False, False, False, True, False, False, False],
            [True, False, False, False, False, False, False],
            end_index=6,
            cross_lookback_days=5,
            yellow_consecutive_days=1,
        )
        self.assertEqual(pair, (-1, -1, 0))

    def test_intraday_snapshot_guard(self):
        self.assertTrue(is_intraday_snapshot("2026-07-21", datetime(2026, 7, 21, 10, 0)))
        self.assertFalse(is_intraday_snapshot("2026-07-21", datetime(2026, 7, 21, 15, 25)))
        self.assertFalse(is_intraday_snapshot("2026-07-20", datetime(2026, 7, 21, 10, 0)))

    def test_chart_contains_candles_lines_dates_and_yellow_bar(self):
        bars = [
            Bar("2026-07-17", 10.0, 10.8, 9.8, 10.5, 1, 1),
            Bar("2026-07-20", 10.5, 11.0, 10.2, 10.3, 1, 1),
        ]
        chart = make_sparkline(bars, [10.2, 10.4], [9.8, 10.0])
        self.assertEqual(chart.count('class="kbar '), 2)
        self.assertIn('class="kbar yellow"', chart)
        self.assertIn('class="yellow-part"', chart)
        self.assertIn("开10.00 高10.80 低9.80 收10.50", chart)
        self.assertIn("07-17", chart)
        self.assertIn("07-20", chart)
        self.assertIn("龙线和虎线", chart)
        self.assertIn('stroke="#ff5c70" stroke-width="2"', chart)
        self.assertIn('stroke="#55c6e8" stroke-width="2"', chart)


if __name__ == "__main__":
    unittest.main()
