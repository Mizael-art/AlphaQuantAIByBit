"""
decision
========

Decision Eligibility Engine (Fase 6 do Plano de Evolução -- Documento
Master, seções 25, 67-82).

- `engine.py` -- decisão determinística pura (LONG_NOW/SHORT_NOW/
  WAIT_TRIGGER/WAIT_PULLBACK/WATCH/REJECT), testada isoladamente.
- `mentor_block.py` -- formata a decisão no formato que o GPT deve
  comunicar verbatim (nunca inventa números).

A integração com dados reais (score + risco + setup) acontece no
endpoint `POST /decision/evaluate` em `server.py`, que orquestra
`scoring.engine`, `risk.engine`/`risk.repository` e este pacote.
"""

from decision.engine import (
    HIGH_CONVICTION,
    LONG_NOW,
    LOW_CONVICTION,
    MEDIUM_CONVICTION,
    REJECT,
    SHORT_NOW,
    WAIT_PULLBACK,
    WAIT_TRIGGER,
    WATCH,
    DecisionEligibilityResult,
    evaluate_decision,
)
from decision.mentor_block import build_mentor_block

__all__ = [
    "evaluate_decision", "DecisionEligibilityResult", "build_mentor_block",
    "LONG_NOW", "SHORT_NOW", "WAIT_TRIGGER", "WAIT_PULLBACK", "WATCH", "REJECT",
    "LOW_CONVICTION", "MEDIUM_CONVICTION", "HIGH_CONVICTION",
]
