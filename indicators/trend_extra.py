"""
indicators/trend_extra.py
============================

Indicadores de tendência com estado dependente do candle anterior
(por isso calculados iterativamente, não vetorizados): SuperTrend,
Parabolic SAR e Ichimoku Cloud (este último vetorizado, pois não
depende de estado recursivo).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators.atr import calculate_atr


@dataclass(frozen=True, slots=True)
class SuperTrendResult:
    """Linha do SuperTrend e a direção da tendência (1 = alta, -1 = baixa)."""

    supertrend: pd.Series
    direction: pd.Series  # 1 (alta) ou -1 (baixa)


def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> SuperTrendResult:
    """
    Calcula o indicador SuperTrend, amplamente usado como filtro de
    tendência e trailing stop dinâmico.

    Args:
        df: DataFrame OHLCV.
        period: período do ATR usado na banda.
        multiplier: multiplicador do ATR (padrão 3.0).

    Returns:
        `SuperTrendResult` com a linha SuperTrend e a direção vigente.
    """
    atr = calculate_atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2

    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)

    close = df["close"]

    # Primeiro índice com ATR válido: é aqui que a série realmente
    # começa (candles anteriores não têm ATR suficiente). Inicializar
    # a partir daqui evita que a lógica de "banda final" compare contra
    # NaN e propague NaN para sempre.
    valid_atr_mask = atr.notna()
    if not valid_atr_mask.any():
        supertrend[:] = np.nan
        direction[:] = 1
        return SuperTrendResult(supertrend=supertrend, direction=direction)

    start_idx = int(np.argmax(valid_atr_mask.to_numpy()))

    supertrend.iloc[:start_idx] = np.nan
    direction.iloc[:start_idx] = 1

    final_upper.iloc[start_idx] = basic_upper.iloc[start_idx]
    final_lower.iloc[start_idx] = basic_lower.iloc[start_idx]
    direction.iloc[start_idx] = 1 if close.iloc[start_idx] >= (final_upper.iloc[start_idx] + final_lower.iloc[start_idx]) / 2 else -1
    supertrend.iloc[start_idx] = (
        final_lower.iloc[start_idx] if direction.iloc[start_idx] == 1 else final_upper.iloc[start_idx]
    )

    for i in range(start_idx + 1, len(df)):
        # Banda superior/inferior "final": só se move na direção que
        # aperta o canal, nunca se afasta do preço na mesma tendência.
        if basic_upper.iloc[i] < final_upper.iloc[i - 1] or close.iloc[i - 1] > final_upper.iloc[i - 1]:
            final_upper.iloc[i] = basic_upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]

        if basic_lower.iloc[i] > final_lower.iloc[i - 1] or close.iloc[i - 1] < final_lower.iloc[i - 1]:
            final_lower.iloc[i] = basic_lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

        previous_direction = direction.iloc[i - 1]

        if previous_direction == 1:
            new_direction = -1 if close.iloc[i] < final_lower.iloc[i] else 1
        else:
            new_direction = 1 if close.iloc[i] > final_upper.iloc[i] else -1

        direction.iloc[i] = new_direction
        supertrend.iloc[i] = final_lower.iloc[i] if new_direction == 1 else final_upper.iloc[i]

    return SuperTrendResult(supertrend=supertrend, direction=direction)


def calculate_parabolic_sar(
    df: pd.DataFrame, af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2
) -> pd.Series:
    """
    Calcula o Parabolic SAR (Stop and Reverse) de Wilder — pontos que
    seguem o preço, acelerando conforme a tendência se estende, usados
    classicamente para trailing stops.

    Args:
        df: DataFrame OHLCV.
        af_start: fator de aceleração inicial.
        af_step: incremento do fator de aceleração a cada novo extremo.
        af_max: fator de aceleração máximo.

    Returns:
        `pandas.Series` com os valores do SAR, alinhada ao índice de `df`.
    """
    high, low = df["high"], df["low"]
    sar = pd.Series(index=df.index, dtype=float)

    # Estado inicial: assume tendência de alta, SAR começa no low do
    # primeiro candle (convenção comum de inicialização).
    is_uptrend = True
    af = af_start
    extreme_point = high.iloc[0]
    sar.iloc[0] = low.iloc[0]

    for i in range(1, len(df)):
        prior_sar = sar.iloc[i - 1]

        if is_uptrend:
            current_sar = prior_sar + af * (extreme_point - prior_sar)
            current_sar = min(current_sar, low.iloc[i - 1], low.iloc[max(i - 2, 0)])

            if low.iloc[i] < current_sar:
                is_uptrend = False
                current_sar = extreme_point
                extreme_point = low.iloc[i]
                af = af_start
            elif high.iloc[i] > extreme_point:
                extreme_point = high.iloc[i]
                af = min(af + af_step, af_max)
        else:
            current_sar = prior_sar + af * (extreme_point - prior_sar)
            current_sar = max(current_sar, high.iloc[i - 1], high.iloc[max(i - 2, 0)])

            if high.iloc[i] > current_sar:
                is_uptrend = True
                current_sar = extreme_point
                extreme_point = high.iloc[i]
                af = af_start
            elif low.iloc[i] < extreme_point:
                extreme_point = low.iloc[i]
                af = min(af + af_step, af_max)

        sar.iloc[i] = current_sar

    return sar


@dataclass(frozen=True, slots=True)
class IchimokuResult:
    """Agrupa as cinco linhas do Ichimoku Kinko Hyo."""

    tenkan_sen: pd.Series
    kijun_sen: pd.Series
    senkou_span_a: pd.Series
    senkou_span_b: pd.Series
    chikou_span: pd.Series


def calculate_ichimoku(
    df: pd.DataFrame,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> IchimokuResult:
    """
    Calcula o Ichimoku Kinko Hyo completo (Tenkan-sen, Kijun-sen,
    Senkou Span A/B e Chikou Span), incluindo os deslocamentos
    (projeção futura da nuvem, defasagem do Chikou Span).
    """
    high, low, close = df["high"], df["low"], df["close"]

    def _midpoint_channel(period: int) -> pd.Series:
        return (
            high.rolling(window=period, min_periods=period).max()
            + low.rolling(window=period, min_periods=period).min()
        ) / 2

    tenkan_sen = _midpoint_channel(tenkan_period)
    kijun_sen = _midpoint_channel(kijun_period)

    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(displacement)
    senkou_span_b = _midpoint_channel(senkou_b_period).shift(displacement)

    chikou_span = close.shift(-displacement)

    return IchimokuResult(
        tenkan_sen=tenkan_sen,
        kijun_sen=kijun_sen,
        senkou_span_a=senkou_span_a,
        senkou_span_b=senkou_span_b,
        chikou_span=chikou_span,
    )
