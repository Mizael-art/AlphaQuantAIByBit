"""
statistics_/volatility.py
============================

Métricas estatísticas de volatilidade e posicionamento relativo do
preço: desvio padrão, Z-score, volatilidade histórica (anualizada),
volatilidade realizada e percentis.

Nome do pacote com sufixo "_" (`statistics_`) para não colidir com o
módulo `statistics` da biblioteca padrão do Python.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Fator de anualização aproximado por timeframe, usado na volatilidade
# histórica (raiz do número de períodos por ano). Baseado em um
# mercado 24/7 (cripto).
_PERIODS_PER_YEAR: dict[str, float] = {
    "1m": 525_600, "3m": 175_200, "5m": 105_120, "15m": 35_040,
    "30m": 17_520, "1H": 8_760, "2H": 4_380, "4H": 2_190,
    "6H": 1_460, "8H": 1_095, "12H": 730, "1D": 365,
    "3D": 121.67, "1W": 52, "1M": 12,
}


@dataclass(frozen=True, slots=True)
class VolatilityStats:
    """Conjunto de métricas de volatilidade e posicionamento estatístico do preço."""

    std_dev: float
    z_score: float
    historical_volatility_pct: float | None
    realized_volatility_pct: float
    percentile_rank: float


def calculate_std_dev(series: pd.Series, period: int = 20) -> pd.Series:
    """Desvio padrão móvel do preço nos últimos `period` candles."""
    return series.rolling(window=period, min_periods=period).std()


def calculate_z_score(series: pd.Series, period: int = 20) -> pd.Series:
    """
    Calcula o Z-score do preço atual em relação à média/desvio padrão
    móvel dos últimos `period` candles — mede quantos desvios padrão o
    preço está distante da sua média recente (útil para identificar
    condições estatisticamente extremas / mean-reversion).
    """
    mean = series.rolling(window=period, min_periods=period).mean()
    std = series.rolling(window=period, min_periods=period).std()
    return (series - mean) / std.replace(0, np.nan)


def calculate_log_returns(series: pd.Series) -> pd.Series:
    """Retornos logarítmicos período a período — base para métricas de volatilidade."""
    return np.log(series / series.shift(1))


def calculate_historical_volatility(
    series: pd.Series, period: int = 20, timeframe: str | None = None
) -> pd.Series:
    """
    Calcula a volatilidade histórica anualizada (%), a partir do
    desvio padrão dos retornos logarítmicos.

    Args:
        series: série de preços de fechamento.
        period: janela usada no cálculo do desvio padrão dos retornos.
        timeframe: timeframe dos candles (ex.: "4H", "1D"), usado para
            anualizar corretamente. Se None ou desconhecido, retorna a
            volatilidade NÃO anualizada (apenas o desvio padrão dos
            retornos no período, em %).

    Returns:
        `pandas.Series` com a volatilidade histórica em percentual.
    """
    log_returns = calculate_log_returns(series)
    rolling_std = log_returns.rolling(window=period, min_periods=period).std()

    periods_per_year = _PERIODS_PER_YEAR.get(timeframe) if timeframe else None
    if periods_per_year is None:
        return rolling_std * 100

    return rolling_std * np.sqrt(periods_per_year) * 100


def calculate_realized_volatility(series: pd.Series, period: int = 20) -> pd.Series:
    """
    Calcula a volatilidade realizada (%): raiz da soma dos retornos
    logarítmicos ao quadrado na janela — mede a volatilidade
    efetivamente "realizada" no período, sem anualização.
    """
    log_returns = calculate_log_returns(series)
    return np.sqrt((log_returns**2).rolling(window=period, min_periods=period).sum()) * 100


def calculate_percentile_rank(series: pd.Series, period: int = 100) -> pd.Series:
    """
    Calcula o percentil do preço atual em relação aos últimos `period`
    candles (0 = mínimo do período, 100 = máximo do período).
    """

    def _rank(window: np.ndarray) -> float:
        current = window[-1]
        return float((window < current).sum() / (len(window) - 1) * 100) if len(window) > 1 else 50.0

    return series.rolling(window=period, min_periods=period).apply(_rank, raw=True)


def build_volatility_stats(df: pd.DataFrame, timeframe: str | None = None, period: int = 20) -> VolatilityStats:
    """
    Constrói o snapshot completo de estatísticas de volatilidade para o
    último candle do DataFrame.
    """
    close = df["close"]

    std_dev = calculate_std_dev(close, period).iloc[-1]
    z_score = calculate_z_score(close, period).iloc[-1]
    historical_vol = calculate_historical_volatility(close, period, timeframe).iloc[-1]
    realized_vol = calculate_realized_volatility(close, period).iloc[-1]
    percentile = calculate_percentile_rank(close, period=min(100, len(df))).iloc[-1]

    return VolatilityStats(
        std_dev=float(std_dev) if pd.notna(std_dev) else 0.0,
        z_score=float(z_score) if pd.notna(z_score) else 0.0,
        historical_volatility_pct=float(historical_vol) if pd.notna(historical_vol) else None,
        realized_volatility_pct=float(realized_vol) if pd.notna(realized_vol) else 0.0,
        percentile_rank=float(percentile) if pd.notna(percentile) else 50.0,
    )
