"""
analysis/support_resistance.py
=================================

Deriva níveis de suporte e resistência a partir dos swing points
(`structure.swings.get_swing_points`) mais próximos do preço atual.

Abordagem:

1. Swing highs acima do preço atual -> candidatos a resistência.
   Swing lows abaixo do preço atual -> candidatos a suporte.
2. Níveis muito próximos entre si (dentro de
   `ANALYSIS_CONFIG.price_cluster_tolerance_pct`) são agrupados em uma
   única zona (usa a média do cluster) -- evita listar 3 resistências
   que na prática são a mesma zona.
3. Retorna os `ANALYSIS_CONFIG.max_levels_returned` níveis mais
   próximos do preço atual, em cada lado.
"""

from __future__ import annotations

import pandas as pd

from config import ANALYSIS_CONFIG


def _cluster_levels(levels: list[float], tolerance_pct: float) -> list[float]:
    """
    Agrupa níveis de preço próximos (dentro de `tolerance_pct`) em uma
    única zona (média do cluster). `levels` deve vir ordenado.
    """
    if not levels:
        return []

    clusters: list[list[float]] = [[levels[0]]]
    for level in levels[1:]:
        cluster_avg = sum(clusters[-1]) / len(clusters[-1])
        if cluster_avg == 0:
            clusters.append([level])
            continue
        distance_pct = abs(level - cluster_avg) / abs(cluster_avg) * 100
        if distance_pct <= tolerance_pct:
            clusters[-1].append(level)
        else:
            clusters.append([level])

    return [sum(cluster) / len(cluster) for cluster in clusters]


def find_support_resistance(
    df: pd.DataFrame,
    swings: pd.DataFrame,
    current_price: float,
) -> tuple[list[float], list[float]]:
    """
    Encontra os níveis de suporte e resistência mais relevantes.

    Args:
        df: DataFrame OHLCV (não usado diretamente hoje -- mantido na
            assinatura para permitir refinamentos futuros, ex.: peso
            por volume no nível, sem quebrar quem já chama esta
            função. `swings` já carrega tudo que é necessário).
        swings: saída de `structure.swings.get_swing_points` (colunas
            "price", "type").
        current_price: preço atual do ativo.

    Returns:
        Tupla `(support, resistance)`, cada uma uma lista de até
        `ANALYSIS_CONFIG.max_levels_returned` níveis de preço,
        ordenados do mais próximo ao mais distante do preço atual.
    """
    if swings.empty:
        return [], []

    swing_highs = swings.loc[swings["type"] == "high", "price"]
    swing_lows = swings.loc[swings["type"] == "low", "price"]

    resistance_candidates = sorted(float(p) for p in swing_highs if p > current_price)
    support_candidates = sorted((float(p) for p in swing_lows if p < current_price), reverse=True)

    tolerance = ANALYSIS_CONFIG.price_cluster_tolerance_pct
    max_levels = ANALYSIS_CONFIG.max_levels_returned

    # Cluster preserva ordem de proximidade: resistance sobe a partir do
    # preço (ordenado asc), support desce a partir do preço (ordenado desc).
    resistance = _cluster_levels(resistance_candidates, tolerance)[:max_levels]
    support = _cluster_levels(support_candidates, tolerance)[:max_levels]

    return (
        [round(level, 6) for level in support],
        [round(level, 6) for level in resistance],
    )
