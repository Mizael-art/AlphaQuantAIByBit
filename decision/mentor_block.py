"""
decision/mentor_block.py
===========================

Formata `DecisionEligibilityResult` no formato "mentor" (Documento
Master, seções 27, 69): o bloco 🟢/🔴/🟡/🟠/⚪/❌ com os campos que o
GPT deve comunicar verbatim, sem inventar nenhum número (Documento
Master, seção 17: "o GPT não deve inventar esses números quando o
backend puder calculá-los").

LIMITAÇÃO declarada: `recommended_leverage` é uma heurística
conservadora baseada só no bucket de volatilidade (não é um cálculo de
margem/liquidação preciso) -- documentado no próprio campo de saída.
`expected_holding` vem do estilo do Playbook (day_trade/intraday/
swing), não de uma estimativa estatística de duração real de trade
(isso exigiria histórico de trades fechados por estratégia, ainda
não construído).
"""

from __future__ import annotations

from typing import Any, Final

from decision.engine import LONG_NOW, REJECT, SHORT_NOW, WAIT_PULLBACK, WAIT_TRIGGER, WATCH

_EMOJI: Final[dict[str, str]] = {
    LONG_NOW: "🟢",
    SHORT_NOW: "🔴",
    WAIT_TRIGGER: "🟡",
    WAIT_PULLBACK: "🟠",
    WATCH: "⚪",
    REJECT: "❌",
}

_LEVERAGE_BY_VOLATILITY: Final[dict[str, int]] = {"LOW": 5, "NORMAL": 3, "HIGH": 2, "EXTREME": 1}

_HOLDING_BY_STYLE: Final[dict[str, str]] = {
    "day_trade": "minutos a algumas horas",
    "intraday": "horas a 1-2 dias",
    "swing": "dias a semanas",
}


def _recommended_leverage(volatility_bucket: str) -> int:
    return _LEVERAGE_BY_VOLATILITY.get(volatility_bucket, 1)


def build_mentor_block(
    *,
    decision: str,
    conviction: str,
    reasons: list[str],
    asset: str,
    entry_zone: tuple[float, float] | None,
    stop: float | None,
    target: float | None,
    rr: float | None,
    approved_risk_pct: float | None,
    volatility_bucket: str,
    style: str | None,
    invalidation: str | None,
    main_risk: str | None,
) -> dict[str, Any]:
    """
    Returns:
        dict pronto para o GPT relatar -- inclui `emoji`, `headline` e
        todos os campos numéricos que uma decisão LONG_NOW/SHORT_NOW
        exige (Documento Master, seção 68). Para decisões que não são
        entrada imediata, os campos de execução ficam `None`
        explicitamente (nunca omitidos silenciosamente -- quem lê sabe
        que não se aplicam agora, não que foram esquecidos).
    """
    emoji = _EMOJI.get(decision, "⚪")
    is_entry_now = decision in (LONG_NOW, SHORT_NOW)

    headline = {
        LONG_NOW: "ABRIR LONG AGORA",
        SHORT_NOW: "ABRIR SHORT AGORA",
        WAIT_TRIGGER: "AGUARDAR GATILHO",
        WAIT_PULLBACK: "AGUARDAR PULLBACK",
        WATCH: "OBSERVAR",
        REJECT: "NÃO ABRIR",
    }.get(decision, "OBSERVAR")

    return {
        "emoji": emoji,
        "headline": headline,
        "decision": decision,
        "conviction": conviction,
        "asset": asset,
        "entry_zone": {"low": entry_zone[0], "high": entry_zone[1]} if entry_zone else None,
        "stop": stop,
        "target": target,
        "rr": rr,
        "risk_pct": approved_risk_pct if is_entry_now else None,
        "recommended_leverage": _recommended_leverage(volatility_bucket) if is_entry_now else None,
        "recommended_leverage_note": "Heurística conservadora por volatilidade -- não é cálculo de margem/liquidação." if is_entry_now else None,
        "expected_holding": _HOLDING_BY_STYLE.get(style, "não estimado") if style else None,
        "reasons": reasons,
        "main_risk": main_risk,
        "invalidation": invalidation,
        "disclaimer": (
            "Convicção reflete a força dos critérios objetivos satisfeitos, não é "
            "probabilidade de lucro. Backtest/análise histórica não garante resultado futuro."
        ),
    }
