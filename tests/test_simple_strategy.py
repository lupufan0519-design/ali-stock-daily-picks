import unittest

from simple_strategy import FIRST_TIER, SECOND_TIER, classify_tier, split_tiers


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
            "",
        )

    def test_current_day_gap_does_not_change_first_tier(self):
        self.assertEqual(
            classify_tier(row(dragon_value=20.0, tiger_value=10.0), CFG),
            FIRST_TIER,
        )

    def test_second_tier_requires_price_below_all_three_lines(self):
        base = row(prior_three_gap_abs=[0.1, 0.6, 0.2])
        self.assertEqual(classify_tier(base, CFG), SECOND_TIER)
        self.assertEqual(classify_tier({**base, "price": 10.1}, CFG), "")

    def test_first_tier_wins_when_both_rules_match(self):
        pools = split_tiers([row()], CFG)
        self.assertEqual(len(pools[FIRST_TIER]), 1)
        self.assertEqual(len(pools[SECOND_TIER]), 0)

    def test_bottom_and_st_filters_are_hard_requirements(self):
        self.assertEqual(classify_tier(row(bottom_ok=False), CFG), "")
        self.assertEqual(classify_tier(row(name="*ST示例"), CFG), "")


if __name__ == "__main__":
    unittest.main()
