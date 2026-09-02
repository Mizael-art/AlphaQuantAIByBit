"""
analysis
========

Camada final de interpretação: combina indicadores clássicos +
estrutura de mercado (já calculados em `indicators/` e `structure/`)
em quatro conclusões de mais alto nível:

    trend.py              -- tendência final (EMA stack + estrutura)
    support_resistance.py -- níveis de S/R a partir dos swing points
    liquidity.py           -- zonas de liquidez (buy-side / sell-side)
    score.py               -- score técnico combinado (0-100)

Nenhum destes módulos busca dado de rede -- todos são funções puras
que recebem o que já foi calculado a montante (`df`, `swings`,
resultado de `structure.market_structure`) e devolvem um veredito.

Nota de reconstrução: este pacote não veio no zip
`AlphaQuantEngine_v2_6_structure_consensus` (import quebrado em
`app.py` e `snapshot/timeframe_snapshot.py`). Foi reconstruído a
partir do uso real desses dois arquivos (assinaturas, tipos de
retorno) -- ver CHANGELOG_v2.6_rebuild.md para detalhes.
"""

from analysis.liquidity import LiquidityZones, find_liquidity_zones
from analysis.score import calculate_score
from analysis.support_resistance import find_support_resistance
from analysis.trend import determine_trend

__all__ = [
    "determine_trend",
    "find_support_resistance",
    "find_liquidity_zones",
    "LiquidityZones",
    "calculate_score",
]
