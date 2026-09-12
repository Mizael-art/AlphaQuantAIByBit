"""
indicators/volume_extra.py
=============================

Indicadores adicionais baseados em volume: OBV (On-Balance Volume) e
CMF (Chaikin Money Flow).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_obv(df: pd.DataFrame) -> pd.Series:
    """
    Calcula o OBV (On-Balance Volume): soma cumulativa do volume,
    somado quando o fechamento sobe e subtraído quando cai. Usado para
    identificar divergências entre preço e volume acumulado.
    """
    direction = np.sign(df["close"].diff().fillna(0))
    signed_volume = direction * df["volume"]
    return signed_volume.cumsum()


def calculate_cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Calcula o CMF (Chaikin Money Flow): mede a pressão compradora ou
    vendedora combinando a posição do fechamento dentro do range do
    candle (Money Flow Multiplier) com o volume negociado.
    """
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]

    range_ = (high - low).replace(0, np.nan)
    money_flow_multiplier = ((close - low) - (high - close)) / range_
    money_flow_volume = money_flow_multiplier * volume

    return (
        money_flow_volume.rolling(window=period, min_periods=period).sum()
        / volume.rolling(window=period, min_periods=period).sum()
    )
