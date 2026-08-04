import unittest

from strategy_contract import (
    EXECUTION_SCOPE,
    EXIT_MAX_HOLDING_BARS,
    EXIT_PROFIT_ACTIVATION_PCT,
    EXIT_RULE_ID,
    EXIT_TRAILING_DRAWDOWN_PCT,
    FROZEN_CANDIDATE_ID,
    LIVE_STRATEGY_CONTRACT,
    LIVE_STRATEGY_ID,
    strategy_contract,
)


class StrategyContractTests(unittest.TestCase):
    def test_frozen_identity_and_scope_are_explicit(self):
        self.assertEqual(LIVE_STRATEGY_ID, "secondary_lowrisk2_hybrid1010_v3")
        self.assertEqual(
            FROZEN_CANDIDATE_ID,
            "low_risk_2__wave_erasure_hybrid_or_10_10_weakening",
        )
        self.assertEqual(EXECUTION_SCOPE, "secondary")

    def test_exit_contract_matches_the_jointly_validated_candidate(self):
        self.assertEqual(
            EXIT_RULE_ID,
            "wave_erasure_hybrid_or_10_10_weakening",
        )
        self.assertEqual(EXIT_PROFIT_ACTIVATION_PCT, 10.0)
        self.assertEqual(EXIT_TRAILING_DRAWDOWN_PCT, 10.0)
        self.assertEqual(EXIT_MAX_HOLDING_BARS, 60)
        self.assertTrue(LIVE_STRATEGY_CONTRACT["exit_on_true_erasure"])

    def test_callers_receive_a_copy(self):
        payload = strategy_contract()
        payload["live_strategy_id"] = "changed"
        self.assertEqual(
            LIVE_STRATEGY_CONTRACT["live_strategy_id"],
            LIVE_STRATEGY_ID,
        )


if __name__ == "__main__":
    unittest.main()
