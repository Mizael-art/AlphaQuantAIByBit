"""
tests/test_optimization.py
=============================

Testes puros da Fase 8: Monte Carlo e Portfolio Intelligence.
Walk-forward e parameter sweep (rede real) têm smoke test separado em
tests/test_optimization_integration.py.
"""

from __future__ import annotations

import pytest

from optimization.monte_carlo import run_monte_carlo
from optimization.portfolio import select_best_combination

# ---------------------------------------------------------------------------
# run_monte_carlo
# ---------------------------------------------------------------------------


def test_monte_carlo_rejects_empty_trades() -> None:
    with pytest.raises(ValueError):
        run_monte_carlo([], starting_capital=10_000, num_simulations=100)


def test_monte_carlo_rejects_non_positive_simulations() -> None:
    with pytest.raises(ValueError):
        run_monte_carlo([1.0, -1.0], starting_capital=10_000, num_simulations=0)


def test_monte_carlo_all_positive_trades_never_loses() -> None:
    result = run_monte_carlo([1.0, 2.0, 1.5], starting_capital=10_000, num_simulations=200, seed=42)
    assert result.probability_of_loss == 0.0
    assert result.final_capital_percentiles["p50"] > 10_000


def test_monte_carlo_all_negative_trades_always_loses() -> None:
    result = run_monte_carlo([-1.0, -2.0, -0.5], starting_capital=10_000, num_simulations=200, seed=42)
    assert result.probability_of_loss == 1.0
    assert result.final_capital_percentiles["p50"] < 10_000


def test_monte_carlo_percentiles_are_ordered() -> None:
    result = run_monte_carlo([3.0, -2.0, 1.0, -1.5, 2.5], starting_capital=10_000, num_simulations=500, seed=7)
    p = result.final_capital_percentiles
    assert p["p5"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p95"]


def test_monte_carlo_is_reproducible_with_seed() -> None:
    r1 = run_monte_carlo([1.0, -1.0, 2.0], starting_capital=5_000, num_simulations=100, seed=123)
    r2 = run_monte_carlo([1.0, -1.0, 2.0], starting_capital=5_000, num_simulations=100, seed=123)
    assert r1.final_capital_percentiles == r2.final_capital_percentiles


def test_monte_carlo_reports_assumptions_note() -> None:
    result = run_monte_carlo([1.0, -1.0], starting_capital=10_000, num_simulations=50, seed=1)
    assert "i.i.d" in result.assumptions_note or "reposição" in result.assumptions_note


# ---------------------------------------------------------------------------
# select_best_combination
# ---------------------------------------------------------------------------


def _opp(symbol: str, score: float) -> dict:
    return {"symbol": symbol, "overall_opportunity_score": score}


def test_select_best_combination_picks_highest_scores_first() -> None:
    opportunities = [_opp("A", 60), _opp("B", 90), _opp("C", 75)]
    result = select_best_combination(opportunities, max_open_risk_pct=10.0, risk_pct_per_trade=1.0)
    assert result.selected == ["B", "C", "A"]


def test_select_best_combination_respects_risk_budget() -> None:
    opportunities = [_opp("A", 90), _opp("B", 85), _opp("C", 80)]
    result = select_best_combination(opportunities, max_open_risk_pct=2.0, risk_pct_per_trade=1.0)
    assert result.selected == ["A", "B"]
    assert "C" in result.skipped
    assert result.total_risk_pct == pytest.approx(2.0)


def test_select_best_combination_respects_max_positions() -> None:
    opportunities = [_opp("A", 90), _opp("B", 85), _opp("C", 80)]
    result = select_best_combination(opportunities, max_open_risk_pct=10.0, risk_pct_per_trade=1.0, max_positions=1)
    assert result.selected == ["A"]
    assert "B" in result.skipped
    assert "C" in result.skipped


def test_select_best_combination_skips_correlated_duplicates() -> None:
    opportunities = [_opp("BTCUSDT", 90), _opp("ETHUSDT", 85), _opp("SOLUSDT", 70)]
    correlation_flags = {"BTCUSDT": None, "ETHUSDT": "BTCUSDT", "SOLUSDT": None}
    result = select_best_combination(
        opportunities, max_open_risk_pct=10.0, risk_pct_per_trade=1.0, correlation_flags=correlation_flags
    )
    assert result.selected == ["BTCUSDT", "SOLUSDT"]
    assert "correlacionado" in result.skipped["ETHUSDT"].lower()
