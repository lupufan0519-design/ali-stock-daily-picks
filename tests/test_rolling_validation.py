from __future__ import annotations

import random
import unittest

from rolling_validation import (
    CausalLineState,
    SignalPoint,
    forward_returns,
    replay_signals,
    simulate_trades,
)
from screener import Bar, Stock, line_series


def bars(count: int) -> list[Bar]:
    random.seed(17)
    price = 12.0
    rows = []
    for index in range(count):
        price = max(2.0, price + random.uniform(-0.5, 0.55))
        open_price = price + random.uniform(-0.2, 0.2)
        close = price + random.uniform(-0.2, 0.2)
        rows.append(
            Bar(
                date=f"2026-01-{index + 1:02d}",
                open=open_price,
                high=max(open_price, close) + random.uniform(0.05, 0.4),
                low=min(open_price, close) - random.uniform(0.05, 0.4),
                close=close,
                volume=1000.0,
                amount=10000.0,
            )
        )
    return rows


class CausalLineTests(unittest.TestCase):
    def test_incremental_state_matches_exact_prefix_recalculation(self):
        history = bars(90)
        state = CausalLineState()
        for index, bar in enumerate(history):
            state.append(bar)
            expected_dragon, expected_tiger = line_series(
                history[: index + 1]
            )
            self.assertEqual(len(state.dragon), len(expected_dragon))
            for actual, expected in zip(state.dragon, expected_dragon):
                self.assertAlmostEqual(actual, expected, places=9)
            for actual, expected in zip(state.tiger, expected_tiger):
                self.assertAlmostEqual(actual, expected, places=9)

    def test_replay_does_not_change_when_future_bars_are_appended(self):
        history = bars(130)
        stock = Stock(1, "600001", "示例")
        cfg = {
            "bottom_lookback_days": 5,
            "cross_lookback_days": 5,
            "limit_up_lookback_days": 42,
            "yellow_consecutive_days": 1,
            "minimum_history_bars": 100,
        }
        before = replay_signals(stock, history[:115], cfg)
        after = replay_signals(stock, history, cfg)
        self.assertEqual(before, after[:115])


class ExitRuleTests(unittest.TestCase):
    @staticmethod
    def point(
        day: int,
        dragon: float,
        tiger: float,
        area: str = "",
        close: float = 10.0,
        base_signal: bool = False,
    ) -> SignalPoint:
        return SignalPoint(
            date=f"2026-07-{day:02d}",
            close=close,
            dragon=dragon,
            tiger=tiger,
            area=area,
            base_signal=base_signal,
            endpoint_cross=False,
        )

    def test_secondary_promotion_is_not_an_exit(self):
        points = [
            self.point(1, 11, 10, "secondary", 10.0),
            self.point(2, 12, 10, "main", 10.5),
            self.point(3, 9, 10, "", 10.8),
        ]
        closed, open_rows = simulate_trades(
            Stock(1, "600001", "示例"),
            points,
            "death_cross_1",
        )
        self.assertEqual(open_rows, [])
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["entry_area"], "secondary")
        self.assertTrue(closed[0]["promoted"])
        self.assertEqual(closed[0]["exit_date"], "2026-07-03")

    def test_second_day_rule_waits_for_confirmation(self):
        points = [
            self.point(1, 11, 10, "main", 10.0),
            self.point(2, 9.9, 10, "", 9.8),
            self.point(3, 9.8, 10, "", 10.2),
        ]
        closed, _ = simulate_trades(
            Stock(1, "600001", "示例"),
            points,
            "death_cross_2",
        )
        self.assertEqual(closed[0]["exit_date"], "2026-07-03")

    def test_weakening_rule_exits_before_cross(self):
        points = [
            self.point(1, 13.0, 10.0, "main", 10.0),
            self.point(2, 12.0, 10.0, "", 10.5),
            self.point(3, 11.0, 10.0, "", 10.2),
        ]
        closed, _ = simulate_trades(
            Stock(1, "600001", "示例"),
            points,
            "weakening_or_cross",
        )
        self.assertEqual(closed[0]["exit_date"], "2026-07-03")

    def test_weakening_rule_does_not_use_pre_entry_days(self):
        points = [
            self.point(1, 14.0, 10.0, "", 9.8),
            self.point(2, 13.0, 10.0, "main", 10.0),
            self.point(3, 12.0, 10.0, "", 10.2),
            self.point(4, 11.0, 10.0, "", 10.1),
        ]
        closed, _ = simulate_trades(
            Stock(1, "600001", "示例"),
            points,
            "weakening_or_cross",
        )
        self.assertEqual(closed[0]["exit_date"], "2026-07-04")

    def test_base_signal_enters_without_pool_conditions(self):
        points = [
            self.point(1, 11, 10, close=10.0, base_signal=True),
            self.point(2, 12, 10, close=11.0, base_signal=True),
            self.point(3, 9, 10, close=10.5),
        ]
        closed, _ = simulate_trades(
            Stock(1, "600001", "示例"),
            points,
            "death_cross_1",
            entry_mode="base",
        )
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["entry_area"], "base")
        self.assertEqual(closed[0]["entry_date"], "2026-07-01")
        self.assertEqual(closed[0]["peak_date"], "2026-07-02")
        self.assertEqual(closed[0]["days_to_peak"], 1)
        self.assertEqual(closed[0]["peak_to_exit_bars"], 1)

    def test_forward_returns_count_one_start_per_bull_cycle(self):
        points = [
            self.point(1, 11, 10, close=10.0, base_signal=True),
            self.point(2, 12, 10, close=10.2, base_signal=True),
            self.point(3, 13, 10, close=10.4, base_signal=True),
            self.point(4, 9, 10, close=10.1),
            self.point(5, 11, 10, close=10.3, base_signal=True),
            self.point(6, 12, 10, close=10.5),
        ]
        rows = forward_returns(
            Stock(1, "600001", "示例"),
            points,
            horizons=(1,),
        )
        self.assertEqual([row["signal_date"] for row in rows], [
            "2026-07-01",
            "2026-07-05",
        ])


if __name__ == "__main__":
    unittest.main()
