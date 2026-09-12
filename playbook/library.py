"""
playbook/library.py
======================

Playbook Library inicial (Documento 2, seção 10; Documento Master,
seção 10) -- começando com um subconjunto pequeno (7, não as ~40
listadas nos documentos), conforme o próprio Plano de Evolução definiu
(seção 5, "Riscos e decisões em aberto").

LIMITAÇÃO IMPORTANTE, declarada explicitamente (não escondida): estas
entradas são METADADOS (nome, regimes compatíveis, estilo, RR mínimo)
usados para o FILTRO regime-first do Discovery Engine -- ainda não são
estratégias validadas por backtest (Documento 2, seção 11:
BACKTEST -> OUT-OF-SAMPLE -> FORWARD TEST -> LIVE ELIGIBILITY). Cada
uma delas É formalizável no `strategy_dsl` (Fase 1) e pode/deve ser
rodada via `POST /backtest/generic` antes de qualquer uso real -- isso
ainda não foi feito neste passo, por isso `statistical_edge_available`
no scoring fica `False` por padrão até existirem resultados de backtest
persistidos (Fase 5/6, Learning Engine).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from regime.detector import (
    ACCUMULATION,
    COMPRESSION,
    DISTRIBUTION,
    EXPANSION,
    RANGE,
    TRENDING_DOWN,
    TRENDING_UP,
)

DAY_TRADE: Final = "day_trade"
INTRADAY: Final = "intraday"
SWING: Final = "swing"


@dataclass(frozen=True, slots=True)
class PlaybookEntry:
    name: str
    description: str
    compatible_regimes: frozenset[str]
    directions: frozenset[str]  # {"long"}, {"short"}, ou {"long", "short"}
    style: str
    min_rr: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "compatible_regimes": sorted(self.compatible_regimes),
            "directions": sorted(self.directions),
            "style": self.style,
            "min_rr": self.min_rr,
        }


PLAYBOOK: Final[list[PlaybookEntry]] = [
    PlaybookEntry(
        name="Trend Continuation",
        description="Entrada a favor da tendência dominante após confirmação de continuidade (BOS na direção da tendência).",
        compatible_regimes=frozenset({TRENDING_UP, TRENDING_DOWN}),
        directions=frozenset({"long", "short"}),
        style=SWING,
        min_rr=2.0,
    ),
    PlaybookEntry(
        name="EMA Pullback",
        description="Recuo até uma EMA de referência dentro de uma tendência já estabelecida, com reação a favor da tendência.",
        compatible_regimes=frozenset({TRENDING_UP, TRENDING_DOWN}),
        directions=frozenset({"long", "short"}),
        style=INTRADAY,
        min_rr=1.8,
    ),
    PlaybookEntry(
        name="Liquidity Sweep Reversal",
        description="Varredura de liquidez além de um extremo do range seguida de rejeição e confirmação estrutural (BOS no LTF).",
        compatible_regimes=frozenset({RANGE, ACCUMULATION, DISTRIBUTION}),
        directions=frozenset({"long", "short"}),
        style=DAY_TRADE,
        min_rr=2.5,
    ),
    PlaybookEntry(
        name="Breakout + Retest",
        description="Rompimento de uma zona de compressão/range com retorno (retest) antes da continuação.",
        compatible_regimes=frozenset({COMPRESSION, EXPANSION}),
        directions=frozenset({"long", "short"}),
        style=DAY_TRADE,
        min_rr=2.0,
    ),
    PlaybookEntry(
        name="Compression Breakout",
        description="Entrada na expansão inicial de um squeeze de volatilidade (Bollinger comprimida), sem esperar retest.",
        compatible_regimes=frozenset({COMPRESSION}),
        directions=frozenset({"long", "short"}),
        style=INTRADAY,
        min_rr=2.2,
    ),
    PlaybookEntry(
        name="Range High Rejection",
        description="Rejeição no topo de um range estabelecido, a favor de reversão/distribuição.",
        compatible_regimes=frozenset({RANGE, DISTRIBUTION}),
        directions=frozenset({"short"}),
        style=DAY_TRADE,
        min_rr=1.8,
    ),
    PlaybookEntry(
        name="Range Low Rejection",
        description="Rejeição no piso de um range estabelecido, a favor de reversão/acumulação.",
        compatible_regimes=frozenset({RANGE, ACCUMULATION}),
        directions=frozenset({"long"}),
        style=DAY_TRADE,
        min_rr=1.8,
    ),
]


def compatible_playbooks(regime: str, direction: str, style: str | None = None) -> list[PlaybookEntry]:
    """
    Filtro regime-first (Documento Master, seção 11: "não usar todas as
    estratégias ao mesmo tempo"). Retorna lista vazia quando nenhuma
    estratégia do Playbook é compatível -- isso é o sinal correto para
    o Discovery Engine pular o ativo, não forçar um match.
    """
    results = [
        entry
        for entry in PLAYBOOK
        if regime in entry.compatible_regimes and direction in entry.directions
    ]
    if style is not None:
        results = [entry for entry in results if entry.style == style]
    return results
