import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prepare_site import validate_strategy_artifacts


class PrepareSiteValidationTests(unittest.TestCase):
    def test_site_build_requires_the_shared_strong_validation_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {"portfolio_checked": True}
            with patch("prepare_site.validate_artifacts", return_value=expected) as gate:
                self.assertEqual(validate_strategy_artifacts(root), expected)
            gate.assert_called_once_with(
                root / "results" / "strategy_grid_optimization.json",
                root / "results" / "trend_case.json",
                root / "results" / "strategy_portfolio_validation.json",
                require_portfolio=True,
            )

    def test_strong_validation_failure_blocks_site_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "prepare_site.validate_artifacts",
                side_effect=ValueError("run_id 不一致"),
            ):
                with self.assertRaisesRegex(ValueError, "run_id"):
                    validate_strategy_artifacts(root)


if __name__ == "__main__":
    unittest.main()
