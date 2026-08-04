from __future__ import annotations

import random
import unittest

from rolling_validation import (
    CausalLineState,
    ExecutionAssumptions,
    SignalPoint,
    forward_returns,
    lifecycle_trade_stats,
    replay_signals,
    next_open_fill,
    simulate_lifecycle_trades,
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
        cross_ok: bool = True,
        cross_age: int = -1,
        cross_lookback_days: int = 0,
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
            yellow_ok=base_signal or bool(area),
            cross_age=cross_age,
            cross_lookback_days=cross_lookback_days,
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

    def test_signal_label_expiry_and_true_trend_end_are_separate(self):
        points = [
            self.point(1, 11, 10, "secondary", 10.0, cross_ok=True),
            self.point(2, 11.2, 10, "", 10.2, cross_ok=False),
            self.point(3, 9.8, 10, "", 10.4, cross_ok=False),
            *[
                self.point(day, 9.8, 10, "", 10.4, cross_ok=False)
                for day in range(4, 62)
            ],
        ]
        literal = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {"id": "signal_window_end", "signal_expiry_exit": True},
        )
        relationship = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {"id": "death_cross"},
        )
        self.assertEqual(literal[0]["exit_date"], "2026-07-02")
        self.assertEqual(relationship[0]["exit_date"], "2026-07-03")
        self.assertEqual(relationship[0]["exit_reason"], "龙线不再高于虎线")

    def test_recalculated_signal_erasure_exits_before_natural_expiry(self):
        points = [
            self.point(
                1,
                11,
                10,
                "secondary",
                10.0,
                cross_age=2,
                cross_lookback_days=5,
            ),
            self.point(2, 11.2, 10, "", 9.8, cross_ok=False),
            *[
                self.point(day, 11.2, 10, "", 9.8, cross_ok=False)
                for day in range(3, 63)
            ],
        ]
        rows = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {"id": "death_cross", "exit_on_erasure": True},
        )
        self.assertEqual(rows[0]["exit_date"], "2026-07-02")
        self.assertEqual(
            rows[0]["exit_reason"],
            "龙腾跃虎信号被K线重算消失",
        )

    def test_natural_cross_label_expiry_does_not_end_a_persistent_trend(self):
        points = [
            self.point(
                1,
                11,
                10,
                "secondary",
                10.0,
                cross_age=4,
                cross_lookback_days=5,
            ),
            self.point(2, 11.2, 10, "", 10.2, cross_ok=False),
            self.point(3, 9.8, 10, "", 10.1, cross_ok=False),
            *[
                self.point(day, 9.8, 10, "", 10.1, cross_ok=False)
                for day in range(4, 63)
            ],
        ]
        rows = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {"id": "death_cross"},
        )
        self.assertEqual(rows[0]["exit_date"], "2026-07-03")
        self.assertEqual(rows[0]["exit_reason"], "龙线不再高于虎线")

    def test_entry_can_wait_for_signal_to_remain_selected(self):
        points = [
            self.point(1, 11, 10, "secondary", 10.0),
            self.point(2, 11.2, 10, "secondary", 10.2),
            self.point(3, 9.8, 10, "", 10.1),
            *[
                self.point(day, 9.8, 10, "", 10.1)
                for day in range(4, 63)
            ],
        ]
        rows = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {"id": "confirmed_entry", "entry_confirmation_days": 1},
        )
        self.assertEqual(rows[0]["entry_date"], "2026-07-02")
        self.assertEqual(rows[0]["entry_confirmation_days"], 1)

    def test_entry_can_wait_for_price_to_confirm_trend_start(self):
        points = [
            self.point(1, 11, 10, "secondary", 10.0),
            self.point(2, 11.2, 10, "", 10.2),
            self.point(3, 11.4, 10, "", 10.4),
            self.point(4, 9.8, 10, "", 10.3),
            *[
                self.point(day, 9.8, 10, "", 10.3)
                for day in range(5, 64)
            ],
        ]
        rows = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {
                "id": "breakout_entry",
                "entry_breakout_pct": 3.0,
                "entry_max_wait_bars": 10,
            },
        )
        self.assertEqual(rows[0]["signal_setup_date"], "2026-07-01")
        self.assertEqual(rows[0]["entry_date"], "2026-07-03")
        self.assertEqual(rows[0]["entry_price"], 10.4)

    def test_lifecycle_trailing_rule_still_ends_on_relationship_loss(self):
        points = [
            self.point(1, 11, 10, "main", 10.0),
            self.point(2, 12, 10, "", 10.6),
            self.point(3, 9, 10, "", 10.4),
            *[
                self.point(day, 9, 10, "", 10.4)
                for day in range(4, 62)
            ],
        ]
        rows = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {
                "id": "trail",
                "activation_threshold_pct": 5.0,
                "trailing_drawdown_pct": 5.0,
            },
        )
        self.assertEqual(rows[0]["exit_date"], "2026-07-03")
        self.assertEqual(rows[0]["exit_reason"], "龙线不再高于虎线")

    def test_lifecycle_trailing_rule_can_require_two_closes(self):
        closes = [10.0, 11.0, 10.4, 10.3] + [10.3] * 58
        points = [
            self.point(
                day,
                11,
                10,
                "main" if day == 1 else "",
                close,
            )
            for day, close in enumerate(closes, start=1)
        ]
        rows = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {
                "id": "confirmed_trail",
                "activation_threshold_pct": 5.0,
                "trailing_drawdown_pct": 5.0,
                "trailing_confirm_days": 2,
            },
        )
        self.assertEqual(rows[0]["exit_date"], "2026-07-04")
        self.assertIn("连续确认2日", rows[0]["exit_reason"])

    def test_lifecycle_trailing_rule_can_wait_five_bars(self):
        closes = [10.0, 11.0, 10.4, 10.3, 10.2, 10.1] + [10.1] * 56
        points = [
            self.point(
                day,
                11,
                10,
                "main" if day == 1 else "",
                close,
            )
            for day, close in enumerate(closes, start=1)
        ]
        rows = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {
                "id": "minimum_hold_trail",
                "activation_threshold_pct": 5.0,
                "trailing_drawdown_pct": 5.0,
                "minimum_holding_bars": 5,
            },
        )
        self.assertEqual(rows[0]["exit_date"], "2026-07-06")

    def test_lifecycle_success_uses_only_completed_entry_to_exit_return(self):
        stats = lifecycle_trade_stats(
            [
                {
                    "return_pct": 5.0,
                    "best_return_pct": 8.0,
                    "worst_return_pct": -1.0,
                    "days_to_peak": 2,
                    "peak_to_exit_bars": 1,
                    "holding_bars": 3,
                    "peak_giveback_pct": 3.0,
                    "pending_days": 1,
                },
                {
                    "return_pct": -2.0,
                    "best_return_pct": 1.0,
                    "worst_return_pct": -3.0,
                    "days_to_peak": 1,
                    "peak_to_exit_bars": 2,
                    "holding_bars": 3,
                    "peak_giveback_pct": 3.0,
                    "pending_days": 2,
                },
            ]
        )
        self.assertEqual(stats["success_rate_pct"], 50.0)
        self.assertEqual(stats["sample_count"], 2)

    def test_joint_lifecycle_fills_entry_and_exit_at_following_opens(self):
        points = [
            self.point(1, 11, 10, "main", 10.0),
            self.point(2, 11.2, 10, "", 11.1),
            self.point(3, 9.8, 10, "", 10.7),
            self.point(4, 9.7, 10, "", 10.4),
            self.point(5, 9.6, 10, "", 10.3),
            self.point(6, 9.5, 10, "", 10.2),
        ]
        opens = [10.0, 11.0, 10.8, 10.5, 10.3, 10.2]
        history = [
            Bar(
                date=point.date,
                open=open_price,
                high=max(open_price, point.close) + 0.1,
                low=min(open_price, point.close) - 0.1,
                close=point.close,
                volume=1000.0,
                amount=10000.0,
            )
            for point, open_price in zip(points, opens)
        ]
        assumptions = ExecutionAssumptions(
            commission_bps_per_side=3.0,
            exchange_fee_bps_per_side=0.341,
            regulatory_fee_bps_per_side=0.2,
            stamp_duty_bps_sell=5.0,
            slippage_bps_per_side=5.0,
        )
        rows = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {"id": "death_cross"},
            horizon=2,
            bars=history,
            execution=assumptions,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry_trigger_date"], "2026-07-01")
        self.assertEqual(rows[0]["entry_date"], "2026-07-02")
        self.assertEqual(rows[0]["exit_trigger_date"], "2026-07-03")
        self.assertEqual(rows[0]["exit_date"], "2026-07-04")
        self.assertEqual(rows[0]["entry_raw_open"], 11.0)
        self.assertEqual(rows[0]["exit_raw_open"], 10.5)
        self.assertGreater(rows[0]["entry_price"], 11.0)
        self.assertLess(rows[0]["exit_price"], 10.5)

    def test_limit_locked_orders_defer_and_buy_wait_is_capped(self):
        stock = Stock(1, "600001", "示例")
        history = [
            Bar("2026-07-01", 10.0, 10.1, 9.9, 10.0, 1000.0, 10000.0),
            Bar("2026-07-02", 11.0, 11.0, 11.0, 11.0, 1000.0, 10000.0),
            Bar("2026-07-03", 10.8, 10.9, 10.7, 10.8, 1000.0, 10000.0),
        ]
        zero_cost = ExecutionAssumptions(
            commission_bps_per_side=0.0,
            exchange_fee_bps_per_side=0.0,
            regulatory_fee_bps_per_side=0.0,
            stamp_duty_bps_sell=0.0,
            slippage_bps_per_side=0.0,
            entry_execution_max_wait_bars=5,
        )
        fill = next_open_fill(stock, history, 0, "buy", zero_cost)
        self.assertEqual(fill.index, 2)
        self.assertEqual(fill.deferred_bars, 1)
        capped = ExecutionAssumptions(**{
            **{key: value for key, value in vars(zero_cost).items() if key != "entry_execution_max_wait_bars"},
            "entry_execution_max_wait_bars": 1,
        })
        self.assertIsNone(next_open_fill(stock, history, 0, "buy", capped))

        down_history = [
            Bar("2026-07-01", 10.0, 10.1, 9.9, 10.0, 1000.0, 10000.0),
            Bar("2026-07-02", 9.0, 9.0, 9.0, 9.0, 1000.0, 10000.0),
            Bar("2026-07-03", 8.9, 9.0, 8.8, 8.9, 1000.0, 10000.0),
        ]
        sell_fill = next_open_fill(stock, down_history, 0, "sell", capped)
        self.assertEqual(sell_fill.index, 2)
        self.assertEqual(sell_fill.deferred_bars, 1)

    def test_frozen_live_rule_uses_break5_trigger_and_next_open_chain(self):
        closes = [10.0, 10.3, 10.5, 10.8, 10.55, 10.5, 10.4, 10.3, 10.2]
        points = [
            self.point(
                day,
                11.0,
                10.0,
                "secondary" if day == 1 else "",
                close,
                cross_age=0 if day == 1 else -1,
                cross_lookback_days=8 if day == 1 else 0,
            )
            for day, close in enumerate(closes, start=1)
        ]
        opens = [10.0, 10.1, 10.4, 10.6, 10.7, 10.5, 10.4, 10.3, 10.2]
        highs = [10.2, 10.35, 10.6, 10.9, 10.65, 10.6, 10.5, 10.4, 10.3]
        history = [
            Bar(
                date=point.date,
                open=open_price,
                high=high,
                low=min(open_price, point.close) - 0.1,
                close=point.close,
                volume=1000.0,
                amount=10000.0,
            )
            for point, open_price, high in zip(points, opens, highs)
        ]
        zero_cost = ExecutionAssumptions(
            commission_bps_per_side=0.0,
            exchange_fee_bps_per_side=0.0,
            regulatory_fee_bps_per_side=0.0,
            stamp_duty_bps_sell=0.0,
            slippage_bps_per_side=0.0,
        )
        rows = simulate_lifecycle_trades(
            Stock(1, "600001", "示例"),
            points,
            {
                "id": "break5_trail3_2_next_open_v2",
                "entry_recent_high_lookback": 5,
                "entry_max_wait_bars": 10,
                "activation_threshold_pct": 3.0,
                "trailing_drawdown_pct": 2.0,
            },
            horizon=5,
            bars=history,
            execution=zero_cost,
        )
        self.assertEqual(rows[0]["entry_trigger_date"], "2026-07-02")
        self.assertEqual(rows[0]["entry_date"], "2026-07-03")
        self.assertEqual(rows[0]["exit_trigger_date"], "2026-07-05")
        self.assertEqual(rows[0]["exit_date"], "2026-07-06")


if __name__ == "__main__":
    unittest.main()
