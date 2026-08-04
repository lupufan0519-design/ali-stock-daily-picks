from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable

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


ROOT = Path(__file__).resolve().parent
GRID_CASE_SHARED_FIELDS = (
    "schema_version",
    "run_id",
    "config_hash",
    "completed_trade_date",
)
REQUIRED_PORTFOLIO_CANDIDATES = (
    FROZEN_CANDIDATE_ID,
    "low_risk_2__wave_erasure_trail_10_10",
    "low_risk_2__wave_erasure_hybrid_or_8_3_weakening",
    "break_5day_high__trail_3_2",
)
RETURN_PRIORITY_CANDIDATE_ID = "low_risk_2__wave_erasure_trail_10_10"
REQUIRED_PORTFOLIO_SCENARIOS = ("cost_1x", "cost_2x")
REQUIRED_PORTFOLIO_SLOTS = ("5", "10", "20")


class ArtifactIdentityError(ValueError):
    pass


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ArtifactIdentityError(f"无法读取策略产物 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactIdentityError(f"策略产物不是JSON对象: {path}")
    return value


def _expect(actual: object, expected: object, field: str) -> None:
    if actual != expected:
        raise ArtifactIdentityError(
            f"{field} 不一致: expected={expected!r}, actual={actual!r}"
        )


def _mapping(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise ArtifactIdentityError(f"{field} must be an object")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactIdentityError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ArtifactIdentityError(f"{field} must be finite")
    return number


def _expected_cost_scenario(assumptions: dict, multiplier: float) -> dict:
    commission = _number(
        assumptions.get("commission_bps_per_side"),
        "portfolio commission_bps_per_side",
    )
    slippage = _number(
        assumptions.get("slippage_bps_per_side"),
        "portfolio slippage_bps_per_side",
    )
    exchange = _number(
        assumptions.get("exchange_fee_bps_per_side"),
        "portfolio exchange_fee_bps_per_side",
    )
    regulatory = _number(
        assumptions.get("regulatory_fee_bps_per_side"),
        "portfolio regulatory_fee_bps_per_side",
    )
    stamp = _number(
        assumptions.get("stamp_duty_bps_sell"),
        "portfolio stamp_duty_bps_sell",
    )
    variable = (commission + slippage) * multiplier
    fixed_each_side = exchange + regulatory
    return {
        "multiplier": float(multiplier),
        "buy_cost_bps": fixed_each_side + variable,
        "sell_cost_bps": fixed_each_side + variable + stamp,
        "scaled_components": "broker commission and slippage only",
        "unscaled_components": (
            "exchange fee, regulatory fee and sell-side stamp duty"
        ),
    }


def _validate_portfolio_slice(
    candidate: dict,
    *,
    candidate_id: str,
    scenario_id: str,
    slot_count: str,
) -> None:
    scenario = _mapping(
        _mapping(candidate.get("scenarios"), f"portfolio.{candidate_id}.scenarios").get(
            scenario_id
        ),
        f"portfolio.{candidate_id}.{scenario_id}",
    )
    by_area = _mapping(
        scenario.get("portfolios_by_area"),
        f"portfolio.{candidate_id}.{scenario_id}.portfolios_by_area",
    )
    secondary = _mapping(
        by_area.get(EXECUTION_SCOPE),
        f"portfolio.{candidate_id}.{scenario_id}.{EXECUTION_SCOPE}",
    )
    slot = _mapping(
        secondary.get(slot_count),
        f"portfolio.{candidate_id}.{scenario_id}.{EXECUTION_SCOPE}.{slot_count}",
    )
    runs = slot.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ArtifactIdentityError(
            f"portfolio.{candidate_id}.{scenario_id}.{slot_count}.runs is empty"
        )
    worst = _mapping(
        _mapping(
            slot.get("seed_summary"),
            f"portfolio.{candidate_id}.{scenario_id}.{slot_count}.seed_summary",
        ).get("worst"),
        f"portfolio.{candidate_id}.{scenario_id}.{slot_count}.worst",
    )
    for field in (
        "average_exposure_pct",
        "capacity_rejections",
        "open_positions_at_cutoff",
    ):
        _number(
            worst.get(field),
            f"portfolio.{candidate_id}.{scenario_id}.{slot_count}.worst.{field}",
        )
    overall = _mapping(
        _mapping(
            worst.get("periods"),
            f"portfolio.{candidate_id}.{scenario_id}.{slot_count}.worst.periods",
        ).get("overall"),
        f"portfolio.{candidate_id}.{scenario_id}.{slot_count}.worst.periods.overall",
    )
    for field in ("cagr_pct", "max_drawdown_pct"):
        _number(
            overall.get(field),
            f"portfolio.{candidate_id}.{scenario_id}.{slot_count}.overall.{field}",
        )
    for field in ("start_date", "end_date"):
        if not str(overall.get(field, "")).strip():
            raise ArtifactIdentityError(
                f"portfolio.{candidate_id}.{scenario_id}.{slot_count}.overall.{field} is missing"
            )


def validate_artifacts(
    grid_path: Path,
    case_path: Path,
    portfolio_path: Path | None = None,
    *,
    require_portfolio: bool = False,
) -> dict:
    grid = _load(grid_path)
    case = _load(case_path)
    contract = strategy_contract()
    expected_entry_rule = {
        "id": contract["entry_id"],
        "label": contract["entry_label"],
        "kind": "timed_filter",
        "delay": contract["entry_delay_bars"],
        "max_pullback": contract["entry_max_pullback_pct"],
        "require_above_dragon": contract["require_close_above_dragon"],
        "require_dragon_nonfalling": contract["require_dragon_nonfalling"],
    }
    expected_exit_rule = {
        "id": contract["exit_id"],
        "label": contract["exit_label"],
        "kind": "hybrid",
        "activation": contract["profit_activation_pct"],
        "drawdown": contract["trailing_drawdown_pct"],
        "weakening_confirm": contract["weakening_confirmation_occurrences"],
        "combine": "either",
        "exit_on_erasure": contract["exit_on_true_erasure"],
    }
    live = grid.get("live_strategy", {})
    if not isinstance(live, dict):
        raise ArtifactIdentityError("grid.live_strategy 缺失")
    for key, expected in contract.items():
        _expect(live.get(key), expected, f"grid.live_strategy.{key}")
    _expect(live.get("candidate_id"), FROZEN_CANDIDATE_ID, "grid candidate")
    _expect(live.get("execution_scope"), EXECUTION_SCOPE, "grid scope")
    grid_meta = grid.get("meta", {})
    _expect(grid_meta.get("live_strategy_id"), LIVE_STRATEGY_ID, "grid meta strategy")
    _expect(
        grid_meta.get("frozen_candidate_id"),
        FROZEN_CANDIDATE_ID,
        "grid meta candidate",
    )
    _expect(grid_meta.get("execution_scope"), EXECUTION_SCOPE, "grid meta scope")
    _expect(
        grid_meta.get("live_strategy_contract"),
        contract,
        "grid meta contract",
    )
    _expect(
        grid_meta.get("forward_evaluation", {}).get(
            "historical_2026_is_blind_holdout"
        ),
        False,
        "grid 2026 blind status",
    )
    _expect(
        _mapping(
            grid_meta.get("execution_assumptions"),
            "grid meta execution_assumptions",
        ).get("entry_execution_max_wait_bars"),
        ENTRY_EXECUTION_MAX_WAIT_BARS,
        "grid entry execution wait contract",
    )
    if "不再属于盲测" not in str(grid_meta.get("selection_policy", "")):
        raise ArtifactIdentityError("grid selection_policy 未声明2026不再属于盲测")

    for field in GRID_CASE_SHARED_FIELDS:
        grid_value = grid.get(field, grid.get("meta", {}).get(field))
        case_value = case.get(field, case.get("meta", {}).get(field))
        _expect(case_value, grid_value, f"grid/case {field}")

    _expect(
        case.get("frozen_live_strategy_id"),
        LIVE_STRATEGY_ID,
        "case live_strategy_id",
    )
    _expect(case.get("candidate_id"), FROZEN_CANDIDATE_ID, "case candidate")
    _expect(case.get("frozen_candidate_id"), FROZEN_CANDIDATE_ID, "case frozen candidate")
    _expect(case.get("execution_scope"), EXECUTION_SCOPE, "case scope")
    _expect(case.get("strategy_contract"), contract, "case contract")
    _expect(case.get("entry_rule_id"), ENTRY_RULE_ID, "case entry rule")
    _expect(case.get("exit_rule_id"), EXIT_RULE_ID, "case exit rule")
    _expect(
        case.get("entry_rule", {}).get("id"),
        ENTRY_RULE_ID,
        "case entry_rule.id",
    )
    _expect(
        case.get("entry_rule", {}).get("label"),
        contract["entry_label"],
        "case entry_rule.label",
    )
    _expect(case.get("entry_rule"), expected_entry_rule, "case entry_rule contract")
    _expect(
        case.get("exit_rule", {}).get("id"),
        EXIT_RULE_ID,
        "case exit_rule.id",
    )
    _expect(
        case.get("exit_rule", {}).get("label"),
        contract["exit_label"],
        "case exit_rule.label",
    )
    _expect(case.get("exit_rule"), expected_exit_rule, "case exit_rule contract")
    _expect(case.get("activation"), EXIT_PROFIT_ACTIVATION_PCT, "case activation")
    _expect(case.get("drawdown"), EXIT_TRAILING_DRAWDOWN_PCT, "case drawdown")
    if not str(case.get("exit_reason", "")).strip():
        raise ArtifactIdentityError("case exit_reason 缺失")

    primary = case.get("primary_case")
    if not isinstance(primary, dict) or primary.get("outcome") != "trade":
        raise ArtifactIdentityError("primary_case 必须是冻结候选的一笔已完成交易")
    _expect(primary.get("entry_area"), EXECUTION_SCOPE, "primary_case.entry_area")
    for field, expected in (
        ("candidate_id", FROZEN_CANDIDATE_ID),
        ("execution_scope", EXECUTION_SCOPE),
        ("entry_rule_id", ENTRY_RULE_ID),
        ("exit_rule_id", EXIT_RULE_ID),
        ("activation", EXIT_PROFIT_ACTIVATION_PCT),
        ("drawdown", EXIT_TRAILING_DRAWDOWN_PCT),
    ):
        _expect(primary.get(field), expected, f"primary_case.{field}")
    _expect(
        primary.get("entry_rule", {}).get("id"),
        ENTRY_RULE_ID,
        "primary_case.entry_rule.id",
    )
    _expect(
        primary.get("entry_rule", {}).get("label"),
        contract["entry_label"],
        "primary_case.entry_rule.label",
    )
    _expect(
        primary.get("entry_rule"),
        expected_entry_rule,
        "primary_case.entry_rule contract",
    )
    _expect(
        primary.get("exit_rule", {}).get("id"),
        EXIT_RULE_ID,
        "primary_case.exit_rule.id",
    )
    _expect(
        primary.get("exit_rule", {}).get("label"),
        contract["exit_label"],
        "primary_case.exit_rule.label",
    )
    _expect(
        primary.get("exit_rule"),
        expected_exit_rule,
        "primary_case.exit_rule contract",
    )
    _expect(primary.get("exit_reason"), case.get("exit_reason"), "case exit_reason")
    bars = primary.get("bars")
    if not isinstance(bars, list) or not bars:
        raise ArtifactIdentityError("primary_case.bars 缺失")
    bar_dates = [str(item.get("date", "")) for item in bars if isinstance(item, dict)]
    if len(bar_dates) != len(bars) or any(not value for value in bar_dates):
        raise ArtifactIdentityError("primary_case.bars 日期不完整")
    if bar_dates != sorted(dict.fromkeys(bar_dates)):
        raise ArtifactIdentityError("primary_case.bars 日期未严格递增")
    for field in (
        "signal_setup_date",
        "entry_trigger_date",
        "entry_date",
        "peak_date",
        "exit_trigger_date",
        "exit_date",
    ):
        value = str(primary.get(field, ""))
        if not value or value not in bar_dates:
            raise ArtifactIdentityError(f"primary_case.{field} 未落在案例K线")
    if not (
        str(primary["signal_setup_date"])
        <= str(primary["entry_trigger_date"])
        < str(primary["entry_date"])
        <= str(primary["peak_date"])
        <= str(primary["exit_trigger_date"])
        < str(primary["exit_date"])
    ):
        raise ArtifactIdentityError("primary_case 买卖触发与执行日期顺序错误")
    for field in ("wave_dragon", "wave_tiger"):
        values = primary.get(field)
        if not isinstance(values, list) or len(values) != len(bars):
            raise ArtifactIdentityError(f"primary_case.{field} 与K线点数不一致")
    qualified_yellow_dates = primary.get("qualified_yellow_dates")
    if not isinstance(qualified_yellow_dates, list) or not qualified_yellow_dates:
        raise ArtifactIdentityError("primary_case 有效配对黄柱缺失")
    if any(str(value) not in bar_dates for value in qualified_yellow_dates):
        raise ArtifactIdentityError("primary_case 有效配对黄柱未落在案例K线")
    caption = str(primary.get("chart_caption", ""))
    for field in (
        "signal_setup_date",
        "entry_trigger_date",
        "entry_date",
        "exit_trigger_date",
        "exit_date",
    ):
        if str(primary[field]) not in caption:
            raise ArtifactIdentityError(f"primary_case.chart_caption 缺少 {field}")

    secondary = grid.get("cohorts", {}).get("secondary", {})
    main = grid.get("cohorts", {}).get("main", {})
    _expect(secondary.get("execution_scope"), EXECUTION_SCOPE, "secondary scope")
    _expect(secondary.get("live_action_enabled"), True, "secondary live action")
    _expect(main.get("live_action_enabled"), False, "main live action")
    optimization = _mapping(grid.get("optimization"), "grid.optimization")
    _expect(
        optimization.get("frozen_candidate_id"),
        FROZEN_CANDIDATE_ID,
        "grid optimization candidate",
    )
    if "all_candidates" in optimization:
        raise ArtifactIdentityError(
            "grid.optimization.all_candidates is a research-only payload and must not be published"
        )

    portfolio_checked = False
    if portfolio_path is not None and portfolio_path.exists():
        portfolio = _load(portfolio_path)
        portfolio_checked = True
        portfolio_meta = portfolio.get("meta", {})
        _expect(
            portfolio_meta.get("live_strategy_id"),
            LIVE_STRATEGY_ID,
            "portfolio live strategy",
        )
        _expect(
            portfolio_meta.get("frozen_candidate_id"),
            FROZEN_CANDIDATE_ID,
            "portfolio candidate",
        )
        _expect(
            portfolio_meta.get("execution_scope"),
            EXECUTION_SCOPE,
            "portfolio scope",
        )
        _expect(
            portfolio_meta.get("live_strategy_contract"),
            contract,
            "portfolio contract",
        )
        _expect(
            portfolio_meta.get("forward_evaluation", {}).get(
                "historical_2026_is_blind_holdout"
            ),
            False,
            "portfolio 2026 blind status",
        )
        if "不再属于盲测" not in str(portfolio_meta.get("selection_policy", "")):
            raise ArtifactIdentityError(
                "portfolio selection_policy 未声明2026不再属于盲测"
            )
        _expect(
            portfolio_meta.get("portfolio_policy", {}).get(
                "official_portfolio_scope"
            ),
            EXECUTION_SCOPE,
            "portfolio official scope",
        )
        portfolio_policy = _mapping(
            portfolio_meta.get("portfolio_policy"),
            "portfolio policy",
        )
        _expect(
            portfolio_policy.get("entry_priority_fields"),
            ["fixed_seed", "code", "setup_date", "entry_date"],
            "portfolio causal entry priority fields",
        )
        _expect(
            portfolio_policy.get("entry_priority_uses_future_information"),
            False,
            "portfolio causal entry priority",
        )
        _expect(
            portfolio_policy.get(
                "entry_priority_shared_across_exit_comparators"
            ),
            True,
            "portfolio shared entry priority",
        )
        _expect(
            portfolio_policy.get("trade_statistics_maturity_future_bars"),
            COMMON_FUTURE_BARS,
            "portfolio trade statistics maturity",
        )
        for field in (
            "portfolio_includes_all_filled_entries_through_cutoff",
            "portfolio_entry_admission_independent_of_future_exit",
            "portfolio_keeps_unexited_positions_open_at_cutoff",
        ):
            _expect(
                portfolio_policy.get(field),
                True,
                f"portfolio causal inclusion {field}",
            )
        grid_assumptions = _mapping(
            grid_meta.get("execution_assumptions"),
            "grid meta execution_assumptions",
        )
        portfolio_assumptions = _mapping(
            portfolio_meta.get("execution_assumptions"),
            "portfolio execution_assumptions",
        )
        for field in (
            "commission_bps_per_side",
            "exchange_fee_bps_per_side",
            "regulatory_fee_bps_per_side",
            "stamp_duty_bps_sell",
            "slippage_bps_per_side",
            "entry_execution_max_wait_bars",
        ):
            _expect(
                portfolio_assumptions.get(field),
                grid_assumptions.get(field),
                f"portfolio execution assumption {field}",
            )
        cost_scenarios = _mapping(
            portfolio_meta.get("cost_scenarios"),
            "portfolio cost_scenarios",
        )
        for scenario_id, multiplier in (("cost_1x", 1.0), ("cost_2x", 2.0)):
            _expect(
                _mapping(
                    cost_scenarios.get(scenario_id),
                    f"portfolio cost_scenarios.{scenario_id}",
                ),
                _expected_cost_scenario(portfolio_assumptions, multiplier),
                f"portfolio cost scenario {scenario_id}",
            )
        grid_cutoff = grid.get("completed_trade_date") or grid.get("meta", {}).get(
            "completed_trade_date"
        )
        _expect(
            portfolio_meta.get("completed_trade_date"),
            grid_cutoff,
            "portfolio completed_trade_date",
        )
        grid_config_hash = grid.get("config_hash") or grid.get("meta", {}).get(
            "config_hash"
        )
        _expect(
            portfolio_meta.get("config_hash"),
            grid_config_hash,
            "portfolio config_hash",
        )
        missing_candidates = [
            candidate_id
            for candidate_id in REQUIRED_PORTFOLIO_CANDIDATES
            if candidate_id not in portfolio.get("candidates", {})
        ]
        if missing_candidates:
            raise ArtifactIdentityError(
                f"portfolio 缺少正式候选: {', '.join(missing_candidates)}"
            )
        portfolio_candidates = _mapping(portfolio.get("candidates"), "portfolio.candidates")
        frozen_portfolio = _mapping(
            portfolio_candidates[FROZEN_CANDIDATE_ID],
            f"portfolio.{FROZEN_CANDIDATE_ID}",
        )
        _expect(
            frozen_portfolio.get("execution_scope"),
            EXECUTION_SCOPE,
            "portfolio candidate scope",
        )
        _expect(
            frozen_portfolio.get("entry_method", {}).get("id"),
            ENTRY_RULE_ID,
            "portfolio entry rule",
        )
        _expect(
            frozen_portfolio.get("exit_rule", {}).get("id"),
            EXIT_RULE_ID,
            "portfolio exit rule",
        )
        _expect(
            frozen_portfolio.get("entry_method"),
            expected_entry_rule,
            "portfolio entry rule contract",
        )
        _expect(
            frozen_portfolio.get("exit_rule"),
            expected_exit_rule,
            "portfolio exit rule contract",
        )
        _expect(
            frozen_portfolio.get("trades_omitted"),
            True,
            "portfolio trades_omitted",
        )
        return_portfolio = _mapping(
            portfolio_candidates[RETURN_PRIORITY_CANDIDATE_ID],
            f"portfolio.{RETURN_PRIORITY_CANDIDATE_ID}",
        )
        _expect(
            return_portfolio.get("execution_scope"),
            EXECUTION_SCOPE,
            "portfolio return candidate scope",
        )
        _expect(
            return_portfolio.get("entry_method", {}).get("id"),
            ENTRY_RULE_ID,
            "portfolio return candidate entry rule",
        )
        _expect(
            return_portfolio.get("entry_method"),
            expected_entry_rule,
            "portfolio return candidate entry rule contract",
        )
        _expect(
            return_portfolio.get("exit_rule", {}).get("id"),
            "wave_erasure_trail_10_10",
            "portfolio return candidate exit rule",
        )
        for field, expected in (
            ("kind", "trailing"),
            ("activation", 10.0),
            ("drawdown", 10.0),
            ("exit_on_erasure", True),
        ):
            _expect(
                return_portfolio.get("exit_rule", {}).get(field),
                expected,
                f"portfolio return candidate exit rule {field}",
            )
        for candidate_id in REQUIRED_PORTFOLIO_CANDIDATES:
            candidate = _mapping(
                portfolio_candidates[candidate_id],
                f"portfolio.{candidate_id}",
            )
            _expect(
                candidate.get("trades_omitted"),
                True,
                f"portfolio.{candidate_id}.trades_omitted",
            )
        for scenario_id in REQUIRED_PORTFOLIO_SCENARIOS:
            for slot_count in REQUIRED_PORTFOLIO_SLOTS:
                _validate_portfolio_slice(
                    frozen_portfolio,
                    candidate_id=FROZEN_CANDIDATE_ID,
                    scenario_id=scenario_id,
                    slot_count=slot_count,
                )
        _validate_portfolio_slice(
            return_portfolio,
            candidate_id=RETURN_PRIORITY_CANDIDATE_ID,
            scenario_id="cost_1x",
            slot_count="20",
        )
    elif require_portfolio:
        raise ArtifactIdentityError(f"缺少正式组合验证文件: {portfolio_path}")

    return {
        "live_strategy_id": LIVE_STRATEGY_ID,
        "candidate_id": FROZEN_CANDIDATE_ID,
        "execution_scope": EXECUTION_SCOPE,
        "completed_trade_date": grid.get("completed_trade_date")
        or grid.get("meta", {}).get("completed_trade_date"),
        "portfolio_checked": portfolio_checked,
        "grid_case_shared_fields": list(GRID_CASE_SHARED_FIELDS),
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发布前校验策略研究产物身份")
    parser.add_argument(
        "--grid",
        type=Path,
        default=ROOT / "results" / "strategy_grid_optimization.json",
    )
    parser.add_argument(
        "--case",
        type=Path,
        default=ROOT / "results" / "trend_case.json",
    )
    parser.add_argument(
        "--portfolio",
        type=Path,
        default=ROOT / "results" / "strategy_portfolio_validation.json",
    )
    parser.add_argument("--require-portfolio", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = validate_artifacts(
        args.grid,
        args.case,
        args.portfolio,
        require_portfolio=args.require_portfolio,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
