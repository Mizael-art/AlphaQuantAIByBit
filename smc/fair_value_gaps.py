"""
smc/fair_value_gaps.py
========================

Detecção de Fair Value Gaps (FVG) e Inverse Fair Value Gaps (iFVG).

Um FVG (também chamado de "imbalance") ocorre quando há um desequilíbrio
entre compradores e vendedores forte o suficiente para deixar um "gap"
de 3 candles sem sobreposição de preço:

- FVG de alta (bullish): low do candle 3 > high do candle 1.
  O gap fica entre high(candle1) e low(candle3).
- FVG de baixa (bearish): high do candle 3 < low do candle 1.
  O gap fica entre high(candle3) e low(candle1).

Um FVG é considerado "mitigado" quando o preço retorna e preenche
(parcial ou totalmente) o gap. Um iFVG é um FVG mitigado que inverteu
de função: um gap bullish que foi rompido para baixo passa a atuar
como resistência (e vice-versa).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd


@dataclass(frozen=True, slots=True)
class FVGZone:
    """Representa uma única Fair Value Gap."""

    direction: str          # "bullish" | "bearish"
    top: float
    bottom: float
    candle_time: datetime   # timestamp do candle do meio (candle 2), onde o gap se forma
    mitigated: bool
    mitigated_pct: float    # 0.0 (não tocado) a 1.0 (totalmente preenchido)
    is_inverse: bool        # True se o gap foi rompido e virou iFVG

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "top": round(float(self.top), 6),
            "bottom": round(float(self.bottom), 6),
            "candle_time": self.candle_time.isoformat(),
            "mitigated": self.mitigated,
            "mitigated_pct": round(float(self.mitigated_pct), 4),
            "is_inverse": self.is_inverse,
        }


def find_fair_value_gaps(df: pd.DataFrame, max_zones: int = 10) -> list[FVGZone]:
    """
    Varre o DataFrame OHLCV em busca de Fair Value Gaps.

    Args:
        df: DataFrame OHLCV (índice temporal, colunas high/low/close).
        max_zones: número máximo de FVGs retornados (as mais recentes).

    Returns:
        Lista de `FVGZone`, ordenada da mais recente para a mais antiga.
    """
    zones: list[FVGZone] = []

    high = df["high"]
    low = df["low"]

    for i in range(2, len(df)):
        candle1_high = high.iloc[i - 2]
        candle1_low = low.iloc[i - 2]
        candle3_high = high.iloc[i]
        candle3_low = low.iloc[i]
        middle_time = df.index[i - 1]

        # FVG de alta: candle 3 abre um gap acima do topo do candle 1.
        if candle3_low > candle1_high:
            top, bottom = candle3_low, candle1_high
            mitigation_pct = _calculate_mitigation(df, i, top, bottom, direction="bullish")
            zones.append(
                FVGZone(
                    direction="bullish",
                    top=top,
                    bottom=bottom,
                    candle_time=middle_time,
                    mitigated=bool(mitigation_pct >= 1.0),
                    mitigated_pct=mitigation_pct,
                    is_inverse=_is_inverse(df, i, top, bottom, direction="bullish"),
                )
            )

        # FVG de baixa: candle 3 abre um gap abaixo do fundo do candle 1.
        elif candle3_high < candle1_low:
            top, bottom = candle1_low, candle3_high
            mitigation_pct = _calculate_mitigation(df, i, top, bottom, direction="bearish")
            zones.append(
                FVGZone(
                    direction="bearish",
                    top=top,
                    bottom=bottom,
                    candle_time=middle_time,
                    mitigated=bool(mitigation_pct >= 1.0),
                    mitigated_pct=mitigation_pct,
                    is_inverse=_is_inverse(df, i, top, bottom, direction="bearish"),
                )
            )

    # Mais recentes primeiro.
    zones.sort(key=lambda z: z.candle_time, reverse=True)
    return zones[:max_zones]


def _calculate_mitigation(
    df: pd.DataFrame, formed_at_index: int, top: float, bottom: float, direction: str
) -> float:
    """
    Calcula o quanto do gap já foi preenchido pelos candles posteriores
    à sua formação (0.0 = intocado, 1.0 = totalmente preenchido).
    """
    gap_size = top - bottom
    if gap_size <= 0:
        return 0.0

    subsequent = df.iloc[formed_at_index + 1:]
    if subsequent.empty:
        return 0.0

    if direction == "bullish":
        # Preenchido de cima para baixo: o quanto o "low" penetrou no gap.
        deepest_penetration = top - subsequent["low"].min()
    else:
        # Preenchido de baixo para cima: o quanto o "high" penetrou no gap.
        deepest_penetration = subsequent["high"].max() - bottom

    penetration_pct = max(0.0, min(1.0, deepest_penetration / gap_size))
    return penetration_pct


def _is_inverse(
    df: pd.DataFrame, formed_at_index: int, top: float, bottom: float, direction: str
) -> bool:
    """
    Determina se o gap foi completamente rompido (não apenas mitigado)
    e, portanto, passou a atuar como iFVG (função invertida).
    """
    subsequent = df.iloc[formed_at_index + 1:]
    if subsequent.empty:
        return False

    if direction == "bullish":
        # Rompimento total: fechamento abaixo do fundo do gap.
        return bool((subsequent["close"] < bottom).any())
    return bool((subsequent["close"] > top).any())
