import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from screener import (
    MAX_UNRESOLVED_ERRORS,
    Stock,
    fetch_chunk,
    retry_failed_individually,
    retry_stock_across_hosts,
    scan_quality_error,
)


class FailingClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        raise ConnectionError("server unavailable")

    def __exit__(self, exc_type, exc, traceback):
        return False


class BrokenAfterConnectClient:
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def get_security_bars(self, *args, **kwargs):
        type(self).calls += 1
        raise ConnectionError("connection dropped")


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

    def test_broken_connection_is_short_circuited_for_the_whole_chunk(self):
        BrokenAfterConnectClient.calls = 0
        fake_xmtdx = SimpleNamespace(
            KlineCategory=SimpleNamespace(DAY=9),
            Market=lambda market: market,
            TdxClient=BrokenAfterConnectClient,
        )
        stocks = [
            Stock(1, f"600{i:03d}", f"示例{i}")
            for i in range(20)
        ]
        with patch.dict(sys.modules, {"xmtdx": fake_xmtdx}):
            results, errors = fetch_chunk(
                "203.0.113.1",
                stocks,
                {"history_bars": 180},
            )

        self.assertEqual(results, [])
        self.assertEqual(BrokenAfterConnectClient.calls, 1)
        self.assertEqual([line.split(" ", 1)[0] for line in errors], [s.code for s in stocks])

    def test_final_retry_runs_concurrently_and_preserves_input_order(self):
        stocks = [Stock(1, f"600{i:03d}", f"示例{i}") for i in range(8)]
        barrier = threading.Barrier(4)
        lock = threading.Lock()
        active = 0
        max_active = 0

        def fake_fetch(host, stock_group, cfg):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                barrier.wait(timeout=2)
            finally:
                with lock:
                    active -= 1
            return [stock_group[0].code], []

        results, errors = retry_failed_individually(
            stocks,
            ["host-a"],
            {},
            4,
            fetcher=fake_fetch,
        )

        self.assertEqual(max_active, 4)
        self.assertEqual(results, [stock.code for stock in stocks])
        self.assertEqual(errors, [])

    def test_final_retry_stops_after_first_success(self):
        stock = Stock(1, "600001", "示例")
        calls = []

        def fake_fetch(host, stock_group, cfg):
            calls.append(host)
            if host == "host-b":
                return ["resolved"], []
            return [], [f"{stock.code} timeout"]

        results, errors = retry_stock_across_hosts(
            stock,
            ["host-a", "host-b", "host-c"],
            {},
            deadline=10,
            clock=lambda: 0,
            fetcher=fake_fetch,
        )

        self.assertEqual(calls, ["host-a", "host-b"])
        self.assertEqual(results, ["resolved"])
        self.assertEqual(errors, [])

    def test_final_retry_budget_expiry_starts_no_requests(self):
        stocks = [Stock(1, "600001", "示例一"), Stock(0, "000001", "示例二")]
        calls = []

        def fake_fetch(host, stock_group, cfg):
            calls.append((host, stock_group[0].code))
            return [], ["unexpected"]

        results, errors = retry_failed_individually(
            stocks,
            ["host-a"],
            {},
            2,
            time_budget=0,
            clock=lambda: 1,
            fetcher=fake_fetch,
        )

        self.assertEqual(results, [])
        self.assertEqual(calls, [])
        self.assertEqual([line.split(" ", 1)[0] for line in errors], [s.code for s in stocks])
        self.assertTrue(all("FinalRetryBudgetExceeded" in line for line in errors))

    def test_scan_quality_blocks_large_partial_publication(self):
        allowed = ["600001 timeout"] * MAX_UNRESOLVED_ERRORS
        blocked = allowed + ["600002 timeout"]
        self.assertEqual(scan_quality_error(5208, allowed), "")
        self.assertIn("本轮不更新策略状态", scan_quality_error(5208, blocked))


if __name__ == "__main__":
    unittest.main()
