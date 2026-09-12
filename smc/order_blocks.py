"""
smc/order_blocks.py
=====================

Detecção de Order Blocks e Breaker Blocks (Smart Money Concepts).

Definições usadas nesta implementação:

- **Order Block (OB)**: o último candle de cor oposta ao movimento
  antes de um rompimento de estrutura (BOS) impulsivo. Um OB de alta
  (bullish) é o último candle de baixa antes de um rompimento de alta
  de um swing high recente; o inverso para OB de baixa (bearish).
  A zona do OB é definida pelo range (high/low) desse candle.

- **Breaker Block**: um Order Block que foi posteriormente **rompido**
  pelo preço na direção contrária — ou seja, deixou de funcionar como
  suporte/resistência original e passou a atuar com a função invertida
  (um OB bullish rompido para baixo vira resistência, e vice-versa).

- **Mitigado**: o preço retornou à zona do OB pelo menos uma vez após
  sua formação (sem necessariamente rompê-la).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from structure.swings import find_swing_highs, find_swing_lows


@dataclass(frozen=True, slots=True)
class OrderBlock:
    """Representa um único Order Block (ou Breaker Block, se `broken=True`)."""

    direction: str          # "bullish" | "bearish" (direção original do OB)
    top: float
    bottom: float
    formed_at: datetime
    mitigated: bool
    broken: bool             # True = virou Breaker Block (função invertida)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "top": round(self.top, 6),
            "bottom": round(self.bottom, 6),
            "formed_at": self.formed_at.isoformat(),
            "mitigated": self.mitigated,
            "broken": self.broken,
            "role": self._role_label(),
        }

    def _role_label(self) -> str:
        if not self.broken:
            return "order_block"
        return "breaker_block"


def _find_last_opposite_candle(df: pd.DataFrame, break_index: int, bullish_break: bool) -> int | None:
    """
    A partir do índice onde ocorreu o rompimento (`break_index`),
    procura para trás o último candle de cor oposta ao movimento.

    Args:
        bullish_break: True se o rompimento foi de alta (procura o
            último candle de baixa antes dele).

    Returns:
        Índice posicional do candle candidato a Order Block, ou None
        se não encontrado dentro de uma janela razoável (20 candles).
    """
    search_window = range(break_index - 1, max(break_index - 20, -1), -1)

    for i in search_window:
        is_bearish_candle = df["close"].iloc[i] < df["open"].iloc[i]
        is_bullish_candle = df["close"].iloc[i] > df["open"].iloc[i]

        if bullish_break and is_bearish_candle:
            return i
        if not bullish_break and is_bullish_candle:
            return i

    return None


def find_order_blocks(
    df: pd.DataFrame,
    swing_lookback: int = 2,
    max_blocks: int = 10,
) -> list[OrderBlock]:
    """
    Detecta Order Blocks (e seus estados de Breaker Block) em um
    DataFrame OHLCV.

    Args:
        df: DataFrame OHLCV.
        swing_lookback: lookback usado para identificar swing highs/lows
            (mesmo parâmetro usado em `structure.swings`).
        max_blocks: número máximo de blocks retornados (os mais recentes).

    Returns:
        Lista de `OrderBlock`, mais recentes primeiro.
    """
    swing_highs = find_swing_highs(df, lookback=swing_lookback)
    swing_lows = find_swing_lows(df, lookback=swing_lookback)

    close = df["close"]
    blocks: list[OrderBlock] = []
    seen_formation_indices: set[int] = set()

    # Mantém o valor do último swing high/low confirmado, candle a candle.
    last_swing_high: float | None = None
    last_swing_low: float | None = None

    for i in range(len(df)):
        if swing_highs.iloc[i]:
            last_swing_high = df["high"].iloc[i]
        if swing_lows.iloc[i]:
            last_swing_low = df["low"].iloc[i]

        # Rompimento de alta: fechamento acima do último swing high conhecido.
        if last_swing_high is not None and close.iloc[i] > last_swing_high:
            ob_index = _find_last_opposite_candle(df, i, bullish_break=True)
            if ob_index is not None and ob_index not in seen_formation_indices:
                seen_formation_indices.add(ob_index)
                blocks.append(_build_order_block(df, ob_index, direction="bullish"))
            last_swing_high = None  # evita disparar o mesmo OB várias vezes seguidas

        # Rompimento de baixa: fechamento abaixo do último swing low conhecido.
        if last_swing_low is not None and close.iloc[i] < last_swing_low:
            ob_index = _find_last_opposite_candle(df, i, bullish_break=False)
            if ob_index is not None and ob_index not in seen_formation_indices:
                seen_formation_indices.add(ob_index)
                blocks.append(_build_order_block(df, ob_index, direction="bearish"))
            last_swing_low = None

    blocks.sort(key=lambda b: b.formed_at, reverse=True)
    return blocks[:max_blocks]


def _build_order_block(df: pd.DataFrame, formed_index: int, direction: str) -> OrderBlock:
    """Constrói um `OrderBlock`, já calculando mitigação e rompimento (breaker)."""
    top = float(df["high"].iloc[formed_index])
    bottom = float(df["low"].iloc[formed_index])
    formed_at = df.index[formed_index]

    subsequent = df.iloc[formed_index + 1:]

    if subsequent.empty:
        mitigated = False
        broken = False
    elif direction == "bullish":
        # Mitigado: preço voltou a tocar a zona (low <= top).
        mitigated = bool((subsequent["low"] <= top).any())
        # Rompido (breaker): fechamento abaixo do fundo da zona.
        broken = bool((subsequent["close"] < bottom).any())
    else:
        mitigated = bool((subsequent["high"] >= bottom).any())
        broken = bool((subsequent["close"] > top).any())

    return OrderBlock(
        direction=direction,
        top=top,
        bottom=bottom,
        formed_at=formed_at,
        mitigated=mitigated,
        broken=broken,
    )
