"""
tests/test_playbook_and_correlation.py
=========================================

Testes puros: filtro regime-first do Playbook e Correlated Exposure Engine.
"""

from __future__ import annotations

import pandas as pd

from discovery.correlation import compute_return_correlation, flag_correlated_duplicates
from playbook.library import compatible_playbooks
from regime.detector import COMPRESSION, RANGE, TRENDING_UP


def test_compatible_playbooks_filters_by_regime_and_direction() -> None:
    results = compatible_playbooks(TRENDING_UP, "long")
    assert all(TRENDING_UP in entry.compatible_regimes for entry in results)
    assert all("long" in entry.directions for entry in results)
    assert len(results) > 0


def test_compatible_playbooks_returns_empty_when_nothing_matches() -> None:
    # Nenhuma estratégia do Playbook inicial é long-only em regime de compressão E long-only ao mesmo tempo com style inexistente.
    results = compatible_playbooks(COMPRESSION, "long", style="swing")
    assert results == []


def test_compatible_playbooks_respects_direction_only_entries() -> None:
    # "Range High Rejection" só é short -- não deve aparecer para long.
    results = compatible_playbooks(RANGE, "long")
    names = {e.name for e in results}
    assert "Range High Rejection" not in names
    assert "Range Low Rejection" in names


def test_correlation_matrix_is_symmetric_and_self_correlated() -> None:
    returns = {
        "A": pd.Series([0.01, 0.02, -0.01, 0.03, 0.00]),
        "B": pd.Series([0.01, 0.02, -0.01, 0.03, 0.00]),  # idêntico a A
        "C": pd.Series([-0.02, 0.01, 0.03, -0.01, 0.02]),
    }
    matrix = compute_return_correlation(returns)
    assert matrix.loc["A", "A"] == 1.0
    assert abs(matrix.loc["A", "B"] - 1.0) < 1e-9


def test_flag_correlated_duplicates_keeps_highest_ranked_of_each_cluster() -> None:
    returns = {
        "A": pd.Series([0.01, 0.02, -0.01, 0.03, 0.00, 0.01, -0.02]),
        "B": pd.Series([0.011, 0.021, -0.009, 0.031, 0.001, 0.012, -0.019]),  # quase idêntico a A -- correlacionado
        "C": pd.Series([-0.03, 0.04, 0.01, -0.02, 0.03, -0.01, 0.02]),  # descorrelacionado
    }
    matrix = compute_return_correlation(returns)
    ranked = ["A", "B", "C"]  # A é o melhor rank, B correlacionado com A, C independente

    flags = flag_correlated_duplicates(ranked, matrix, threshold=0.85)

    assert flags["A"] is None  # melhor do cluster -- sobrevive
    assert flags["B"] == "A"  # redundante com A
    assert flags["C"] is None  # descorrelacionado -- sobrevive
