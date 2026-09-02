"""
tests/test_volume_profile.py
==============================

Testes unitários do Volume Profile (POC, VAH, VAL, HVN, LVN).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from volume_profile.profile import build_volume_profile


@pytest.fixture
def sample_df() -> pd.DataFrame:
    periods = 200
    index = pd.date_range("2024-01-01", periods=periods, freq="4h")
    rng = np.random.default_rng(31)
    close = 1000 + np.cumsum(rng.normal(0, 2, periods))
    high = close + np.abs(rng.normal(2, 1, periods))
    low = close - np.abs(rng.normal(2, 1, periods))
    open_ = close - rng.normal(0, 1, periods)
    volume = np.abs(rng.normal(500, 100, periods))

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )


def test_poc_is_within_price_range(sample_df: pd.DataFrame) -> None:
    result = build_volume_profile(sample_df)
    assert result.price_range_low <= result.poc <= result.price_range_high


def test_value_area_contains_poc(sample_df: pd.DataFrame) -> None:
    result = build_volume_profile(sample_df)
    assert result.val <= result.poc <= result.vah


def test_value_area_is_within_full_range(sample_df: pd.DataFrame) -> None:
    result = build_volume_profile(sample_df)
    assert result.price_range_low <= result.val
    assert result.vah <= result.price_range_high


def test_total_distributed_volume_matches_input(sample_df: pd.DataFrame) -> None:
    from volume_profile.profile import _distribute_volume_into_bins
    import numpy as np

    bin_edges = np.linspace(sample_df["low"].min(), sample_df["high"].max(), 51)
    bin_volumes = _distribute_volume_into_bins(sample_df, bin_edges)

    # O volume total distribuído deve ser igual (dentro de uma
    # tolerância de ponto flutuante) ao volume total dos candles.
    assert abs(bin_volumes.sum() - sample_df["volume"].sum()) < 1e-6
