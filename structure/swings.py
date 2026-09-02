"""
structure/swings.py
=====================

Detecção de Swing Highs e Swing Lows usando um fractal simples:
um candle é um swing high se seu "high" for maior do que o "high" dos
`lookback` candles anteriores E posteriores; o inverso para swing low.

Essa é a base sobre a qual `market_structure.py` identifica HH, HL,
LH, LL e, a partir daí, BOS e CHOCH.
"""

from __future__ import annotations

import pandas as pd

from config import STRUCTURE_CONFIG


def find_swing_highs(df: pd.DataFrame, lookback: int | None = None) -> pd.Series:
    """
    Identifica os candles que são swing highs (fractal de topo).

    Args:
        df: DataFrame OHLCV.
        lookback: número de candles à esquerda/direita usados na
            confirmação (padrão: `config.STRUCTURE_CONFIG.swing_lookback`, 2).

    Returns:
        `pandas.Series` booleana, True nos índices onde há um swing high.
    """
    lookback = lookback or STRUCTURE_CONFIG.swing_lookback
    high = df["high"]

    is_swing_high = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        window = high.iloc[i - lookback: i + lookback + 1]
        if high.iloc[i] == window.max() and (window == window.max()).sum() == 1:
            is_swing_high.iloc[i] = True

    return is_swing_high


def find_swing_lows(df: pd.DataFrame, lookback: int | None = None) -> pd.Series:
    """
    Identifica os candles que são swing lows (fractal de fundo).

    Args:
        df: DataFrame OHLCV.
        lookback: número de candles à esquerda/direita usados na
            confirmação (padrão: `config.STRUCTURE_CONFIG.swing_lookback`, 2).

    Returns:
        `pandas.Series` booleana, True nos índices onde há um swing low.
    """
    lookback = lookback or STRUCTURE_CONFIG.swing_lookback
    low = df["low"]

    is_swing_low = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        window = low.iloc[i - lookback: i + lookback + 1]
        if low.iloc[i] == window.min() and (window == window.min()).sum() == 1:
            is_swing_low.iloc[i] = True

    return is_swing_low


def get_swing_points(df: pd.DataFrame, lookback: int | None = None) -> pd.DataFrame:
    """
    Retorna um DataFrame compacto apenas com os swing points (highs e
    lows) em ordem cronológica, útil para os módulos de BOS/CHOCH.

    Colunas retornadas: "price", "type" ("high" | "low").
    """
    swing_highs = find_swing_highs(df, lookback=lookback)
    swing_lows = find_swing_lows(df, lookback=lookback)

    highs_df = pd.DataFrame({"price": df.loc[swing_highs, "high"], "type": "high"})
    lows_df = pd.DataFrame({"price": df.loc[swing_lows, "low"], "type": "low"})

    swings = pd.concat([highs_df, lows_df]).sort_index()
    return swings
