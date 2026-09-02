"""
risk/ruin.py
==============

Risk of Ruin (Documento 2, seção 21; Documento Master, seção 32).

Fórmula usada -- aproximação clássica de "risk of ruin" para apostas
de fração fixa do capital, com trades independentes e distribuição
binária simplificada (ganha `payoff_ratio`×R ou perde 1×R):

    edge = win_rate * payoff_ratio - (1 - win_rate)
    risk_of_ruin ≈ ((1 - edge) / (1 + edge)) ** units_to_ruin

onde `units_to_ruin = 1 / risk_per_trade_fraction` (quantas unidades de
risco cabem no capital).

LIMITAÇÃO declarada: isso é uma aproximação amplamente usada na
literatura de risk management de trading (ex.: tabelas de Ryan
Jones/Van Tharp), não uma simulação Monte Carlo exata -- assume
trades i.i.d. (sem sequências de correlação entre resultados), edge
constante ao longo do tempo, e não modela custos/slippage. Serve para
comparar cenários (esse risco por trade é alto ou baixo demais dado o
edge conhecido?), não como probabilidade garantida. Quando `edge <= 0`,
o risco de ruína tende a 100% (sem edge positivo, fração fixa não salva
o capital no longo prazo) -- reportado explicitamente, não escondido.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskOfRuinResult:
    edge: float
    risk_of_ruin_pct: float
    assumptions_note: str

    def to_dict(self) -> dict:
        return {
            "edge": round(self.edge, 4),
            "risk_of_ruin_pct": round(self.risk_of_ruin_pct, 2),
            "assumptions_note": self.assumptions_note,
        }


_ASSUMPTIONS_NOTE = (
    "Aproximação analítica (trades independentes, edge constante, sem custos/slippage) -- "
    "não é uma simulação Monte Carlo nem uma garantia estatística."
)


def estimate_risk_of_ruin(win_rate_pct: float, payoff_ratio: float, risk_per_trade_pct: float) -> RiskOfRuinResult:
    """
    Args:
        win_rate_pct: taxa de acerto histórica (0-100).
        payoff_ratio: ganho médio / perda média (ex.: 2.0 = ganha em
            média 2R quando acerta).
        risk_per_trade_pct: risco por trade como % do capital (ex.: 1.0 = 1%).

    Returns:
        `RiskOfRuinResult` com o edge calculado e o risco de ruína
        estimado (0-100%).

    Raises:
        ValueError: `risk_per_trade_pct` <= 0 (não há como estimar
            "unidades até a ruína" sem um risco por trade positivo).
    """
    if risk_per_trade_pct <= 0:
        raise ValueError("risk_per_trade_pct precisa ser positivo para estimar risk of ruin.")

    win_rate = win_rate_pct / 100
    edge = win_rate * payoff_ratio - (1 - win_rate)

    if edge <= 0:
        return RiskOfRuinResult(edge=edge, risk_of_ruin_pct=100.0, assumptions_note=_ASSUMPTIONS_NOTE)

    units_to_ruin = 100.0 / risk_per_trade_pct
    ratio = (1 - edge) / (1 + edge)
    risk_of_ruin = (ratio**units_to_ruin) * 100

    return RiskOfRuinResult(edge=edge, risk_of_ruin_pct=min(100.0, risk_of_ruin), assumptions_note=_ASSUMPTIONS_NOTE)
