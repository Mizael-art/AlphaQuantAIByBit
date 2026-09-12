"""
indicators/macd.py
===================

Cálculo do MACD (Moving Average Convergence Divergence).

O MACD é a diferença entre duas EMAs (rápida e lenta), acompanhada de
uma linha de sinal (EMA da própria linha MACD) e de um histograma
(diferença entre MACD e sinal), usado para identificar momentum e
possíveis reversões/continuações de tendência.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import INDICATORS_CONFIG
from indicators.ema import calculate_ema


@dataclass(frozen=True, slots=True)
class MACDResult:
    """Agrupa as três séries produzidas pelo cálculo do MACD."""

    macd_line: pd.Series
    signal_line: pd.Series
    histogram: pd.Series


def calculate_macd(
    series: pd.Series,
    fast_period: int | None = None,
    slow_period: int | None = None,
    signal_period: int | None = None,
) -> MACDResult:
    """
    Calcula o MACD completo (linha MACD, linha de sinal e histograma).

    Args:
        series: série de preços (tipicamente `df["close"]`).
        fast_period: período da EMA rápida (padrão: 12).
        slow_period: período da EMA lenta (padrão: 26).
        signal_period: período da EMA de sinal (padrão: 9).

    Returns:
        `MACDResult` com as três séries alinhadas ao índice de `series`.
    """
    macd_config = INDICATORS_CONFIG.macd
    fast_period = fast_period or macd_config.fast_period
    slow_period = slow_period or macd_config.slow_period
    signal_period = signal_period or macd_config.signal_period

    ema_fast = calculate_ema(series, fast_period)
    ema_slow = calculate_ema(series, slow_period)

    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal_period)
    histogram = macd_line - signal_line

    return MACDResult(macd_line=macd_line, signal_line=signal_line, histogram=histogram)
