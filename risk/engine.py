"""
risk/engine.py
=================

Núcleo do Risk Engine (Documento 2, seção 21; Documento Master, seções
21, 56). Função pura: recebe o estado atual da conta (já consultado no
banco por `risk/repository.py`) + os limites configurados + o trade
proposto, e devolve uma decisão -- nunca consulta o banco diretamente
(mesmo padrão de `scoring/engine.py` e `regime/detector.py`: lógica de
decisão separada de I/O, fácil de testar sem depender de persistência).

Documento Master, seção 73: "autonomia é sobre decisão, risco continua
subordinado ao Risk Engine" -- isto é o que aplica essa regra. Nenhuma
outra camada do sistema (Discovery Engine, scoring, futuro Decision
Eligibility da Fase 6) tem permissão para contornar estes limites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

APPROVED: Final = "APPROVED"
REDUCED: Final = "REDUCED"
REJECTED: Final = "REJECTED"

Decision = Literal["APPROVED", "REDUCED", "REJECTED"]


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_risk_per_trade_pct: float
    daily_loss_limit_pct: float
    weekly_loss_limit_pct: float
    monthly_drawdown_limit_pct: float
    max_open_risk_pct: float


@dataclass(frozen=True, slots=True)
class AccountRiskState:
    current_capital: float
    realized_pnl_today_pct: float
    realized_pnl_week_pct: float
    realized_pnl_month_pct: float
    open_risk_pct: float
    #: True se já existe posição aberta no mesmo `correlation_group` do trade proposto.
    correlated_open_position_exists: bool = False


@dataclass(frozen=True, slots=True)
class ProposedTrade:
    asset: str
    direction: str
    requested_risk_pct: float
    correlation_group: str | None = None


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision: Decision
    approved_risk_pct: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"decision": self.decision, "approved_risk_pct": round(self.approved_risk_pct, 3), "reasons": self.reasons}


def evaluate_trade_risk(trade: ProposedTrade, state: AccountRiskState, limits: RiskLimits) -> RiskDecision:
    """
    Aplica os limites em ordem -- qualquer limite duro violado rejeita
    o trade inteiro (nunca "quase aprova"); a única redução parcial
    aceita é o teto de risco por trade e o espaço restante de open
    risk, nunca os limites de perda realizada (esses são STOP, não
    "reduza um pouco e continue").
    """
    reasons: list[str] = []

    # --- Limites de perda realizada (STOP -- nunca reduzido, só rejeitado) ---
    if state.realized_pnl_today_pct <= -abs(limits.daily_loss_limit_pct):
        reasons.append(
            f"Limite de perda diária atingido ({state.realized_pnl_today_pct:.2f}% <= "
            f"-{limits.daily_loss_limit_pct:.2f}%) -- nenhuma operação nova hoje."
        )
        return RiskDecision(REJECTED, 0.0, reasons)

    if state.realized_pnl_week_pct <= -abs(limits.weekly_loss_limit_pct):
        reasons.append(
            f"Limite de perda semanal atingido ({state.realized_pnl_week_pct:.2f}% <= "
            f"-{limits.weekly_loss_limit_pct:.2f}%) -- nenhuma operação nova esta semana."
        )
        return RiskDecision(REJECTED, 0.0, reasons)

    if state.realized_pnl_month_pct <= -abs(limits.monthly_drawdown_limit_pct):
        reasons.append(
            f"Drawdown mensal atingido ({state.realized_pnl_month_pct:.2f}% <= "
            f"-{limits.monthly_drawdown_limit_pct:.2f}%) -- nenhuma operação nova este mês."
        )
        return RiskDecision(REJECTED, 0.0, reasons)

    # --- Correlação: já existe posição aberta no mesmo cluster ---
    if state.correlated_open_position_exists:
        reasons.append(
            f"Já existe posição aberta correlacionada com {trade.asset} -- "
            "Documento Master seção 15: tratar como a mesma aposta, não abrir uma segunda."
        )
        return RiskDecision(REJECTED, 0.0, reasons)

    # --- Risco por trade: nunca acima do teto configurado ---
    risk_pct = min(trade.requested_risk_pct, limits.max_risk_per_trade_pct)
    if risk_pct < trade.requested_risk_pct:
        reasons.append(
            f"Risco solicitado ({trade.requested_risk_pct:.2f}%) acima do teto por trade "
            f"({limits.max_risk_per_trade_pct:.2f}%) -- reduzido."
        )

    # --- Open risk: espaço restante até o teto agregado ---
    remaining_open_risk = limits.max_open_risk_pct - state.open_risk_pct
    if remaining_open_risk <= 0:
        reasons.append(
            f"Open risk já no teto ({state.open_risk_pct:.2f}% >= {limits.max_open_risk_pct:.2f}%) -- "
            "sem espaço para uma nova posição."
        )
        return RiskDecision(REJECTED, 0.0, reasons)

    if risk_pct > remaining_open_risk:
        reasons.append(
            f"Risco reduzido de {risk_pct:.2f}% para {remaining_open_risk:.2f}% -- espaço restante "
            f"de open risk (teto {limits.max_open_risk_pct:.2f}%, já comprometido {state.open_risk_pct:.2f}%)."
        )
        risk_pct = remaining_open_risk

    decision = REDUCED if risk_pct < trade.requested_risk_pct else APPROVED
    if decision == APPROVED:
        reasons.append("Dentro de todos os limites configurados.")

    return RiskDecision(decision, risk_pct, reasons)
