"""
tests/test_learning.py
=========================

Testes puros da Fase 5: classificação de sinais e motor de hipóteses.
Reconstrução histórica (`learning/reconstruction.py`, rede real) tem
smoke test separado em `tests/test_learning_reconstruction.py`.
"""

from __future__ import annotations

from learning.classification import (
    BAD_TRADE_GOOD_RESULT,
    GOOD_TRADE_BAD_RESULT,
    LUCKY_WIN,
    PENDING_RESULT,
    VALID_SIGNAL,
    WEAK_SIGNAL,
    classify_signal,
    compute_quality_score,
)
from learning.hypotheses import IN_TEST, OBSERVATION, REJECTED, VALIDATED, build_hypotheses

# ---------------------------------------------------------------------------
# compute_quality_score / classify_signal
# ---------------------------------------------------------------------------


def test_pending_result_when_no_result_given() -> None:
    assert classify_signal(quality_score=80, result=None) == PENDING_RESULT


def test_good_process_and_win_is_valid_signal() -> None:
    assert classify_signal(quality_score=75, result="win") == VALID_SIGNAL


def test_bad_process_and_win_is_lucky_win() -> None:
    assert classify_signal(quality_score=20, result="win") == LUCKY_WIN


def test_mediocre_process_and_win_is_bad_trade_good_result() -> None:
    assert classify_signal(quality_score=45, result="win") == BAD_TRADE_GOOD_RESULT


def test_good_process_and_loss_is_good_trade_bad_result() -> None:
    assert classify_signal(quality_score=75, result="loss") == GOOD_TRADE_BAD_RESULT


def test_weak_process_and_loss_is_weak_signal() -> None:
    assert classify_signal(quality_score=20, result="loss") == WEAK_SIGNAL


def test_breakeven_good_process_is_valid_signal() -> None:
    assert classify_signal(quality_score=70, result="breakeven") == VALID_SIGNAL


def test_breakeven_weak_process_is_weak_signal() -> None:
    assert classify_signal(quality_score=30, result="breakeven") == WEAK_SIGNAL


def test_quality_score_higher_with_bos_and_regime_compatible() -> None:
    low = compute_quality_score(trend="Ranging", bos=False, choch=True, regime_compatible=False, rr=None)
    high = compute_quality_score(trend="Bullish", bos=True, choch=False, regime_compatible=True, rr=3.0)
    assert high > low
    assert 0 <= low <= 100
    assert 0 <= high <= 100


# ---------------------------------------------------------------------------
# build_hypotheses
# ---------------------------------------------------------------------------


def _signal(strategy: str, result: str | None, r_multiple: float | None = None) -> dict:
    return {"strategy_guess": strategy, "result": result, "r_multiple": r_multiple}


def test_small_sample_is_observation() -> None:
    signals = [_signal("Sweep Reversal", "win", 2.0) for _ in range(5)]
    hyps = build_hypotheses(signals)
    assert hyps[0].status == OBSERVATION
    assert hyps[0].sample_size == 5


def test_medium_sample_is_in_test() -> None:
    signals = [_signal("Sweep Reversal", "win", 2.0) for _ in range(15)]
    hyps = build_hypotheses(signals)
    assert hyps[0].status == IN_TEST


def test_large_sample_good_stats_is_validated() -> None:
    signals = [_signal("Sweep Reversal", "win", 2.0) for _ in range(20)] + [
        _signal("Sweep Reversal", "loss", -1.0) for _ in range(10)
    ]
    hyps = build_hypotheses(signals)
    assert hyps[0].sample_size == 30
    assert hyps[0].win_rate_pct == pytest_approx(66.67)
    assert hyps[0].status == VALIDATED


def test_large_sample_bad_stats_is_rejected() -> None:
    signals = [_signal("Bad Strategy", "loss", -1.0) for _ in range(25)] + [
        _signal("Bad Strategy", "win", 1.0) for _ in range(5)
    ]
    hyps = build_hypotheses(signals)
    assert hyps[0].status == REJECTED


def test_signals_without_result_are_ignored() -> None:
    signals = [_signal("X", None) for _ in range(50)] + [_signal("X", "win", 1.0) for _ in range(3)]
    hyps = build_hypotheses(signals)
    assert hyps[0].sample_size == 3  # os 50 sem resultado não entram na amostra


def test_groups_are_independent() -> None:
    signals = [_signal("A", "win", 2.0) for _ in range(12)] + [_signal("B", "loss", -1.0) for _ in range(3)]
    hyps = {h.group_key: h for h in build_hypotheses(signals)}
    assert hyps["A"].sample_size == 12
    assert hyps["B"].sample_size == 3
    assert hyps["A"].status == IN_TEST
    assert hyps["B"].status == OBSERVATION


def test_hypotheses_sorted_by_sample_size_descending() -> None:
    signals = [_signal("Small", "win", 1.0) for _ in range(5)] + [_signal("Big", "win", 1.0) for _ in range(20)]
    hyps = build_hypotheses(signals)
    assert [h.group_key for h in hyps] == ["Big", "Small"]


def pytest_approx(value):
    import pytest

    return pytest.approx(value, abs=0.1)
