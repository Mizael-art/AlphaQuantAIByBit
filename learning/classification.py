"""
learning/classification.py
=============================

Classificação de sinais externos (Documento 2, seção 27; Documento
Master, seção 33). O documento nomeia 5 categorias mas não dá o
algoritmo -- o mapeamento abaixo é uma interpretação explícita e
documentada, não uma transcrição literal:

    quality_score >= 60  => processo "bom" (estrutura/regime/RR consistentes)
    quality_score < 35   => processo "ruim"
    entre os dois        => processo "mediano"

    resultado WIN  + processo bom     -> VALID_SIGNAL
    resultado WIN  + processo mediano -> BAD_TRADE_GOOD_RESULT (ganhou apesar do processo duvidoso)
    resultado WIN  + processo ruim    -> LUCKY_WIN (ganhou apesar de um processo claramente ruim)
    resultado LOSS + processo bom     -> GOOD_TRADE_BAD_RESULT (perdeu apesar de bom processo)
    resultado LOSS + processo mediano/ruim -> WEAK_SIGNAL (perdeu e o processo já não sustentava confiança)
    resultado BREAKEVEN                -> VALID_SIGNAL se processo bom, senão WEAK_SIGNAL
    sem resultado ainda                -> PENDING_RESULT (não classificável -- nunca inventa um resultado)

`quality_score` é calculado reaproveitando `scoring.engine` (média de
`quality` e `confirmation`) sobre o contexto reconstruído -- não
duplica a lógica de scoring.
"""

from __future__ import annotations

from typing import Final

from scoring.engine import compute_opportunity_score

VALID_SIGNAL: Final = "VALID_SIGNAL"
WEAK_SIGNAL: Final = "WEAK_SIGNAL"
LUCKY_WIN: Final = "LUCKY_WIN"
BAD_TRADE_GOOD_RESULT: Final = "BAD_TRADE_GOOD_RESULT"
GOOD_TRADE_BAD_RESULT: Final = "GOOD_TRADE_BAD_RESULT"
PENDING_RESULT: Final = "PENDING_RESULT"

_GOOD_THRESHOLD = 60.0
_BAD_THRESHOLD = 35.0


def compute_quality_score(trend: str, bos: bool, choch: bool, regime_compatible: bool, rr: float | None) -> float:
    """Reaproveita `scoring.engine` -- média de quality/confirmation, sem contexto BTC (sinais externos não têm isso reconstruído nesta fase)."""
    score = compute_opportunity_score(
        trend=trend, bos=bos, choch=choch, regime_compatible=regime_compatible, rr=rr,
        distance_to_zone_pct=None, volatility_bucket="NORMAL", btc_context=None,
        correlation_penalty=False, playbook_stats=None,
    )
    return (score.quality + score.confirmation) / 2


def classify_signal(quality_score: float, result: str | None) -> str:
    """
    Args:
        quality_score: 0-100 (`compute_quality_score`).
        result: "win" | "loss" | "breakeven" | None.
    """
    if result is None:
        return PENDING_RESULT

    is_good = quality_score >= _GOOD_THRESHOLD
    is_bad = quality_score < _BAD_THRESHOLD

    if result == "win":
        if is_good:
            return VALID_SIGNAL
        if is_bad:
            return LUCKY_WIN
        return BAD_TRADE_GOOD_RESULT

    if result == "loss":
        return GOOD_TRADE_BAD_RESULT if is_good else WEAK_SIGNAL

    # breakeven
    return VALID_SIGNAL if is_good else WEAK_SIGNAL
