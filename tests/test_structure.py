"""
tests/test_structure.py
=========================

Testes unitários da detecção de estrutura de mercado (swings, HH/HL/LH/LL,
BOS, CHOCH).

Executar com:
    pytest tests/test_structure.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from structure.bos import detect_bos
from structure.choch import detect_choch
from structure.market_structure import analyze_market_structure
from structure.swings import find_swing_highs, find_swing_lows, get_swing_points


@pytest.fixture
def uptrend_df() -> pd.DataFrame:
    """
    DataFrame OHLCV sintético representando uma sequência clara de
    Higher Highs / Higher Lows (tendência de alta bem definida),
    construído candle a candle para garantir swings previsíveis.
    """
    # Sequência de "high" desenhada manualmente para produzir swings
    # em zig-zag ascendente: sobe, recua (mas menos), sobe mais, etc.
    highs = [
        10, 11, 12, 15, 13, 12, 14, 18, 16, 15,
        17, 22, 19, 18, 20, 26, 23, 22, 24, 30,
    ]
    lows = [h - 3 for h in highs]
    closes = [h - 1 for h in highs]
    opens = [low + 0.5 for low in lows]
    volume = [1000 for _ in highs]

    index = pd.date_range("2024-01-01", periods=len(highs), freq="4h")

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume},
        index=index,
    )


@pytest.fixture
def downtrend_df(uptrend_df: pd.DataFrame) -> pd.DataFrame:
    """Inverte a fixture de uptrend para simular uma tendência de baixa clara."""
    df = uptrend_df.copy()
    df = df.iloc[::-1].reset_index(drop=True)
    df.index = uptrend_df.index
    return df


def test_find_swing_highs_returns_boolean_series(uptrend_df: pd.DataFrame) -> None:
    swing_highs = find_swing_highs(uptrend_df)
    assert swing_highs.dtype == bool
    assert swing_highs.any()


def test_find_swing_lows_returns_boolean_series(uptrend_df: pd.DataFrame) -> None:
    swing_lows = find_swing_lows(uptrend_df)
    assert swing_lows.dtype == bool
    assert swing_lows.any()


def test_get_swing_points_has_price_and_type_columns(uptrend_df: pd.DataFrame) -> None:
    swings = get_swing_points(uptrend_df)
    assert list(swings.columns) == ["price", "type"]
    assert set(swings["type"].unique()).issubset({"high", "low"})


def test_analyze_market_structure_detects_uptrend(uptrend_df: pd.DataFrame) -> None:
    result = analyze_market_structure(uptrend_df)
    assert result.trend == "Bullish"
    assert result.hh is True
    assert result.hl is True
    assert result.lh is False
    assert result.ll is False


def test_analyze_market_structure_detects_downtrend(downtrend_df: pd.DataFrame) -> None:
    result = analyze_market_structure(downtrend_df)
    assert result.trend == "Bearish"
    assert result.lh is True
    assert result.ll is True
    assert result.hh is False
    assert result.hl is False


def test_detect_bos_true_when_price_breaks_last_high_in_uptrend() -> None:
    swings = pd.DataFrame(
        {"price": [100.0, 90.0, 110.0], "type": ["high", "low", "high"]},
        index=pd.date_range("2024-01-01", periods=3, freq="4h"),
    )
    close = pd.Series([111.0], index=[swings.index[-1] + pd.Timedelta(hours=4)])

    assert detect_bos(swings, close, trend="Bullish") is True


def test_detect_bos_false_when_price_does_not_break_last_high() -> None:
    swings = pd.DataFrame(
        {"price": [100.0, 90.0, 110.0], "type": ["high", "low", "high"]},
        index=pd.date_range("2024-01-01", periods=3, freq="4h"),
    )
    close = pd.Series([105.0], index=[swings.index[-1] + pd.Timedelta(hours=4)])

    assert detect_bos(swings, close, trend="Bullish") is False


def test_detect_choch_true_when_uptrend_breaks_last_low() -> None:
    swings = pd.DataFrame(
        {"price": [100.0, 90.0, 110.0, 95.0], "type": ["high", "low", "high", "low"]},
        index=pd.date_range("2024-01-01", periods=4, freq="4h"),
    )
    close = pd.Series([94.0], index=[swings.index[-1] + pd.Timedelta(hours=4)])

    assert detect_choch(swings, close, trend="Bullish") is True


def test_detect_choch_false_when_trend_holds() -> None:
    swings = pd.DataFrame(
        {"price": [100.0, 90.0, 110.0, 95.0], "type": ["high", "low", "high", "low"]},
        index=pd.date_range("2024-01-01", periods=4, freq="4h"),
    )
    close = pd.Series([120.0], index=[swings.index[-1] + pd.Timedelta(hours=4)])

    assert detect_choch(swings, close, trend="Bullish") is False
