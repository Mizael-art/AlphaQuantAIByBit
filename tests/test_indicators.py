"""
tests/test_indicators.py
==========================

Testes unitários dos indicadores técnicos (EMA, RSI, ATR, MACD, Volume).

Executar com:
    pytest tests/test_indicators.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.atr import calculate_atr
from indicators.ema import calculate_all_emas, calculate_ema
from indicators.macd import calculate_macd
from indicators.rsi import calculate_rsi
from indicators.volume import calculate_volume_average, is_volume_above_average


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """
    DataFrame OHLCV sintético com 300 candles, com uma tendência de
    alta clara (para permitir asserts previsíveis sobre EMA/RSI/MACD).
    """
    periods = 300
    index = pd.date_range("2024-01-01", periods=periods, freq="4h")

    # Preço em tendência de alta com um pouco de ruído determinístico.
    rng = np.random.default_rng(seed=42)
    trend = np.linspace(100, 300, periods)
    noise = rng.normal(loc=0, scale=1.5, size=periods)
    close = trend + noise

    high = close + np.abs(rng.normal(loc=1, scale=0.5, size=periods))
    low = close - np.abs(rng.normal(loc=1, scale=0.5, size=periods))
    open_ = close - rng.normal(loc=0, scale=0.5, size=periods)
    volume = np.abs(rng.normal(loc=1000, scale=200, size=periods))

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def test_calculate_ema_length_matches_input(sample_df: pd.DataFrame) -> None:
    ema20 = calculate_ema(sample_df["close"], period=20)
    assert len(ema20) == len(sample_df)


def test_calculate_all_emas_has_expected_columns(sample_df: pd.DataFrame) -> None:
    emas = calculate_all_emas(sample_df)
    assert list(emas.columns) == ["ema20", "ema50", "ema100", "ema200"]


def test_ema_reacts_faster_than_slower_ema_in_uptrend(sample_df: pd.DataFrame) -> None:
    emas = calculate_all_emas(sample_df)
    # Em uma tendência de alta consistente, EMAs mais curtas devem
    # estar acima das mais longas no final da série.
    assert emas["ema20"].iloc[-1] > emas["ema200"].iloc[-1]


def test_rsi_is_within_valid_range(sample_df: pd.DataFrame) -> None:
    rsi = calculate_rsi(sample_df["close"])
    valid_rsi = rsi.dropna()
    assert (valid_rsi >= 0).all()
    assert (valid_rsi <= 100).all()


def test_rsi_is_high_in_strong_uptrend(sample_df: pd.DataFrame) -> None:
    rsi = calculate_rsi(sample_df["close"])
    # Em uma tendência de alta forte e constante, o RSI final deve
    # estar acima de 50 (viés comprador).
    assert rsi.iloc[-1] > 50


def test_atr_is_non_negative(sample_df: pd.DataFrame) -> None:
    atr = calculate_atr(sample_df)
    valid_atr = atr.dropna()
    assert (valid_atr >= 0).all()


def test_macd_returns_three_aligned_series(sample_df: pd.DataFrame) -> None:
    macd_result = calculate_macd(sample_df["close"])
    assert len(macd_result.macd_line) == len(sample_df)
    assert len(macd_result.signal_line) == len(sample_df)
    assert len(macd_result.histogram) == len(sample_df)

    # O histograma deve ser exatamente a diferença entre MACD e sinal.
    diff = (macd_result.macd_line - macd_result.signal_line).dropna()
    hist = macd_result.histogram.dropna()
    pd.testing.assert_series_equal(diff, hist, check_names=False)


def test_volume_average_and_flag_are_consistent(sample_df: pd.DataFrame) -> None:
    volume_avg = calculate_volume_average(sample_df)
    above_avg = is_volume_above_average(sample_df)

    valid_index = volume_avg.dropna().index
    expected = sample_df.loc[valid_index, "volume"] > volume_avg.loc[valid_index]

    pd.testing.assert_series_equal(above_avg.loc[valid_index], expected, check_names=False)
