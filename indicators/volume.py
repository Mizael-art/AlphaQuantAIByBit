"""
indicators/volume.py
=====================

Análise de volume: cálculo do volume médio e classificação de cada
candle como acima ou abaixo da média (útil para detectar spikes de
volume que costumam acompanhar rompimentos de estrutura).
"""

from __future__ import annotations

import pandas as pd

from config import INDICATORS_CONFIG


def calculate_volume_average(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """
    Calcula a média móvel simples do volume.

    Args:
        df: DataFrame OHLCV (precisa da coluna "volume").
        period: período da média (padrão: `config.INDICATORS_CONFIG.volume.average_period`, 20).

    Returns:
        `pandas.Series` com o volume médio, alinhada ao índice de `df`.
    """
    period = period or INDICATORS_CONFIG.volume.average_period
    return df["volume"].rolling(window=period, min_periods=period).mean()


def is_volume_above_average(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """
    Retorna uma série booleana indicando, candle a candle, se o volume
    negociado está acima da média móvel de volume.
    """
    volume_avg = calculate_volume_average(df, period=period)
    return df["volume"] > volume_avg
