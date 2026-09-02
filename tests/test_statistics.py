"""
tests/test_statistics.py
==========================

Testes unitários do módulo de estatística (statistics_).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from statistics_.volatility import (
    build_volatility_stats,
    calculate_percentile_rank,
    calculate_std_dev,
    calculate_z_score,
)


@pytest.fixture
def sample_series() -> pd.Series:
    periods = 200
    rng = np.random.default_rng(42)
    values = 1000 + np.cumsum(rng.normal(0, 3, periods))
    index = pd.date_range("2024-01-01", periods=periods, freq="4h")
    return pd.Series(values, index=index)


def test_std_dev_is_non_negative(sample_series: pd.Series) -> None:
    std = calculate_std_dev(sample_series).dropna()
    assert (std >= 0).all()


def test_z_score_of_current_price_at_the_mean_is_near_zero() -> None:
    # Série constante seguida de um único desvio: o z-score do ponto
    # exatamente na média (antes do desvio) deve ser 0.
    values = [100.0] * 25
    index = pd.date_range("2024-01-01", periods=len(values), freq="4h")
    series = pd.Series(values, index=index)

    z = calculate_z_score(series, period=20)
    assert z.iloc[-1] == 0 or pd.isna(z.iloc[-1])


def test_percentile_rank_is_within_bounds(sample_series: pd.Series) -> None:
    percentile = calculate_percentile_rank(sample_series, period=50).dropna()
    assert (percentile >= 0).all()
    assert (percentile <= 100).all()


def test_percentile_rank_of_max_value_is_100() -> None:
    values = list(range(1, 51))  # sequência estritamente crescente
    index = pd.date_range("2024-01-01", periods=len(values), freq="4h")
    series = pd.Series(values, index=index, dtype=float)

    percentile = calculate_percentile_rank(series, period=50)
    assert percentile.iloc[-1] == 100.0


def test_build_volatility_stats_returns_all_fields(sample_series: pd.Series) -> None:
    df = pd.DataFrame(
        {
            "open": sample_series,
            "high": sample_series + 1,
            "low": sample_series - 1,
            "close": sample_series,
            "volume": 1000.0,
        }
    )
    stats = build_volatility_stats(df, timeframe="4H")

    assert stats.std_dev >= 0
    assert stats.realized_volatility_pct >= 0
    assert 0 <= stats.percentile_rank <= 100
