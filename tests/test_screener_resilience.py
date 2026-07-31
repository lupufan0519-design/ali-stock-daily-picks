import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from screener import (
    MAX_UNRESOLVED_ERRORS,
    Stock,
    fetch_chunk,
    scan_quality_error,
)


class FailingClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        raise ConnectionError("server unavailable")

    def __exit__(self, exc_type, exc, traceback):
        return False


class ScreenerResilienceTests(unittest.TestCase):
    def test_connection_failure_returns_chunk_errors_for_retry(self):
        fake_xmtdx = SimpleNamespace(
            KlineCategory=SimpleNamespace(DAY=9),
            Market=lambda market: market,
            TdxClient=FailingClient,
        )
        stocks = [
            Stock(1, "600001", "示例一"),
            Stock(0, "000001", "示例二"),
        ]
        with patch.dict(sys.modules, {"xmtdx": fake_xmtdx}):
            results, errors = fetch_chunk(
                "203.0.113.1",
                stocks,
                {"history_bars": 180},
            )

        self.assertEqual(results, [])
        self.assertEqual(len(errors), 2)
        self.assertTrue(errors[0].startswith("600001 ConnectionError:"))
        self.assertTrue(errors[1].startswith("000001 ConnectionError:"))

    def test_scan_quality_blocks_large_partial_publication(self):
        allowed = ["600001 timeout"] * MAX_UNRESOLVED_ERRORS
        blocked = allowed + ["600002 timeout"]
        self.assertEqual(scan_quality_error(5208, allowed), "")
        self.assertIn("本轮不更新策略状态", scan_quality_error(5208, blocked))


if __name__ == "__main__":
    unittest.main()
