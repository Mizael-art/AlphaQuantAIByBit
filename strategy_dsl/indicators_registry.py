"""
strategy_dsl/indicators_registry.py
======================================

Tabela de indicadores suportados pelo DSL (Documento 1, seção 4) e a
função que os calcula a partir do `IndicatorSpec` declarado no schema.

Reaproveita 100% do que já existe em `indicators/` -- este módulo NÃO
reimplementa RSI/MACD/ATR/Bollinger/etc., só faz a ponte entre o nome
público usado no schema (ex.: "RSI") e a função Python já testada.

SMA e WMA não existem em `indicators/` (só EMA) -- são calculados aqui
diretamente via pandas (são triviais e não precisam de módulo próprio).
HMA fica como não-suportado por enquanto (ver `UNSUPPORTED_INDICATORS`)
porque não há implementação existente pra reaproveitar e não é uma
prioridade do Documento 1 em relação ao resto.

Nunca substitui um indicador não suportado por outro parecido --
`UnsupportedIndicatorError` é levantado explicitamente.
"""

from __future__ import annotations

import pandas as pd

from indicators.atr import calculate_atr
from indicators.bands_channels import calculate_bollinger_bands, calculate_donchian_channels
from indicators.ema import calculate_ema
from indicators.macd import calculate_macd
from indicators.momentum_extra import calculate_roc, calculate_stochastic
from indicators.rsi import calculate_rsi
from indicators.volume import calculate_volume_average
from indicators.volume_extra import calculate_obv
from indicators.vwap import calculate_vwap
from strategy_dsl.errors import UnsupportedIndicatorError
from strategy_dsl.schema import IndicatorSpec

# Indicadores suportados hoje (Documento 1, seção 4) -- fonte da verdade
# consumida também por `capabilities.py` e pelo endpoint `/schema_capabilities`.
SUPPORTED_INDICATORS: frozenset[str] = frozenset(
    {
        "SMA", "EMA", "WMA",
        "RSI", "MACD", "ROC", "STOCHASTIC",
        "ATR", "BOLLINGER", "DONCHIAN",
        "VOLUME_SMA", "OBV", "VWAP",
        "HIGHEST", "LOWEST",
    }
)

# Indicadores citados no Documento 1 (seção 4) que ainda não têm
# implementação de origem para reaproveitar -- listados explicitamente
# para o `schema_capabilities` nunca fingir suporte por omissão.
UNSUPPORTED_INDICATORS: frozenset[str] = frozenset({"HMA", "PIVOT_HIGH", "PIVOT_LOW", "BREAKOUT"})


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def _wma(series: pd.Series, period: int) -> pd.Series:
    weights = pd.Series(range(1, period + 1), dtype=float)
    return series.rolling(period).apply(lambda w: (w * weights.values).sum() / weights.sum(), raw=True)


def compute_indicator(df: pd.DataFrame, spec: IndicatorSpec) -> dict[str, pd.Series]:
    """
    Calcula um `IndicatorSpec` sobre o DataFrame de candles (colunas
    `open/high/low/close/volume`, já ordenado cronologicamente).

    Returns:
        dict alias -> Series. A maioria dos indicadores produz uma
        única série (`{spec.id: serie}`); indicadores com múltiplas
        saídas (MACD, Bollinger, Donchian, Stochastic) produzem uma
        série por componente, com sufixo (`{id}_LINE`, `{id}_UPPER`
        etc.), documentado em `schema_capabilities`.

    Raises:
        UnsupportedIndicatorError: `spec.type` não está em
            `SUPPORTED_INDICATORS`.
    """
    kind = spec.type.upper()
    if kind not in SUPPORTED_INDICATORS:
        raise UnsupportedIndicatorError(spec.type)

    source = df[spec.source] if spec.source in df.columns else df["close"]
    period = spec.period

    if kind == "SMA":
        return {spec.id: _sma(source, period)}
    if kind == "EMA":
        return {spec.id: calculate_ema(source, period)}
    if kind == "WMA":
        return {spec.id: _wma(source, period)}
    if kind == "RSI":
        return {spec.id: calculate_rsi(source, period)}
    if kind == "ATR":
        return {spec.id: calculate_atr(df, period)}
    if kind == "ROC":
        return {spec.id: calculate_roc(source, period)}
    if kind == "VOLUME_SMA":
        return {spec.id: calculate_volume_average(df, period)}
    if kind == "OBV":
        return {spec.id: calculate_obv(df)}
    if kind == "VWAP":
        return {spec.id: calculate_vwap(df)}
    if kind == "HIGHEST":
        return {spec.id: source.rolling(period).max()}
    if kind == "LOWEST":
        return {spec.id: source.rolling(period).min()}

    if kind == "MACD":
        fast = int(spec.params.get("fast", 12))
        slow = int(spec.params.get("slow", 26))
        signal = int(spec.params.get("signal", 9))
        result = calculate_macd(source, fast_period=fast, slow_period=slow, signal_period=signal)
        return {
            f"{spec.id}_LINE": result.macd_line,
            f"{spec.id}_SIGNAL": result.signal_line,
            f"{spec.id}_HIST": result.histogram,
        }
    if kind == "BOLLINGER":
        std_dev = float(spec.params.get("std_dev", 2.0))
        result = calculate_bollinger_bands(df, period=period, std_dev=std_dev)
        return {f"{spec.id}_UPPER": result.upper, f"{spec.id}_MID": result.middle, f"{spec.id}_LOWER": result.lower}
    if kind == "DONCHIAN":
        result = calculate_donchian_channels(df, period=period)
        return {f"{spec.id}_UPPER": result.upper, f"{spec.id}_MID": result.middle, f"{spec.id}_LOWER": result.lower}
    if kind == "STOCHASTIC":
        k_period = int(spec.params.get("k_period", period or 14))
        d_period = int(spec.params.get("d_period", 3))
        result = calculate_stochastic(df, k_period=k_period, d_period=d_period)
        return {f"{spec.id}_K": result.percent_k, f"{spec.id}_D": result.percent_d}

    # Não deveria chegar aqui (kind já validado contra SUPPORTED_INDICATORS),
    # mas nunca cai num retorno silencioso caso a tabela e o dispatch divirjam.
    raise UnsupportedIndicatorError(spec.type)
