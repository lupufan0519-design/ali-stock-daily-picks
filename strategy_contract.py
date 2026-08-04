from __future__ import annotations


LIVE_STRATEGY_ID = "secondary_lowrisk2_hybrid1010_v3"
FROZEN_CANDIDATE_ID = (
    "low_risk_2__wave_erasure_hybrid_or_10_10_weakening"
)
EXECUTION_SCOPE = "secondary"

ENTRY_RULE_ID = "low_risk_2"
ENTRY_DELAY_BARS = 2
ENTRY_MAX_PULLBACK_PCT = 3.0
ENTRY_REQUIRE_SIGNAL_VALID = True
ENTRY_REQUIRE_CLOSE_ABOVE_DRAGON = True
ENTRY_REQUIRE_DRAGON_NONFALLING = True
ENTRY_EXECUTION_MAX_WAIT_BARS = 5

EXIT_RULE_ID = "wave_erasure_hybrid_or_10_10_weakening"
EXIT_ON_TRUE_ERASURE = True
EXIT_ON_DRAGON_TIGER_END = True
EXIT_PROFIT_ACTIVATION_PCT = 10.0
EXIT_TRAILING_DRAWDOWN_PCT = 10.0
EXIT_WEAKENING_POINTS = 3
EXIT_WEAKENING_CONFIRMATIONS = 1
EXIT_MAX_HOLDING_BARS = 60

EXECUTION_TIMING = "收盘确认，下一可交易日开盘执行"

ENTRY_LABEL = (
    "首次进入次选后第2个完整交易日收盘确认：信号仍有效、龙线仍高于虎线、"
    "收盘不低于龙线、龙线不低于前一日，且较信号日收盘回撤不超过3%；"
    "下一可交易日开盘买入"
)
EXIT_LABEL = (
    "信号在可见窗口内被重算消失，或龙线不再高于虎线时优先退出；否则浮盈达到"
    "10%后较最高收盘回撤10%，或龙虎线连续三点同步转弱，任一先出现即确认卖点；"
    "最晚跟踪60个后续交易日"
)


LIVE_STRATEGY_CONTRACT = {
    "live_strategy_id": LIVE_STRATEGY_ID,
    "candidate_id": FROZEN_CANDIDATE_ID,
    "execution_scope": EXECUTION_SCOPE,
    "entry_id": ENTRY_RULE_ID,
    "entry_label": ENTRY_LABEL,
    "entry_delay_bars": ENTRY_DELAY_BARS,
    "entry_max_pullback_pct": ENTRY_MAX_PULLBACK_PCT,
    "require_signal_valid": ENTRY_REQUIRE_SIGNAL_VALID,
    "require_close_above_dragon": ENTRY_REQUIRE_CLOSE_ABOVE_DRAGON,
    "require_dragon_nonfalling": ENTRY_REQUIRE_DRAGON_NONFALLING,
    "entry_execution_max_wait_bars": ENTRY_EXECUTION_MAX_WAIT_BARS,
    "exit_id": EXIT_RULE_ID,
    "exit_label": EXIT_LABEL,
    "exit_on_true_erasure": EXIT_ON_TRUE_ERASURE,
    "profit_activation_pct": EXIT_PROFIT_ACTIVATION_PCT,
    "trailing_drawdown_pct": EXIT_TRAILING_DRAWDOWN_PCT,
    "weakening_points": EXIT_WEAKENING_POINTS,
    "weakening_confirmation_occurrences": EXIT_WEAKENING_CONFIRMATIONS,
    "exit_on_dragon_tiger_end": EXIT_ON_DRAGON_TIGER_END,
    "max_holding_bars": EXIT_MAX_HOLDING_BARS,
    "execution_timing": EXECUTION_TIMING,
}


def strategy_contract() -> dict:
    return dict(LIVE_STRATEGY_CONTRACT)
