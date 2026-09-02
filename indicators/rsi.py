"""
indicators/rsi.py
==================

Cálculo do RSI (Relative Strength Index / Índice de Força Relativa).

O RSI mede a velocidade e a magnitude das variações de preço em uma
escala de 0 a 100, sendo usado para identificar condições de
sobrecompra (>70) e sobrevenda (<30).

Implementação baseada na suavização de Wilder (a mesma usada pela
maioria das plataformas de trading, incluindo TradingView).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import INDICATORS_CONFIG


def calculate_rsi(series: pd.Series, period: int | None = None) -> pd.Series:
    """
    Calcula o RSI de uma série de preços usando a suavização de Wilder.

    Args:
        series: série de preços (tipicamente `df["close"]`).
        period: período do RSI (padrão: `config.INDICATORS_CONFIG.rsi.period`, 14).

    Returns:
        `pandas.Series` com o RSI (0-100), alinhada ao índice de `series`.
    """
    period = period or INDICATORS_CONFIG.rsi.period

    delta = series.diff()

    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    # Suavização de Wilder = média móvel exponencial com alpha = 1/period.
    avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # Quando não há perdas no período (avg_loss == 0), o RSI é 100.
    rsi = rsi.where(avg_loss != 0, 100.0)

    return rsi
