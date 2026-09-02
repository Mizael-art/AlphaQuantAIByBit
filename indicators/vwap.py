"""
indicators/vwap.py
====================

Cálculo do VWAP (Volume Weighted Average Price) e do Anchored VWAP.

- **VWAP**: preço médio ponderado por volume, calculado a partir de um
  ponto de ancoragem (âncora). É amplamente usado por mesas
  institucionais como referência de "preço justo" do dia/sessão.
- **Anchored VWAP**: mesma lógica, mas ancorado em um ponto
  específico definido pelo usuário (ex.: um swing high/low
  relevante, o início do candle mais significativo, etc.), útil para
  avaliar o preço médio pago pelos participantes desde um evento
  importante.
"""

from __future__ import annotations

import pandas as pd


def _typical_price(df: pd.DataFrame) -> pd.Series:
    """Preço típico do candle: média entre high, low e close."""
    return (df["high"] + df["low"] + df["close"]) / 3


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Calcula o VWAP cumulativo desde o primeiro candle do DataFrame.

    Args:
        df: DataFrame OHLCV.

    Returns:
        `pandas.Series` com o VWAP acumulado, alinhado ao índice de `df`.
    """
    typical_price = _typical_price(df)
    cumulative_pv = (typical_price * df["volume"]).cumsum()
    cumulative_volume = df["volume"].cumsum()

    return cumulative_pv / cumulative_volume.replace(0, pd.NA)


def calculate_anchored_vwap(df: pd.DataFrame, anchor_time: pd.Timestamp) -> pd.Series:
    """
    Calcula o VWAP ancorado a partir de um timestamp específico.

    Candles anteriores ao `anchor_time` recebem `NaN` (o VWAP ancorado
    só existe a partir do ponto de ancoragem).

    Args:
        df: DataFrame OHLCV.
        anchor_time: timestamp (compatível com o índice de `df`) a
            partir do qual o VWAP será calculado.

    Returns:
        `pandas.Series` com o Anchored VWAP, alinhado ao índice de `df`.
    """
    anchored_df = df.loc[df.index >= anchor_time]

    if anchored_df.empty:
        return pd.Series(index=df.index, dtype=float)

    anchored_vwap = calculate_vwap(anchored_df)

    result = pd.Series(index=df.index, dtype=float)
    result.loc[anchored_vwap.index] = anchored_vwap
    return result


def calculate_session_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Calcula o VWAP reiniciado a cada nova sessão (dia UTC) — o VWAP
    "clássico" usado intraday, que zera o acumulado à meia-noite UTC.

    Args:
        df: DataFrame OHLCV (índice datetime, timezone-aware em UTC).

    Returns:
        `pandas.Series` com o VWAP de sessão, alinhado ao índice de `df`.
    """
    typical_price = _typical_price(df)
    pv = typical_price * df["volume"]

    session_key = df.index.date
    cumulative_pv = pv.groupby(session_key).cumsum()
    cumulative_volume = df["volume"].groupby(session_key).cumsum()

    return cumulative_pv / cumulative_volume.replace(0, pd.NA)
