"""
structure/choch.py
====================

Detecção de CHOCH (Change of Character).

CHOCH ocorre quando o preço rompe o último swing relevante NA DIREÇÃO
CONTRÁRIA à tendência vigente — o primeiro sinal técnico de uma
possível reversão de tendência:

- Em tendência de alta: fechamento abaixo do último swing low.
- Em tendência de baixa: fechamento acima do último swing high.
"""

from __future__ import annotations

import pandas as pd


def detect_choch(swings: pd.DataFrame, close: pd.Series, trend: str) -> bool:
    """
    Verifica se houve um CHOCH (quebra de estrutura contrária à tendência).

    Args:
        swings: DataFrame de swing points (saída de `structure.swings.get_swing_points`),
            com colunas "price" e "type" ("high" | "low").
        close: série de preços de fechamento.
        trend: tendência vigente ("Bullish", "Bearish" ou "Ranging").

    Returns:
        True se o preço atual rompeu o último swing relevante na
        direção CONTRÁRIA à tendência (possível reversão).
    """
    if swings.empty or close.empty:
        return False

    last_price = close.iloc[-1]

    if trend == "Bullish":
        last_lows = swings.loc[swings["type"] == "low", "price"]
        if last_lows.empty:
            return False
        return bool(last_price < last_lows.iloc[-1])

    if trend == "Bearish":
        last_highs = swings.loc[swings["type"] == "high", "price"]
        if last_highs.empty:
            return False
        return bool(last_price > last_highs.iloc[-1])

    return False
