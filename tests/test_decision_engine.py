"""
tests/test_decision_engine.py
================================

Testes puros da Fase 6: `decision.engine.evaluate_decision` e
`decision.mentor_block.build_mentor_block`.
"""

from __future__ import annotations

import pytest

from decision.engine import (
    HIGH_CONVICTION,
    LONG_NOW,
    LOW_CONVICTION,
    REJECT,
    SHORT_NOW,
    WAIT_PULLBACK,
    WAIT_TRIGGER,
    WATCH,
    evaluate_decision,
)
from decision.mentor_block import build_mentor_block


def _decide(**overrides) -> str:
    base = dict(
        direction="long",
        overall_score=75.0,
        risk_decision="APPROVED",
        setup_status="TRIGGERED",
        entry_quality="ENTRY_NOW",
    )
    base.update(overrides)
    return evaluate_decision(**base)


# ---------------------------------------------------------------------------
# evaluate_decision
# ---------------------------------------------------------------------------


def test_risk_rejected_always_rejects_regardless_of_score() -> None:
    result = _decide(risk_decision="REJECTED", overall_score=95.0)
    assert result.decision == REJECT
    assert any("Risk Engine" in r for r in result.reasons)


def test_low_score_rejects_not_watch() -> None:
    """Documento Master seção 77: não usar WATCH como resposta de segurança quando não há edge."""
    result = _decide(overall_score=30.0)
    assert result.decision == REJECT


def test_ready_and_good_score_and_entry_now_is_long_now() -> None:
    result = _decide(direction="long")
    assert result.decision == LONG_NOW


def test_ready_and_good_score_and_entry_now_is_short_now() -> None:
    result = _decide(direction="short")
    assert result.decision == SHORT_NOW


def test_waiting_status_is_wait_trigger() -> None:
    result = _decide(setup_status="WATCH")
    assert result.decision == WAIT_TRIGGER


def test_no_entry_quality_is_wait_pullback() -> None:
    result = _decide(entry_quality="NO_ENTRY")
    assert result.decision == WAIT_PULLBACK


def test_entry_on_pullback_quality_is_wait_pullback() -> None:
    result = _decide(entry_quality="ENTRY_ON_PULLBACK", setup_status="TRIGGERED")
    assert result.decision == WAIT_PULLBACK


def test_entry_on_confirmation_is_wait_trigger() -> None:
    result = _decide(entry_quality="ENTRY_ON_CONFIRMATION", setup_status="TRIGGERED")
    assert result.decision == WAIT_TRIGGER


def test_ready_but_score_below_entry_now_threshold_is_watch() -> None:
    result = _decide(overall_score=55.0, setup_status="TRIGGERED", entry_quality="ENTRY_NOW")
    assert result.decision == WATCH


def test_unknown_setup_status_treated_as_ready_if_entry_now() -> None:
    """Trade avaliado ad-hoc (sem setup persistido) ainda pode virar LONG_NOW/SHORT_NOW."""
    result = _decide(setup_status="UNKNOWN")
    assert result.decision == LONG_NOW


def test_conviction_scales_with_score() -> None:
    low = _decide(overall_score=52.0, setup_status="WATCH")
    high = _decide(overall_score=90.0)
    assert low.conviction == LOW_CONVICTION
    assert high.conviction == HIGH_CONVICTION


def test_invalid_direction_raises() -> None:
    with pytest.raises(ValueError):
        _decide(direction="sideways")


def test_reduced_risk_still_allows_entry_now_with_note() -> None:
    result = _decide(risk_decision="REDUCED")
    assert result.decision == LONG_NOW
    assert any("reduzido" in r.lower() for r in result.reasons)


# ---------------------------------------------------------------------------
# build_mentor_block
# ---------------------------------------------------------------------------


def test_mentor_block_entry_now_includes_execution_fields() -> None:
    block = build_mentor_block(
        decision=LONG_NOW, conviction=HIGH_CONVICTION, reasons=["ok"], asset="SOLUSDT",
        entry_zone=(140.0, 142.0), stop=138.0, target=150.0, rr=3.0, approved_risk_pct=1.0,
        volatility_bucket="NORMAL", style="day_trade", invalidation="Fechamento 1H abaixo de 138", main_risk="Notícia inesperada",
    )
    assert block["emoji"] == "🟢"
    assert block["headline"] == "ABRIR LONG AGORA"
    assert block["risk_pct"] == 1.0
    assert block["recommended_leverage"] == 3
    assert block["entry_zone"] == {"low": 140.0, "high": 142.0}


def test_mentor_block_non_entry_hides_execution_fields() -> None:
    block = build_mentor_block(
        decision=WATCH, conviction=LOW_CONVICTION, reasons=["sem gatilho"], asset="SOLUSDT",
        entry_zone=None, stop=None, target=None, rr=None, approved_risk_pct=None,
        volatility_bucket="NORMAL", style=None, invalidation=None, main_risk=None,
    )
    assert block["emoji"] == "⚪"
    assert block["risk_pct"] is None
    assert block["recommended_leverage"] is None


def test_mentor_block_reject_has_correct_emoji_and_headline() -> None:
    block = build_mentor_block(
        decision=REJECT, conviction=LOW_CONVICTION, reasons=["sem edge"], asset="XRPUSDT",
        entry_zone=None, stop=None, target=None, rr=None, approved_risk_pct=None,
        volatility_bucket="HIGH", style=None, invalidation=None, main_risk=None,
    )
    assert block["emoji"] == "❌"
    assert block["headline"] == "NÃO ABRIR"
