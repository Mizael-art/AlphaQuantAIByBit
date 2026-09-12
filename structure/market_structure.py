"""
structure/market_structure.py
===============================

Orquestra a detecção completa de estrutura de mercado:

1. Encontra os swing points (highs/lows) via `structure.swings`.
2. Classifica os dois últimos highs e os dois últimos lows em
   HH/LH e HL/LL, respectivamente.
3. Deriva a tendência estrutural (Bullish / Bearish / Ranging).
4. Detecta BOS e CHOCH via `structure.bos` e `structure.choch`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import STRUCTURE_CONFIG
from structure.bos import detect_bos
from structure.choch import detect_choch
from structure.swings import get_swing_points


@dataclass(frozen=True, slots=True)
class MarketStructureResult:
    """Resultado completo da análise de estrutura de mercado."""

    trend: str
    hh: bool
    hl: bool
    lh: bool
    ll: bool
    bos: bool
    choch: bool
    swing_high: float | None
    swing_low: float | None


def _classify_swing_sequence(prices: pd.Series) -> tuple[bool, bool]:
    """
    Compara os dois últimos valores de uma sequência de swings (highs
    OU lows) e retorna (is_higher, is_lower).

    Ex.: para swing highs, is_higher == HH e is_lower == LH.
         para swing lows, is_higher == HL e is_lower == LL.
    """
    if len(prices) < 2:
        return False, False

    last, previous = prices.iloc[-1], prices.iloc[-2]
    return bool(last > previous), bool(last < previous)


def analyze_market_structure(
    df: pd.DataFrame,
    lookback: int | None = None,
) -> MarketStructureResult:
    """
    Executa a análise completa de estrutura de mercado sobre um
    DataFrame OHLCV.

    Args:
        df: DataFrame OHLCV (índice temporal, colunas high/low/close).
        lookback: candles à esquerda/direita usados na confirmação de
            swings (padrão: `config.STRUCTURE_CONFIG.swing_lookback`).

    Returns:
        `MarketStructureResult` com tendência, HH/HL/LH/LL, BOS, CHOCH
        e os últimos swing high/low.
    """
    lookback = lookback or STRUCTURE_CONFIG.swing_lookback
    swings = get_swing_points(df, lookback=lookback)

    swing_highs = swings.loc[swings["type"] == "high", "price"]
    swing_lows = swings.loc[swings["type"] == "low", "price"]

    hh, lh = _classify_swing_sequence(swing_highs)
    hl, ll = _classify_swing_sequence(swing_lows)

    # Tendência estrutural: só é definida como Bullish/Bearish quando
    # highs e lows concordam; caso contrário, o mercado está em range
    # ou em transição.
    if hh and hl:
        trend = "Bullish"
    elif lh and ll:
        trend = "Bearish"
    else:
        trend = "Ranging"

    bos = detect_bos(swings, df["close"], trend)
    choch = detect_choch(swings, df["close"], trend)

    last_swing_high = float(swing_highs.iloc[-1]) if not swing_highs.empty else None
    last_swing_low = float(swing_lows.iloc[-1]) if not swing_lows.empty else None

    return MarketStructureResult(
        trend=trend,
        hh=hh,
        hl=hl,
        lh=lh,
        ll=ll,
        bos=bos,
        choch=choch,
        swing_high=last_swing_high,
        swing_low=last_swing_low,
    )
