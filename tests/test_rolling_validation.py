from __future__ import annotations

import random
import unittest

from rolling_validation import (
    CausalLineState,
    SignalPoint,
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
    ) -> SignalPoint:
        return SignalPoint(
            date=f"2026-07-{day:02d}",
            close=close,
            dragon=dragon,
            tiger=tiger,
            area=area,
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


if __name__ == "__main__":
    unittest.main()
