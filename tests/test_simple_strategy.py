import unittest

from simple_strategy import FIRST_TIER, SECOND_TIER, THIRD_TIER, classify_tier, split_tiers


CFG = {"line_gap_max_abs": 0.5}


def row(**updates):
    value = {
        "code": "600001",
        "name": "普通股票",
        "eligible": True,
        "bottom_ok": True,
        "price": 9.0,
        "dragon_value": 10.0,
        "tiger_value": 10.2,
        "yellow_line_value": 10.4,
        "prior_three_gap_abs": [0.1, 0.3, 0.5],
    }
    value.update(updates)
    return value


class SimpleStrategyTests(unittest.TestCase):
    def test_first_tier_requires_all_three_completed_days_within_threshold(self):
        self.assertEqual(classify_tier(row(), CFG), FIRST_TIER)
        self.assertEqual(
            classify_tier(row(prior_three_gap_abs=[0.1, 0.51, 0.2]), CFG),
            SECOND_TIER,
        )
        self.assertEqual(
            classify_tier(
                row(
                    prior_three_gap_abs=[0.1, 0.51, 0.2],
                    price=11.0,
                ),
                CFG,
            ),
            THIRD_TIER,
        )

    def test_current_day_gap_does_not_change_first_tier(self):
        self.assertEqual(
            classify_tier(row(dragon_value=20.0, tiger_value=10.0), CFG),
            FIRST_TIER,
        )

    def test_second_tier_only_requires_price_not_above_yellow_line(self):
        base = row(prior_three_gap_abs=[0.1, 0.6, 0.2])
        self.assertEqual(classify_tier(base, CFG), SECOND_TIER)
        self.assertEqual(
            classify_tier(
                {
                    **base,
                    "price": 10.1,
                    "dragon_value": 9.5,
                    "tiger_value": 9.6,
                },
                CFG,
            ),
            SECOND_TIER,
        )
        self.assertEqual(classify_tier({**base, "price": 10.5}, CFG), THIRD_TIER)

    def test_third_tier_collects_remaining_recent_bottom_signals(self):
        candidate = row(
            price=10.5,
            prior_three_gap_abs=[0.1, 0.6, 0.2],
        )
        self.assertEqual(classify_tier(candidate, CFG), THIRD_TIER)

    def test_first_tier_wins_when_both_rules_match(self):
        pools = split_tiers([row()], CFG)
        self.assertEqual(len(pools[FIRST_TIER]), 1)
        self.assertEqual(len(pools[SECOND_TIER]), 0)
        self.assertEqual(len(pools[THIRD_TIER]), 0)

    def test_bottom_and_st_filters_are_hard_requirements(self):
        self.assertEqual(classify_tier(row(bottom_ok=False), CFG), "")
        self.assertEqual(classify_tier(row(name="*ST示例"), CFG), "")


    def test_every_tier_sorts_by_absolute_bottom_price_gap(self):
        rows = [
            row(code="600003", bottom_price=8.0, price=9.0),
            row(code="600001", bottom_price=8.8, price=9.0),
            row(code="600002", bottom_price=8.5, price=9.0),
            row(code="600013", bottom_price=8.0, price=9.0, prior_three_gap_abs=[0.1, 0.6, 0.2]),
            row(code="600011", bottom_price=8.8, price=9.0, prior_three_gap_abs=[0.1, 0.6, 0.2]),
            row(code="600023", bottom_price=8.0, price=11.0, prior_three_gap_abs=[0.1, 0.6, 0.2]),
            row(code="600021", bottom_price=10.8, price=11.0, prior_three_gap_abs=[0.1, 0.6, 0.2]),
        ]
        pools = split_tiers(rows, CFG)
        self.assertEqual([item["code"] for item in pools[FIRST_TIER]], ["600001", "600002", "600003"])
        self.assertEqual([item["code"] for item in pools[SECOND_TIER]], ["600011", "600013"])
        self.assertEqual([item["code"] for item in pools[THIRD_TIER]], ["600021", "600023"])

    def test_missing_bottom_price_sorts_after_computable_gap(self):
        pools = split_tiers(
            [row(code="600002", bottom_price=0.0), row(code="600001", bottom_price=8.9)],
            CFG,
        )
        self.assertEqual([item["code"] for item in pools[FIRST_TIER]], ["600001", "600002"])


if __name__ == "__main__":
    unittest.main()
