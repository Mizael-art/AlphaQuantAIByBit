"""
analysis/liquidity.py
========================

Zonas de liquidez no sentido Smart Money Concepts: onde estão os stops
"resting" que o mercado tende a caçar antes de reverter/continuar.

- **buy_side**: liquidez ACIMA do preço -- stops de vendedores vendidos
  e ordens de compra de breakout, acumulados logo acima de swing
  highs. É "buy-side" porque um sweep ali dispara COMPRAS (stop-loss de
  posições vendidas sendo estopadas).
- **sell_side**: liquidez ABAIXO do preço -- stops de comprados e
  ordens de venda de breakdown, acumulados logo abaixo de swing lows.
  Um sweep ali dispara VENDAS.

Esta é uma leitura estrutural simples (swing highs/lows brutos), não o
mesmo dado que `smc.liquidity_sweeps` e `smc.equal_highs_lows` (que já
detectam eventos de varredura e igualdades de forma mais rigorosa) --
aqui o objetivo é só mapear ONDE a liquidez plausivelmente está, para
o campo `liquidity` do snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from config import ANALYSIS_CONFIG


@dataclass(frozen=True, slots=True)
class LiquidityZones:
    """Zonas de liquidez identificadas, separadas por lado."""

    buy_side: list[float] = field(default_factory=list)
    sell_side: list[float] = field(default_factory=list)


def find_liquidity_zones(swings: pd.DataFrame) -> LiquidityZones:
    """
    Deriva as zonas de liquidez a partir dos swing points.

    Args:
        swings: saída de `structure.swings.get_swing_points` (colunas
            "price", "type"), em ordem cronológica.

    Returns:
        `LiquidityZones` com os `ANALYSIS_CONFIG.max_levels_returned`
        swing highs mais recentes (buy_side) e swing lows mais
        recentes (sell_side).
    """
    if swings.empty:
        return LiquidityZones()

    max_levels = ANALYSIS_CONFIG.max_levels_returned

    swing_highs = swings.loc[swings["type"] == "high", "price"]
    swing_lows = swings.loc[swings["type"] == "low", "price"]

    # Mais recentes primeiro -- liquidez recente é mais relevante que
    # um swing de meses atrás que o mercado já pode ter "limpado".
    buy_side = [round(float(p), 6) for p in swing_highs.iloc[::-1].head(max_levels)]
    sell_side = [round(float(p), 6) for p in swing_lows.iloc[::-1].head(max_levels)]

    return LiquidityZones(buy_side=buy_side, sell_side=sell_side)
