"""
structure/bos.py
==================

Detecção de BOS (Break of Structure).

BOS ocorre quando o preço rompe o último swing relevante NA DIREÇÃO da
tendência vigente, confirmando sua continuação:

- Em tendência de alta: fechamento acima do último swing high.
- Em tendência de baixa: fechamento abaixo do último swing low.
"""

from __future__ import annotations

import pandas as pd


def detect_bos(swings: pd.DataFrame, close: pd.Series, trend: str) -> bool:
    """
    Verifica se houve um BOS na direção da tendência informada.

    Args:
        swings: DataFrame de swing points (saída de `structure.swings.get_swing_points`),
            com colunas "price" e "type" ("high" | "low").
        close: série de preços de fechamento.
        trend: tendência vigente ("Bullish", "Bearish" ou "Ranging").

    Returns:
        True se o preço atual rompeu o último swing relevante na
        direção da tendência.
    """
    if swings.empty or close.empty:
        return False

    last_price = close.iloc[-1]

    if trend == "Bullish":
        last_highs = swings.loc[swings["type"] == "high", "price"]
        if last_highs.empty:
            return False
        return bool(last_price > last_highs.iloc[-1])

    if trend == "Bearish":
        last_lows = swings.loc[swings["type"] == "low", "price"]
        if last_lows.empty:
            return False
        return bool(last_price < last_lows.iloc[-1])

    return False
