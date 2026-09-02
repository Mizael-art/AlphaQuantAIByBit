"""
regime
======

Regime-First Engine (Fase 3 do Plano de Evolução -- Documento 2, seções
7-9; Documento Master, seções 7, 12-14). Detecção de regime de mercado,
força relativa vs. BTC e classificação de contexto BTC para altcoins.

Todas as funções aqui são puras (recebem métricas já calculadas,
devolvem uma classificação) -- quem calcula os inputs a partir de
candles reais é `discovery/engine.py`.
"""

from regime.btc_filter import BTC_HOSTILE, BTC_NEUTRAL, BTC_SUPPORTIVE, classify_btc_context
from regime.detector import ALL_REGIMES, RegimeResult, detect_regime
from regime.relative_strength import NEUTRAL, STRONG, WEAK, RelativeStrengthResult, classify_relative_strength

__all__ = [
    "ALL_REGIMES",
    "RegimeResult",
    "detect_regime",
    "RelativeStrengthResult",
    "classify_relative_strength",
    "STRONG",
    "WEAK",
    "NEUTRAL",
    "classify_btc_context",
    "BTC_SUPPORTIVE",
    "BTC_NEUTRAL",
    "BTC_HOSTILE",
]
