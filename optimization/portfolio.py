"""
optimization/portfolio.py
============================

Portfolio Intelligence (Documento Master, seção 38: "BEST COMBINATION
OF TRADES"). Função pura -- seleção gulosa (greedy) por score
decrescente, respeitando teto de risco agregado e evitando
correlação redundante. Não reimplementa o Correlated Exposure Engine
(Fase 3, `discovery.correlation`) -- consome sua saída.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PortfolioSelection:
    selected: list[str]
    skipped: dict[str, str]  # symbol -> motivo
    total_risk_pct: float

    def to_dict(self) -> dict:
        return {"selected": self.selected, "skipped": self.skipped, "total_risk_pct": round(self.total_risk_pct, 3)}


def select_best_combination(
    opportunities: list[dict],
    max_open_risk_pct: float,
    risk_pct_per_trade: float,
    max_positions: int | None = None,
    correlation_flags: dict[str, str | None] | None = None,
) -> PortfolioSelection:
    """
    Args:
        opportunities: cada dict precisa ter `symbol` e
            `overall_opportunity_score` (mesmo shape de
            `scoring.engine.OpportunityScore.to_dict()` + `symbol`) --
            já ordenável, mas esta função ordena de novo por garantia.
        max_open_risk_pct: teto agregado de risco (Documento 2, seção 21).
        risk_pct_per_trade: risco fixo assumido por posição (a
            granularidade de "quanto risco cada uma pede" fica com o
            Risk Engine -- aqui é uma seleção de portfólio, não um
            position sizer).
        max_positions: limite adicional de número de posições (`None` = sem limite além do risco).
        correlation_flags: saída de `discovery.correlation.flag_correlated_duplicates`
            (symbol -> symbol de rank melhor com quem está correlacionado,
            ou `None` se não há duplicata) -- se não fornecido, a seleção
            ignora correlação (assume tudo independente).

    Returns:
        `PortfolioSelection` com os símbolos escolhidos, os pulados
        (com motivo -- correlação ou orçamento de risco esgotado) e o
        risco total comprometido pela seleção.
    """
    ranked = sorted(opportunities, key=lambda o: o["overall_opportunity_score"], reverse=True)
    correlation_flags = correlation_flags or {}

    selected: list[str] = []
    skipped: dict[str, str] = {}
    total_risk_pct = 0.0

    for opp in ranked:
        symbol = opp["symbol"]

        if max_positions is not None and len(selected) >= max_positions:
            skipped[symbol] = f"Limite de {max_positions} posições já atingido."
            continue

        correlated_with = correlation_flags.get(symbol)
        if correlated_with is not None and correlated_with in selected:
            skipped[symbol] = f"Correlacionado com {correlated_with}, já selecionado (mesma aposta)."
            continue

        if total_risk_pct + risk_pct_per_trade > max_open_risk_pct:
            skipped[symbol] = (
                f"Adicionar {risk_pct_per_trade:.2f}% excederia o teto de open risk "
                f"({total_risk_pct:.2f}% + {risk_pct_per_trade:.2f}% > {max_open_risk_pct:.2f}%)."
            )
            continue

        selected.append(symbol)
        total_risk_pct += risk_pct_per_trade

    return PortfolioSelection(selected=selected, skipped=skipped, total_risk_pct=total_risk_pct)
