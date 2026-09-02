"""
tests/test_risk_engine.py
============================

Testes puros da Fase 4: núcleo de decisão do Risk Engine, Risk of
Ruin e Capital Allocation. `risk/repository.py` (I/O) é coberto em
`tests/test_risk_repository.py`.
"""

from __future__ import annotations

import pytest

from risk.capital_allocation import CORE, NORMAL, REDUCED as ALLOC_REDUCED, WATCH_ONLY, classify_capital_priority
from risk.engine import (
    APPROVED,
    REDUCED,
    REJECTED,
    AccountRiskState,
    ProposedTrade,
    RiskLimits,
    evaluate_trade_risk,
)
from risk.ruin import estimate_risk_of_ruin

_LIMITS = RiskLimits(
    max_risk_per_trade_pct=1.0,
    daily_loss_limit_pct=3.0,
    weekly_loss_limit_pct=6.0,
    monthly_drawdown_limit_pct=12.0,
    max_open_risk_pct=5.0,
)


def _state(**overrides) -> AccountRiskState:
    base = dict(
        current_capital=10_000.0,
        realized_pnl_today_pct=0.0,
        realized_pnl_week_pct=0.0,
        realized_pnl_month_pct=0.0,
        open_risk_pct=0.0,
        correlated_open_position_exists=False,
    )
    base.update(overrides)
    return AccountRiskState(**base)


def _trade(**overrides) -> ProposedTrade:
    base = dict(asset="SOLUSDT", direction="long", requested_risk_pct=1.0, correlation_group=None)
    base.update(overrides)
    return ProposedTrade(**base)


# ---------------------------------------------------------------------------
# evaluate_trade_risk
# ---------------------------------------------------------------------------


def test_approves_when_within_all_limits() -> None:
    decision = evaluate_trade_risk(_trade(), _state(), _LIMITS)
    assert decision.decision == APPROVED
    assert decision.approved_risk_pct == 1.0


def test_rejects_when_daily_loss_limit_hit() -> None:
    decision = evaluate_trade_risk(_trade(), _state(realized_pnl_today_pct=-3.5), _LIMITS)
    assert decision.decision == REJECTED
    assert decision.approved_risk_pct == 0.0
    assert any("diária" in r for r in decision.reasons)


def test_rejects_when_weekly_loss_limit_hit() -> None:
    decision = evaluate_trade_risk(_trade(), _state(realized_pnl_week_pct=-6.0), _LIMITS)
    assert decision.decision == REJECTED
    assert any("semanal" in r for r in decision.reasons)


def test_rejects_when_monthly_drawdown_limit_hit() -> None:
    decision = evaluate_trade_risk(_trade(), _state(realized_pnl_month_pct=-15.0), _LIMITS)
    assert decision.decision == REJECTED
    assert any("mensal" in r for r in decision.reasons)


def test_daily_loss_limit_checked_before_correlation() -> None:
    """Limite de perda é STOP absoluto -- checado antes até de correlação."""
    decision = evaluate_trade_risk(
        _trade(), _state(realized_pnl_today_pct=-10.0, correlated_open_position_exists=True), _LIMITS
    )
    assert decision.decision == REJECTED
    assert any("diária" in r for r in decision.reasons)


def test_rejects_when_correlated_open_position_exists() -> None:
    decision = evaluate_trade_risk(_trade(), _state(correlated_open_position_exists=True), _LIMITS)
    assert decision.decision == REJECTED
    assert any("correlacionada" in r for r in decision.reasons)


def test_reduces_risk_above_per_trade_cap() -> None:
    decision = evaluate_trade_risk(_trade(requested_risk_pct=2.5), _state(), _LIMITS)
    assert decision.decision == REDUCED
    assert decision.approved_risk_pct == 1.0  # teto por trade


def test_reduces_risk_to_remaining_open_risk_space() -> None:
    decision = evaluate_trade_risk(_trade(requested_risk_pct=1.0), _state(open_risk_pct=4.5), _LIMITS)
    assert decision.decision == REDUCED
    assert decision.approved_risk_pct == pytest.approx(0.5)


def test_rejects_when_open_risk_already_at_cap() -> None:
    decision = evaluate_trade_risk(_trade(), _state(open_risk_pct=5.0), _LIMITS)
    assert decision.decision == REJECTED
    assert any("Open risk" in r for r in decision.reasons)


# ---------------------------------------------------------------------------
# estimate_risk_of_ruin
# ---------------------------------------------------------------------------


def test_risk_of_ruin_rejects_non_positive_risk_per_trade() -> None:
    with pytest.raises(ValueError):
        estimate_risk_of_ruin(win_rate_pct=55, payoff_ratio=2.0, risk_per_trade_pct=0)


def test_risk_of_ruin_is_100_when_edge_is_negative() -> None:
    result = estimate_risk_of_ruin(win_rate_pct=30, payoff_ratio=1.0, risk_per_trade_pct=1.0)
    assert result.edge < 0
    assert result.risk_of_ruin_pct == 100.0


def test_risk_of_ruin_lower_with_smaller_risk_per_trade() -> None:
    high_risk = estimate_risk_of_ruin(win_rate_pct=55, payoff_ratio=2.0, risk_per_trade_pct=5.0)
    low_risk = estimate_risk_of_ruin(win_rate_pct=55, payoff_ratio=2.0, risk_per_trade_pct=0.5)
    assert low_risk.risk_of_ruin_pct < high_risk.risk_of_ruin_pct


def test_risk_of_ruin_lower_with_higher_edge() -> None:
    weak_edge = estimate_risk_of_ruin(win_rate_pct=45, payoff_ratio=1.5, risk_per_trade_pct=1.0)
    strong_edge = estimate_risk_of_ruin(win_rate_pct=60, payoff_ratio=2.5, risk_per_trade_pct=1.0)
    assert strong_edge.risk_of_ruin_pct < weak_edge.risk_of_ruin_pct


# ---------------------------------------------------------------------------
# classify_capital_priority
# ---------------------------------------------------------------------------


def test_low_score_is_watch_only() -> None:
    assert classify_capital_priority(overall_score=40, correlated_with=None, rr=3.0) == WATCH_ONLY


def test_correlated_is_reduced_even_with_high_score() -> None:
    assert classify_capital_priority(overall_score=90, correlated_with="BTCUSDT", rr=3.0) == ALLOC_REDUCED


def test_weak_rr_is_reduced() -> None:
    assert classify_capital_priority(overall_score=85, correlated_with=None, rr=1.2) == ALLOC_REDUCED


def test_high_score_good_rr_no_correlation_is_core() -> None:
    assert classify_capital_priority(overall_score=85, correlated_with=None, rr=3.0) == CORE


def test_moderate_score_is_normal() -> None:
    assert classify_capital_priority(overall_score=65, correlated_with=None, rr=2.0) == NORMAL
