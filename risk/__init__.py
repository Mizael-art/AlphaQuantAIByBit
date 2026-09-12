"""
risk
====

Risk Engine central (Fase 4 do Plano de Evolução -- Documento 2, seção
21; Documento Master, seções 21, 32, 56, 73). Correlated Exposure já
foi construído na Fase 3 (`discovery/correlation.py`); esta fase
adiciona os limites por trade/dia/semana/mês, open risk, risk of ruin
e capital allocation.

`engine.py` (decisão, pura) e `repository.py` (I/O sobre a Session)
são deliberadamente separados -- mesmo padrão de `scoring/engine.py`.
"""

from risk.capital_allocation import CORE, NORMAL, REDUCED as CAPITAL_REDUCED, WATCH_ONLY, classify_capital_priority
from risk.engine import (
    APPROVED,
    REDUCED,
    REJECTED,
    AccountRiskState,
    ProposedTrade,
    RiskDecision,
    RiskLimits,
    evaluate_trade_risk,
)
from risk.ruin import RiskOfRuinResult, estimate_risk_of_ruin

__all__ = [
    "AccountRiskState", "ProposedTrade", "RiskDecision", "RiskLimits", "evaluate_trade_risk",
    "APPROVED", "REDUCED", "REJECTED",
    "estimate_risk_of_ruin", "RiskOfRuinResult",
    "classify_capital_priority", "CORE", "NORMAL", "CAPITAL_REDUCED", "WATCH_ONLY",
]
