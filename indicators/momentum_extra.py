"""
indicators/momentum_extra.py
==============================

Indicadores adicionais de momentum/força de tendência: ADX (com +DI/-DI),
CCI, MFI, ROC, Stochastic Oscillator e Williams %R.

Agrupados em um único módulo (em vez de um arquivo por indicador) para
manter o pacote `indicators` gerenciável — todos seguem a mesma
assinatura: recebem um DataFrame OHLCV e devolvem `pandas.Series` (ou
uma tupla delas) alinhadas ao índice original.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators.atr import calculate_true_range


@dataclass(frozen=True, slots=True)
class ADXResult:
    """Agrupa ADX, +DI e -DI."""

    adx: pd.Series
    plus_di: pd.Series
    minus_di: pd.Series


def calculate_adx(df: pd.DataFrame, period: int = 14) -> ADXResult:
    """
    Calcula o ADX (Average Directional Index) junto com +DI e -DI,
    usando suavização de Wilder.

    ADX mede a FORÇA da tendência (não a direção): valores acima de 25
    geralmente indicam tendência forte; abaixo de 20, mercado em range.
    """
    high, low, close = df["high"], df["low"], df["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    true_range = calculate_true_range(df)
    atr = true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    return ADXResult(adx=adx, plus_di=plus_di, minus_di=minus_di)


def calculate_cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Calcula o CCI (Commodity Channel Index), que mede o desvio do
    preço típico em relação à sua média móvel, normalizado pelo
    desvio médio absoluto.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    sma = typical_price.rolling(window=period, min_periods=period).mean()
    mean_deviation = typical_price.rolling(window=period, min_periods=period).apply(
        lambda x: np.abs(x - x.mean()).mean(), raw=True
    )
    return (typical_price - sma) / (0.015 * mean_deviation.replace(0, np.nan))


def calculate_mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calcula o MFI (Money Flow Index), um "RSI ponderado por volume"
    que mede pressão compradora/vendedora considerando o dinheiro
    efetivamente movimentado, não só a variação de preço.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    money_flow = typical_price * df["volume"]

    price_up = typical_price.diff() > 0
    positive_flow = money_flow.where(price_up, 0.0)
    negative_flow = money_flow.where(~price_up, 0.0)

    positive_sum = positive_flow.rolling(window=period, min_periods=period).sum()
    negative_sum = negative_flow.rolling(window=period, min_periods=period).sum()

    money_ratio = positive_sum / negative_sum.replace(0, np.nan)
    mfi = 100 - (100 / (1 + money_ratio))
    return mfi.where(negative_sum != 0, 100.0)


def calculate_roc(series: pd.Series, period: int = 12) -> pd.Series:
    """
    Calcula o ROC (Rate of Change): variação percentual do preço em
    relação a `period` candles atrás. Mede momentum puro de preço.
    """
    return (series / series.shift(period) - 1) * 100


@dataclass(frozen=True, slots=True)
class StochasticResult:
    """Agrupa as linhas %K e %D do Stochastic Oscillator."""

    percent_k: pd.Series
    percent_d: pd.Series


def calculate_stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3, smooth_k: int = 3
) -> StochasticResult:
    """
    Calcula o Stochastic Oscillator (%K suavizado e %D), que mede a
    posição do fechamento em relação ao range de `k_period` candles.
    """
    lowest_low = df["low"].rolling(window=k_period, min_periods=k_period).min()
    highest_high = df["high"].rolling(window=k_period, min_periods=k_period).max()

    raw_k = 100 * (df["close"] - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    percent_k = raw_k.rolling(window=smooth_k, min_periods=smooth_k).mean()
    percent_d = percent_k.rolling(window=d_period, min_periods=d_period).mean()

    return StochasticResult(percent_k=percent_k, percent_d=percent_d)


def calculate_williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calcula o Williams %R, equivalente invertido do Stochastic %K
    (escala de 0 a -100, onde valores próximos de 0 indicam sobrecompra
    e próximos de -100 indicam sobrevenda).
    """
    highest_high = df["high"].rolling(window=period, min_periods=period).max()
    lowest_low = df["low"].rolling(window=period, min_periods=period).min()

    return -100 * (highest_high - df["close"]) / (highest_high - lowest_low).replace(0, np.nan)
