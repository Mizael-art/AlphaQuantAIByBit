"""
indicators
==========

Pacote com o cálculo de indicadores técnicos usados na análise:
EMA (20/50/100/200), RSI(14), ATR(14), MACD e Volume Médio.

Cada módulo expõe funções puras que recebem um `pandas.DataFrame`
OHLCV (índice temporal, colunas open/high/low/close/volume) e
retornam `pandas.Series` alinhadas ao mesmo índice.
"""

from indicators.atr import calculate_atr
from indicators.bands_channels import (
    calculate_bollinger_bands,
    calculate_donchian_channels,
    calculate_keltner_channels,
)
from indicators.ema import calculate_all_emas, calculate_ema
from indicators.macd import calculate_macd
from indicators.momentum_extra import (
    calculate_adx,
    calculate_cci,
    calculate_mfi,
    calculate_roc,
    calculate_stochastic,
    calculate_williams_r,
)
from indicators.rsi import calculate_rsi
from indicators.trend_extra import calculate_ichimoku, calculate_parabolic_sar, calculate_supertrend
from indicators.volume import calculate_volume_average
from indicators.volume_extra import calculate_cmf, calculate_obv
from indicators.vwap import calculate_anchored_vwap, calculate_session_vwap, calculate_vwap

__all__ = [
    "calculate_ema",
    "calculate_all_emas",
    "calculate_rsi",
    "calculate_atr",
    "calculate_macd",
    "calculate_volume_average",
    "calculate_vwap",
    "calculate_anchored_vwap",
    "calculate_session_vwap",
    "calculate_adx",
    "calculate_cci",
    "calculate_mfi",
    "calculate_roc",
    "calculate_stochastic",
    "calculate_williams_r",
    "calculate_obv",
    "calculate_cmf",
    "calculate_bollinger_bands",
    "calculate_donchian_channels",
    "calculate_keltner_channels",
    "calculate_supertrend",
    "calculate_parabolic_sar",
    "calculate_ichimoku",
]
