"""
risk/capital_allocation.py
=============================

Capital Allocation (Documento 2, seção 22; Documento Master, seção 22).

Classifica PRIORIDADE relativa (CORE/NORMAL/REDUCED/WATCH_ONLY), nunca
altera o risco automaticamente por conta própria -- "não necessariamente
alterar o risco automaticamente" é texto literal do documento. A
decisão de quanto risco de fato usar continua com `risk/engine.py`
(que aplica os limites duros); isto aqui é só rótulo de prioridade
relativa entre oportunidades já aprovadas.
"""

from __future__ import annotations

from typing import Final

CORE: Final = "CORE"
NORMAL: Final = "NORMAL"
REDUCED: Final = "REDUCED"
WATCH_ONLY: Final = "WATCH_ONLY"


def classify_capital_priority(overall_score: float, correlated_with: str | None, rr: float | None) -> str:
    """
    Args:
        overall_score: Overall Opportunity Score (0-100, `scoring.engine`).
        correlated_with: símbolo de score maior com quem esta
            oportunidade está correlacionada (`discovery.correlation`),
            ou `None` se não é redundante com nada de rank melhor.
        rr: risco:retorno estimado do trade.

    Returns:
        CORE: score alto, sem redundância de correlação, RR bom --
            candidata a receber a maior fatia relativa de atenção/risco
            dentro dos limites do Risk Engine.
        NORMAL: score razoável, sem problema estrutural evidente.
        REDUCED: correlacionada com algo melhor, ou RR fraco -- ainda
            operável, mas com prioridade menor.
        WATCH_ONLY: score baixo demais para tratar como candidata a
            execução agora -- só acompanhar.
    """
    if overall_score < 50:
        return WATCH_ONLY
    if correlated_with is not None:
        return REDUCED
    if rr is not None and rr < 1.5:
        return REDUCED
    if overall_score >= 80 and (rr is None or rr >= 2.5):
        return CORE
    return NORMAL
