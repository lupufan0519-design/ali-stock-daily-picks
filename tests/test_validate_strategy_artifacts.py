import json
import tempfile
import unittest
from pathlib import Path

from strategy_contract import (
    ENTRY_EXECUTION_MAX_WAIT_BARS,
    ENTRY_RULE_ID,
    EXECUTION_SCOPE,
    EXIT_PROFIT_ACTIVATION_PCT,
    EXIT_RULE_ID,
    EXIT_TRAILING_DRAWDOWN_PCT,
    FROZEN_CANDIDATE_ID,
    LIVE_STRATEGY_ID,
    strategy_contract,
)
from signal_window_optimization import COMMON_FUTURE_BARS
from validate_strategy_artifacts import ArtifactIdentityError, validate_artifacts
from validate_strategy_artifacts import REQUIRED_PORTFOLIO_CANDIDATES


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def valid_portfolio_scenarios() -> dict:
    return {
        scenario_id: {
            "portfolios_by_area": {
                EXECUTION_SCOPE: {
                    slot_count: {
                        "runs": [{"seed": 17}],
                        "seed_summary": {
                            "worst": {
                                "average_exposure_pct": 25.0,
                                "capacity_rejections": 3,
                                "open_positions_at_cutoff": 2,
                                "periods": {
                                    "overall": {
                                        "start_date": "2015-11-12",
                                        "end_date": "2026-08-04",
                                        "cagr_pct": 4.2,
                                        "max_drawdown_pct": -18.0,
                                    }
                                },
                            }
                        },
                    }
                    for slot_count in ("5", "10", "20")
                }
            }
        }
        for scenario_id in ("cost_1x", "cost_2x")
    }


def valid_payloads() -> tuple[dict, dict, dict]:
    shared = {
        "schema_version": 3,
        "run_id": "joint-2026-08-04-test",
        "config_hash": "abc123",
        "completed_trade_date": "2026-08-04",
    }
    contract = strategy_contract()
    execution_assumptions = {
        "commission_bps_per_side": 3.0,
        "exchange_fee_bps_per_side": 0.341,
        "regulatory_fee_bps_per_side": 0.2,
        "stamp_duty_bps_sell": 5.0,
        "slippage_bps_per_side": 5.0,
        "entry_execution_max_wait_bars": ENTRY_EXECUTION_MAX_WAIT_BARS,
    }
    entry_rule = {
        "id": ENTRY_RULE_ID,
        "label": contract["entry_label"],
        "kind": "timed_filter",
        "delay": contract["entry_delay_bars"],
        "max_pullback": contract["entry_max_pullback_pct"],
        "require_above_dragon": contract["require_close_above_dragon"],
        "require_dragon_nonfalling": contract["require_dragon_nonfalling"],
    }
    exit_rule = {
        "id": EXIT_RULE_ID,
        "label": contract["exit_label"],
        "kind": "hybrid",
        "activation": contract["profit_activation_pct"],
        "drawdown": contract["trailing_drawdown_pct"],
        "weakening_confirm": contract["weakening_confirmation_occurrences"],
        "combine": "either",
        "exit_on_erasure": contract["exit_on_true_erasure"],
    }
    primary = {
        "outcome": "trade",
        "candidate_id": FROZEN_CANDIDATE_ID,
        "execution_scope": EXECUTION_SCOPE,
        "entry_area": EXECUTION_SCOPE,
        "entry_rule_id": ENTRY_RULE_ID,
        "exit_rule_id": EXIT_RULE_ID,
        "entry_rule": dict(entry_rule),
        "exit_rule": dict(exit_rule),
        "activation": EXIT_PROFIT_ACTIVATION_PCT,
        "drawdown": EXIT_TRAILING_DRAWDOWN_PCT,
        "exit_reason": "dragon_tiger_weakening",
        "signal_setup_date": "2026-07-01",
        "entry_trigger_date": "2026-07-03",
        "entry_date": "2026-07-04",
        "peak_date": "2026-07-05",
        "exit_trigger_date": "2026-07-07",
        "exit_date": "2026-07-08",
        "bars": [
            {"date": value, "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0}
            for value in (
                "2026-07-01",
                "2026-07-03",
                "2026-07-04",
                "2026-07-05",
                "2026-07-07",
                "2026-07-08",
            )
        ],
        "wave_dragon": [9.0, 9.1, 9.2, 9.3, 9.4, 9.5],
        "wave_tiger": [8.0, 8.1, 8.2, 8.3, 8.4, 8.5],
        "qualified_yellow_dates": ["2026-07-01"],
        "chart_caption": (
            "2026-07-01形成信号；2026-07-03收盘确认，2026-07-04开盘买入；"
            "2026-07-07收盘确认，2026-07-08开盘卖出。"
        ),
    }
    grid = {
        **shared,
        "meta": {
            **shared,
            "live_strategy_id": LIVE_STRATEGY_ID,
            "frozen_candidate_id": FROZEN_CANDIDATE_ID,
            "execution_scope": EXECUTION_SCOPE,
            "live_strategy_contract": strategy_contract(),
            "selection_policy": "2026已反复查看，不再属于盲测",
            "forward_evaluation": {
                "historical_2026_is_blind_holdout": False
            },
            "execution_assumptions": dict(execution_assumptions),
        },
        "live_strategy": {**strategy_contract(), "contract": strategy_contract()},
        "optimization": {"frozen_candidate_id": FROZEN_CANDIDATE_ID},
        "cohorts": {
            "secondary": {
                "execution_scope": EXECUTION_SCOPE,
                "live_action_enabled": True,
            },
            "main": {"live_action_enabled": False},
        },
    }
    case = {
        **shared,
        "frozen_live_strategy_id": LIVE_STRATEGY_ID,
        "frozen_candidate_id": FROZEN_CANDIDATE_ID,
        "candidate_id": FROZEN_CANDIDATE_ID,
        "execution_scope": EXECUTION_SCOPE,
        "strategy_contract": strategy_contract(),
        "entry_rule_id": ENTRY_RULE_ID,
        "exit_rule_id": EXIT_RULE_ID,
        "entry_rule": dict(entry_rule),
        "exit_rule": dict(exit_rule),
        "activation": EXIT_PROFIT_ACTIVATION_PCT,
        "drawdown": EXIT_TRAILING_DRAWDOWN_PCT,
        "exit_reason": primary["exit_reason"],
        "primary_case": primary,
    }
    portfolio = {
        "meta": {
            "completed_trade_date": shared["completed_trade_date"],
            "config_hash": shared["config_hash"],
            "live_strategy_id": LIVE_STRATEGY_ID,
            "frozen_candidate_id": FROZEN_CANDIDATE_ID,
            "execution_scope": EXECUTION_SCOPE,
            "live_strategy_contract": strategy_contract(),
            "selection_policy": "2026已反复查看，不再属于盲测",
            "forward_evaluation": {
                "historical_2026_is_blind_holdout": False
            },
            "execution_assumptions": dict(execution_assumptions),
            "cost_scenarios": {
                "cost_1x": {
                    "multiplier": 1.0,
                    "buy_cost_bps": 8.541,
                    "sell_cost_bps": 13.541,
                    "scaled_components": "broker commission and slippage only",
                    "unscaled_components": (
                        "exchange fee, regulatory fee and sell-side stamp duty"
                    ),
                },
                "cost_2x": {
                    "multiplier": 2.0,
                    "buy_cost_bps": 16.541,
                    "sell_cost_bps": 21.541,
                    "scaled_components": "broker commission and slippage only",
                    "unscaled_components": (
                        "exchange fee, regulatory fee and sell-side stamp duty"
                    ),
                },
            },
            "portfolio_policy": {
                "official_portfolio_scope": EXECUTION_SCOPE,
                "entry_priority_fields": [
                    "fixed_seed",
                    "code",
                    "setup_date",
                    "entry_date",
                ],
                "entry_priority_uses_future_information": False,
                "entry_priority_shared_across_exit_comparators": True,
                "trade_statistics_maturity_future_bars": COMMON_FUTURE_BARS,
                "portfolio_includes_all_filled_entries_through_cutoff": True,
                "portfolio_entry_admission_independent_of_future_exit": True,
                "portfolio_keeps_unexited_positions_open_at_cutoff": True,
            },
        },
        "candidates": {
            candidate_id: {
                "execution_scope": EXECUTION_SCOPE,
                "entry_method": (
                    dict(entry_rule)
                    if candidate_id in {
                        FROZEN_CANDIDATE_ID,
                        "low_risk_2__wave_erasure_trail_10_10",
                    }
                    else {"id": candidate_id.split("__", 1)[0]}
                ),
                "exit_rule": (
                    dict(exit_rule)
                    if candidate_id == FROZEN_CANDIDATE_ID
                    else {
                        "id": "wave_erasure_trail_10_10",
                        "label": "收益优先对照",
                        "kind": "trailing",
                        "activation": 10.0,
                        "drawdown": 10.0,
                        "exit_on_erasure": True,
                    }
                    if candidate_id == "low_risk_2__wave_erasure_trail_10_10"
                    else {"id": candidate_id.split("__", 1)[1]}
                ),
                "trades_omitted": True,
                "scenarios": valid_portfolio_scenarios(),
            }
            for candidate_id in REQUIRED_PORTFOLIO_CANDIDATES
        },
    }
    return grid, case, portfolio


class ValidateStrategyArtifactsTests(unittest.TestCase):
    def test_retired_validation_workflow_cannot_overwrite_the_simple_site(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "rolling-validation.yml"
        )
        self.assertFalse(workflow.exists())

    def test_publish_workflows_share_one_non_cancelling_concurrency_group(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        for filename in ("daily.yml", "intraday.yml"):
            workflow = (workflows / filename).read_text(encoding="utf-8")
            self.assertIn("group: stock-pages-publish", workflow)
            self.assertIn("cancel-in-progress: false", workflow)
        daily = (workflows / "daily.yml").read_text(encoding="utf-8")
        self.assertIn("results/history.json", daily)
        self.assertIn("results/latest.html", daily)
        self.assertIn("index.html", daily)

    def test_intraday_refresh_runs_only_during_continuous_trading(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "intraday.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('cron: "30-55/5 1 * * 1-5"', workflow)
        self.assertNotIn('cron: "15-55/5 1 * * 1-5"', workflow)
        self.assertIn('"09:30" <= hhmm <= "11:30"', workflow)
        self.assertIn('"13:00" <= hhmm <= "15:00"', workflow)

    def validate(self, mutate=None):
        grid, case, portfolio = valid_payloads()
        if mutate:
            mutate(grid, case, portfolio)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in ("grid.json", "case.json", "portfolio.json")]
            for path, payload in zip(paths, (grid, case, portfolio)):
                write_json(path, payload)
            return validate_artifacts(*paths, require_portfolio=True)

    def test_matching_contract_artifacts_pass(self):
        result = self.validate()

        self.assertEqual(result["live_strategy_id"], LIVE_STRATEGY_ID)
        self.assertEqual(result["candidate_id"], FROZEN_CANDIDATE_ID)
        self.assertTrue(result["portfolio_checked"])

    def test_grid_case_shared_field_mismatch_fails(self):
        with self.assertRaisesRegex(ArtifactIdentityError, "grid/case run_id"):
            self.validate(lambda _grid, case, _portfolio: case.update(run_id="wrong"))

    def test_portfolio_identity_or_cutoff_mismatch_fails(self):
        with self.assertRaisesRegex(
            ArtifactIdentityError,
            "portfolio completed_trade_date",
        ):
            self.validate(
                lambda _grid, _case, portfolio: portfolio["meta"].update(
                    completed_trade_date="2026-08-03"
                )
            )

    def test_portfolio_config_hash_mismatch_fails(self):
        with self.assertRaisesRegex(ArtifactIdentityError, "portfolio config_hash"):
            self.validate(
                lambda _grid, _case, portfolio: portfolio["meta"].update(
                    config_hash="different-config"
                )
            )

    def test_portfolio_entry_priority_must_be_causal_and_shared(self):
        with self.assertRaisesRegex(
            ArtifactIdentityError,
            "portfolio causal entry priority fields",
        ):
            self.validate(
                lambda _grid, _case, portfolio: portfolio["meta"][
                    "portfolio_policy"
                ].update(
                    entry_priority_fields=[
                        "fixed_seed",
                        "candidate_id",
                        "code",
                        "entry_date",
                        "exit_date",
                    ],
                    entry_priority_uses_future_information=True,
                    entry_priority_shared_across_exit_comparators=False,
                )
            )

    def test_portfolio_cost_labels_must_match_actual_scaled_components(self):
        with self.assertRaisesRegex(
            ArtifactIdentityError,
            "portfolio cost scenario cost_2x",
        ):
            self.validate(
                lambda _grid, _case, portfolio: portfolio["meta"][
                    "cost_scenarios"
                ]["cost_2x"].update(
                    buy_cost_bps=17.082,
                    scaled_components="all costs",
                )
            )

    def test_portfolio_maturity_and_open_position_policy_are_required(self):
        with self.assertRaisesRegex(
            ArtifactIdentityError,
            "portfolio trade statistics maturity",
        ):
            self.validate(
                lambda _grid, _case, portfolio: portfolio["meta"][
                    "portfolio_policy"
                ].update(
                    trade_statistics_maturity_future_bars=60,
                    portfolio_entry_admission_independent_of_future_exit=False,
                )
            )

        with self.assertRaisesRegex(
            ArtifactIdentityError,
            "portfolio causal inclusion",
        ):
            self.validate(
                lambda _grid, _case, portfolio: portfolio["meta"][
                    "portfolio_policy"
                ].update(
                    portfolio_entry_admission_independent_of_future_exit=False
                )
            )

    def test_grid_execution_wait_must_match_the_frozen_contract(self):
        with self.assertRaisesRegex(
            ArtifactIdentityError,
            "entry execution wait contract",
        ):
            self.validate(
                lambda grid, _case, _portfolio: grid["meta"][
                    "execution_assumptions"
                ].update(entry_execution_max_wait_bars=9)
            )

    def test_published_grid_rejects_research_only_all_candidates(self):
        with self.assertRaisesRegex(ArtifactIdentityError, "all_candidates"):
            self.validate(
                lambda grid, _case, _portfolio: grid["optimization"].update(
                    all_candidates=[]
                )
            )

    def test_portfolio_page_metric_is_required(self):
        def remove_metric(_grid, _case, portfolio):
            del portfolio["candidates"][FROZEN_CANDIDATE_ID]["scenarios"][
                "cost_1x"
            ]["portfolios_by_area"][EXECUTION_SCOPE]["20"]["seed_summary"][
                "worst"
            ]["periods"]["overall"]["cagr_pct"]

        with self.assertRaisesRegex(ArtifactIdentityError, "cagr_pct"):
            self.validate(remove_metric)

    def test_portfolio_page_metric_must_be_finite(self):
        def corrupt_metric(_grid, _case, portfolio):
            portfolio["candidates"][FROZEN_CANDIDATE_ID]["scenarios"][
                "cost_1x"
            ]["portfolios_by_area"][EXECUTION_SCOPE]["20"]["seed_summary"][
                "worst"
            ]["periods"]["overall"]["cagr_pct"] = float("nan")

        with self.assertRaisesRegex(ArtifactIdentityError, "must be finite"):
            self.validate(corrupt_metric)

    def test_return_priority_candidate_identity_is_required(self):
        with self.assertRaisesRegex(
            ArtifactIdentityError,
            "return candidate exit rule",
        ):
            self.validate(
                lambda _grid, _case, portfolio: portfolio["candidates"][
                    "low_risk_2__wave_erasure_trail_10_10"
                ]["exit_rule"].update(id="wrong")
            )

    def test_primary_case_must_be_the_frozen_completed_trade(self):
        with self.assertRaisesRegex(ArtifactIdentityError, "primary_case.candidate_id"):
            self.validate(
                lambda _grid, case, _portfolio: case["primary_case"].update(
                    candidate_id="wrong"
                )
            )

    def test_case_entry_parameters_must_match_the_frozen_contract(self):
        with self.assertRaisesRegex(
            ArtifactIdentityError,
            "case entry_rule contract",
        ):
            self.validate(
                lambda _grid, case, _portfolio: case["entry_rule"].update(
                    delay=99,
                    max_pullback=99.0,
                )
            )

    def test_portfolio_exit_parameters_must_match_the_frozen_contract(self):
        with self.assertRaisesRegex(
            ArtifactIdentityError,
            "portfolio exit rule contract",
        ):
            self.validate(
                lambda _grid, _case, portfolio: portfolio["candidates"][
                    FROZEN_CANDIDATE_ID
                ]["exit_rule"].update(
                    weakening_confirm=99,
                    combine="all",
                    exit_on_erasure=False,
                )
            )

    def test_primary_case_chart_dates_and_lines_must_align(self):
        with self.assertRaisesRegex(ArtifactIdentityError, "wave_dragon"):
            self.validate(
                lambda _grid, case, _portfolio: case["primary_case"].update(
                    wave_dragon=[9.0]
                )
            )


if __name__ == "__main__":
    unittest.main()
