"""
tests/test_smc.py
===================

Testes unitários do pacote Smart Money Concepts (smc).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smc.equal_highs_lows import find_equal_highs_lows
from smc.fair_value_gaps import find_fair_value_gaps
from smc.liquidity_sweeps import find_liquidity_sweeps
from smc.order_blocks import find_order_blocks
from smc.premium_discount import calculate_premium_discount


@pytest.fixture
def trending_df() -> pd.DataFrame:
    periods = 250
    index = pd.date_range("2024-01-01", periods=periods, freq="4h")
    rng = np.random.default_rng(21)
    trend = np.linspace(1000, 1400, periods)
    noise = rng.normal(0, 5, periods)
    close = trend + noise
    high = close + np.abs(rng.normal(3, 1.5, periods))
    low = close - np.abs(rng.normal(3, 1.5, periods))
    open_ = close - rng.normal(0, 2, periods)
    volume = np.abs(rng.normal(1000, 200, periods))

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=index
    )


@pytest.fixture
def fvg_df() -> pd.DataFrame:
    """DataFrame com um gap de alta explícito entre os candles 1 e 3."""
    index = pd.date_range("2024-01-01", periods=5, freq="4h")
    data = {
        "open": [100, 102, 110, 111, 112],
        "high": [103, 104, 112, 113, 114],
        "low": [99, 101, 109, 110, 111],
        "close": [102, 103, 111, 112, 113],
        "volume": [1000, 1000, 1000, 1000, 1000],
    }
    return pd.DataFrame(data, index=index)


def test_find_order_blocks_returns_list_with_expected_fields(trending_df: pd.DataFrame) -> None:
    blocks = find_order_blocks(trending_df)
    assert isinstance(blocks, list)
    for block in blocks:
        d = block.to_dict()
        assert d["direction"] in ("bullish", "bearish")
        assert d["top"] >= d["bottom"]
        assert isinstance(d["mitigated"], bool)
        assert isinstance(d["broken"], bool)


def test_find_fair_value_gaps_detects_explicit_bullish_gap(fvg_df: pd.DataFrame) -> None:
    zones = find_fair_value_gaps(fvg_df)
    assert len(zones) >= 1
    bullish_zones = [z for z in zones if z.direction == "bullish"]
    assert len(bullish_zones) >= 1
    # O gap esperado: high(candle1)=103, low(candle3)=109 -> zona [103, 109].
    assert any(abs(z.bottom - 103) < 1e-6 and abs(z.top - 109) < 1e-6 for z in bullish_zones)


def test_fvg_to_dict_is_json_serializable(fvg_df: pd.DataFrame) -> None:
    import json

    zones = find_fair_value_gaps(fvg_df)
    payload = [z.to_dict() for z in zones]
    json.dumps(payload)  # não deve levantar TypeError


def test_find_equal_highs_lows_requires_two_touches(trending_df: pd.DataFrame) -> None:
    equal_highs, equal_lows = find_equal_highs_lows(trending_df)
    for level in equal_highs + equal_lows:
        assert level.touches >= 2


def test_find_liquidity_sweeps_returns_valid_events(trending_df: pd.DataFrame) -> None:
    sweeps = find_liquidity_sweeps(trending_df)
    for sweep in sweeps:
        if sweep.direction == "sweep_high":
            assert sweep.wick_extreme > sweep.swept_level
            assert sweep.close_price < sweep.swept_level
        else:
            assert sweep.wick_extreme < sweep.swept_level
            assert sweep.close_price > sweep.swept_level


def test_calculate_premium_discount_classifies_correctly() -> None:
    zones = calculate_premium_discount(range_high=200.0, range_low=100.0, current_price=180.0)
    assert zones.equilibrium == 150.0
    assert zones.current_zone == "premium"

    zones_discount = calculate_premium_discount(range_high=200.0, range_low=100.0, current_price=120.0)
    assert zones_discount.current_zone == "discount"


def test_calculate_premium_discount_rejects_invalid_range() -> None:
    with pytest.raises(ValueError):
        calculate_premium_discount(range_high=100.0, range_low=100.0, current_price=100.0)
