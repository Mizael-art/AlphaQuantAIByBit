"""
smc/equal_highs_lows.py
=========================

Detecção de Equal Highs (EQH) e Equal Lows (EQL).

Equal Highs/Lows ocorrem quando dois ou mais swing points ficam a uma
distância percentual muito pequena entre si — indicando uma zona de
liquidez concentrada (stops de quem vendeu no topo / comprou no fundo),
um alvo comum para "liquidity sweeps" antes de um movimento real.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from structure.swings import get_swing_points


@dataclass(frozen=True, slots=True)
class EqualLevel:
    """Representa uma zona de Equal Highs ou Equal Lows."""

    kind: str                  # "equal_high" | "equal_low"
    price_avg: float
    touches: int
    first_touch: datetime
    last_touch: datetime
    swept: bool                 # True se o preço já rompeu a zona depois da última formação

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "price": round(self.price_avg, 6),
            "touches": self.touches,
            "first_touch": self.first_touch.isoformat(),
            "last_touch": self.last_touch.isoformat(),
            "swept": self.swept,
        }


def find_equal_highs_lows(
    df: pd.DataFrame,
    tolerance_pct: float = 0.1,
    swing_lookback: int = 2,
    max_levels: int = 5,
) -> tuple[list[EqualLevel], list[EqualLevel]]:
    """
    Identifica zonas de Equal Highs e Equal Lows a partir dos swing points.

    Args:
        df: DataFrame OHLCV.
        tolerance_pct: tolerância percentual para considerar dois swings
            "iguais" (padrão 0.1%).
        swing_lookback: lookback usado na detecção de swings.
        max_levels: número máximo de zonas retornadas por tipo (as mais recentes).

    Returns:
        Tupla (equal_highs, equal_lows), cada uma como lista de `EqualLevel`.
    """
    swings = get_swing_points(df, lookback=swing_lookback)

    highs = swings.loc[swings["type"] == "high"]
    lows = swings.loc[swings["type"] == "low"]

    equal_highs = _cluster_equal_levels(df, highs, kind="equal_high", tolerance_pct=tolerance_pct)
    equal_lows = _cluster_equal_levels(df, lows, kind="equal_low", tolerance_pct=tolerance_pct)

    return equal_highs[-max_levels:], equal_lows[-max_levels:]


def _cluster_equal_levels(
    df: pd.DataFrame, points: pd.DataFrame, kind: str, tolerance_pct: float
) -> list[EqualLevel]:
    """Agrupa swing points próximos em zonas de Equal High/Low com 2+ toques."""
    if points.empty:
        return []

    prices = points["price"].tolist()
    times = list(points.index)

    clusters: list[dict] = []

    for price, time in zip(prices, times):
        matched = False
        for cluster in clusters:
            distance_pct = abs(price - cluster["avg"]) / cluster["avg"] * 100
            if distance_pct <= tolerance_pct:
                cluster["prices"].append(price)
                cluster["times"].append(time)
                cluster["avg"] = sum(cluster["prices"]) / len(cluster["prices"])
                matched = True
                break
        if not matched:
            clusters.append({"prices": [price], "times": [time], "avg": price})

    levels: list[EqualLevel] = []
    for cluster in clusters:
        if len(cluster["prices"]) < 2:
            continue  # exige ao menos 2 toques para ser considerado "equal"

        avg_price = cluster["avg"]
        last_touch = max(cluster["times"])
        swept = _was_swept(df, avg_price, last_touch, kind)

        levels.append(
            EqualLevel(
                kind=kind,
                price_avg=avg_price,
                touches=len(cluster["prices"]),
                first_touch=min(cluster["times"]),
                last_touch=last_touch,
                swept=swept,
            )
        )

    return levels


def _was_swept(df: pd.DataFrame, level_price: float, last_touch: pd.Timestamp, kind: str) -> bool:
    """Verifica se o preço rompeu a zona depois do último toque conhecido."""
    subsequent = df.loc[df.index > last_touch]
    if subsequent.empty:
        return False

    if kind == "equal_high":
        return bool((subsequent["high"] > level_price).any())
    return bool((subsequent["low"] < level_price).any())
