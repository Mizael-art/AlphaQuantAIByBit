"""
decision/engine.py
=====================

Decision Eligibility Engine (Documento Master, seções 25, 67-82).
Função pura -- nunca consulta banco ou rede diretamente (mesmo padrão
de `risk/engine.py` e `scoring/engine.py`): recebe o Overall Opportunity
Score já calculado (Fase 3), a decisão do Risk Engine já calculada
(Fase 4), o status do setup e a qualidade de entrada, e devolve UMA
decisão determinística.

Documento Master, seção 73: "autonomia é sobre decisão, o risco
continua subordinado ao Risk Engine" -- por isso o risco é o primeiro
filtro aqui, e um REJECTED do Risk Engine nunca é contornável por um
score alto.

Documento Master, seção 77 ("não ser conservador por padrão"): este
motor não usa WATCH como resposta de segurança -- WATCH só sai quando
os critérios objetivos (abaixo) realmente correspondem a "ainda não é
hora", nunca como forma de evitar dar uma resposta.

Nível de convicção (seção 75) NUNCA é probabilidade de lucro -- é só a
força relativa dos critérios já satisfeitos, e é reportado como tal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

LONG_NOW: Final = "LONG_NOW"
SHORT_NOW: Final = "SHORT_NOW"
WAIT_TRIGGER: Final = "WAIT_TRIGGER"
WAIT_PULLBACK: Final = "WAIT_PULLBACK"
WATCH: Final = "WATCH"
REJECT: Final = "REJECT"

LOW_CONVICTION: Final = "LOW"
MEDIUM_CONVICTION: Final = "MEDIUM"
HIGH_CONVICTION: Final = "HIGH"

#: Status de setup (setups/lifecycle.py) considerados "pronto para entrar agora".
_ENTRY_READY_STATUSES: Final = frozenset({"TRIGGERED", "ENTRY_READY", "READY"})
#: Status ainda não prontos, mas não descartados -- aguardando o mercado.
_WAITING_STATUSES: Final = frozenset({"FORMATION", "WATCH", "NEAR_ENTRY"})

_MIN_SCORE_TO_CONSIDER: Final = 50.0
_MIN_SCORE_FOR_ENTRY_NOW: Final = 65.0


@dataclass(frozen=True, slots=True)
class DecisionEligibilityResult:
    decision: str
    conviction: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"decision": self.decision, "conviction": self.conviction, "reasons": self.reasons}


def _conviction_from_score(overall_score: float) -> str:
    if overall_score >= 80:
        return HIGH_CONVICTION
    if overall_score >= 60:
        return MEDIUM_CONVICTION
    return LOW_CONVICTION


def evaluate_decision(
    *,
    direction: str,
    overall_score: float,
    risk_decision: str,
    setup_status: str,
    entry_quality: str,
) -> DecisionEligibilityResult:
    """
    Args:
        direction: "long" | "short".
        overall_score: Overall Opportunity Score (0-100, `scoring.engine`).
        risk_decision: "APPROVED" | "REDUCED" | "REJECTED" (`risk.engine.evaluate_trade_risk`).
        setup_status: status atual do Setup Lifecycle (`setups.lifecycle`)
            -- ou `"UNKNOWN"` se não há setup persistido ainda (trade
            ad-hoc, avaliado sob demanda).
        entry_quality: "ENTRY_NOW" | "ENTRY_ON_PULLBACK" |
            "ENTRY_ON_CONFIRMATION" | "ENTRY_ON_BREAKOUT" |
            "ENTRY_ON_RETEST" | "NO_ENTRY" (Documento Master, seção 18) --
            reflete se o preço já percorreu demais o movimento
            (chase risk, seção 19) ou está numa zona executável agora.
    """
    if direction not in ("long", "short"):
        raise ValueError("direction deve ser 'long' ou 'short'.")

    reasons: list[str] = []

    # 1) Risco sempre primeiro -- nunca contornável por score alto.
    if risk_decision == "REJECTED":
        reasons.append("Risk Engine rejeitou o trade -- decisão de risco é absoluta, não é contornada por score.")
        return DecisionEligibilityResult(REJECT, LOW_CONVICTION, reasons)

    # 2) Sem edge suficiente -- reject direto, não "watch" por segurança.
    if overall_score < _MIN_SCORE_TO_CONSIDER:
        reasons.append(f"Overall Opportunity Score ({overall_score:.1f}) abaixo do mínimo para considerar ({_MIN_SCORE_TO_CONSIDER}).")
        return DecisionEligibilityResult(REJECT, LOW_CONVICTION, reasons)

    conviction = _conviction_from_score(overall_score)

    # 3) Chase risk -- setup ainda bom, mas entrada perseguindo preço.
    if entry_quality == "NO_ENTRY":
        reasons.append("Entrada não executável no momento (chase risk ou ausência de zona clara) -- aguardar pullback.")
        return DecisionEligibilityResult(WAIT_PULLBACK, conviction, reasons)

    # 4) Setup ainda não chegou na zona/gatilho.
    if setup_status in _WAITING_STATUSES:
        reasons.append(f"Setup em '{setup_status}' -- ainda aguardando o gatilho definido.")
        return DecisionEligibilityResult(WAIT_TRIGGER, conviction, reasons)

    # 5) Pronto e com score alto o suficiente -- decisão explícita
    #    (Documento Master, seção 76: "não transformar um trade pronto
    #    em 'continue observando'").
    ready = setup_status in _ENTRY_READY_STATUSES or setup_status == "UNKNOWN"
    if ready and entry_quality == "ENTRY_NOW" and overall_score >= _MIN_SCORE_FOR_ENTRY_NOW:
        reasons.append(f"Critérios satisfeitos: risco {risk_decision.lower()}, score {overall_score:.1f}, entrada executável agora.")
        if risk_decision == "REDUCED":
            reasons.append("Risco foi reduzido pelo Risk Engine -- aprovado com tamanho menor que o solicitado.")
        return DecisionEligibilityResult(LONG_NOW if direction == "long" else SHORT_NOW, conviction, reasons)

    # 6) Pronto mas esperando confirmação/retest/breakout específico.
    if entry_quality in ("ENTRY_ON_CONFIRMATION", "ENTRY_ON_BREAKOUT", "ENTRY_ON_RETEST"):
        reasons.append(f"Aguardando confirmação específica antes de entrar ({entry_quality}).")
        return DecisionEligibilityResult(WAIT_TRIGGER, conviction, reasons)

    if entry_quality == "ENTRY_ON_PULLBACK":
        reasons.append("Estratégia pede entrada em pullback -- ainda não recuou o suficiente.")
        return DecisionEligibilityResult(WAIT_PULLBACK, conviction, reasons)

    # 7) Nenhum dos gatilhos de decisão explícita bateu -- observar,
    #    não por segurança, mas porque nenhum critério de entrada foi
    #    satisfeito ainda.
    reasons.append("Nenhum critério de entrada imediata satisfeito ainda -- acompanhar.")
    return DecisionEligibilityResult(WATCH, conviction, reasons)
