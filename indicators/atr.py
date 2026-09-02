"""
indicators/atr.py
==================

Cálculo do ATR (Average True Range).

O ATR mede a volatilidade do ativo, considerando gaps entre candles.
É amplamente usado para dimensionar stops, alvos e para avaliar se o
mercado está em um momento de alta ou baixa volatilidade.
"""

from __future__ import annotations

import pandas as pd

from config import INDICATORS_CONFIG


def calculate_true_range(df: pd.DataFrame) -> pd.Series:
    """
    Calcula o True Range (TR) de cada candle.

    TR = max(
        high - low,
        abs(high - close_anterior),
        abs(low - close_anterior)
    )
    """
    high = df["high"]
    low = df["low"]
    previous_close = df["close"].shift(1)

    range_high_low = high - low
    range_high_prev_close = (high - previous_close).abs()
    range_low_prev_close = (low - previous_close).abs()

    true_range = pd.concat(
        [range_high_low, range_high_prev_close, range_low_prev_close], axis=1
    ).max(axis=1)

    return true_range


def calculate_atr(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """
    Calcula o ATR a partir do True Range, usando suavização de Wilder
    (equivalente a uma EMA com alpha = 1/period).

    Args:
        df: DataFrame OHLCV (precisa das colunas high, low, close).
        period: período do ATR (padrão: `config.INDICATORS_CONFIG.atr.period`, 14).

    Returns:
        `pandas.Series` com o ATR, alinhada ao índice de `df`.
    """
    period = period or INDICATORS_CONFIG.atr.period

    true_range = calculate_true_range(df)
    atr = true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    return atr
