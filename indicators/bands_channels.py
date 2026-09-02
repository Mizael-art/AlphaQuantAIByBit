"""
indicators/bands_channels.py
===============================

Bandas e canais de volatilidade: Bollinger Bands, Donchian Channels e
Keltner Channels. Todos medem, de formas diferentes, a "faixa normal"
de preço esperada — úteis para detectar compressão/expansão de
volatilidade e possíveis rompimentos.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from indicators.atr import calculate_atr
from indicators.ema import calculate_ema


@dataclass(frozen=True, slots=True)
class BandResult:
    """Estrutura genérica para bandas/canais de 3 linhas (upper/middle/lower)."""

    upper: pd.Series
    middle: pd.Series
    lower: pd.Series


def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> BandResult:
    """
    Calcula as Bandas de Bollinger: SMA central +/- `std_dev` desvios
    padrão do preço de fechamento. Compressão das bandas (squeeze)
    costuma preceder movimentos de expansão de volatilidade.
    """
    close = df["close"]
    middle = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std()

    upper = middle + std_dev * std
    lower = middle - std_dev * std

    return BandResult(upper=upper, middle=middle, lower=lower)


def calculate_donchian_channels(df: pd.DataFrame, period: int = 20) -> BandResult:
    """
    Calcula os Canais de Donchian: máxima e mínima dos últimos
    `period` candles, com a linha central sendo a média dos dois.
    Rompimentos do canal são usados classicamente em estratégias de
    breakout (ex.: Turtle Traders).
    """
    upper = df["high"].rolling(window=period, min_periods=period).max()
    lower = df["low"].rolling(window=period, min_periods=period).min()
    middle = (upper + lower) / 2

    return BandResult(upper=upper, middle=middle, lower=lower)


def calculate_keltner_channels(
    df: pd.DataFrame, ema_period: int = 20, atr_period: int = 10, atr_multiplier: float = 2.0
) -> BandResult:
    """
    Calcula os Canais de Keltner: EMA central +/- múltiplo do ATR
    (em vez de desvio padrão, como no Bollinger) — reage mais
    suavemente a outliers de preço.
    """
    middle = calculate_ema(df["close"], ema_period)
    atr = calculate_atr(df, atr_period)

    upper = middle + atr_multiplier * atr
    lower = middle - atr_multiplier * atr

    return BandResult(upper=upper, middle=middle, lower=lower)
