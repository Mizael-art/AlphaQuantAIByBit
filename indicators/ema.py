"""
indicators/ema.py
==================

Cálculo de Médias Móveis Exponenciais (EMA).

A EMA dá mais peso aos preços recentes do que uma média móvel simples
(SMA), tornando-a mais sensível a mudanças recentes de preço — por
isso é amplamente usada para identificar tendência de curto, médio e
longo prazo (EMA20, EMA50, EMA100, EMA200 respectivamente).
"""

from __future__ import annotations

import pandas as pd

from config import INDICATORS_CONFIG


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Calcula a EMA de uma série de preços para um período específico.

    Args:
        series: série de preços (tipicamente `df["close"]`).
        period: período da EMA (ex.: 20, 50, 100, 200).

    Returns:
        `pandas.Series` com a EMA, alinhada ao índice de `series`.
    """
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def calculate_all_emas(df: pd.DataFrame, price_column: str = "close") -> pd.DataFrame:
    """
    Calcula todas as EMAs configuradas (por padrão: 20, 50, 100, 200) e
    as retorna como colunas de um novo DataFrame.

    Args:
        df: DataFrame OHLCV.
        price_column: coluna de preço usada no cálculo (padrão "close").

    Returns:
        DataFrame com uma coluna por período, nomeada "ema{periodo}"
        (ex.: "ema20", "ema50", "ema100", "ema200").
    """
    result = pd.DataFrame(index=df.index)
    for period in INDICATORS_CONFIG.ema.periods:
        result[f"ema{period}"] = calculate_ema(df[price_column], period)
    return result
