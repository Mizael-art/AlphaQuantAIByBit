"""
learning
========

Learning Engine (Fase 5 do Plano de Evolução -- Documento 2, seções
27-33; Documento Master, seções 27-33).

- `schema.py` -- entrada de sinal externo.
- `classification.py` -- VALID_SIGNAL/WEAK_SIGNAL/LUCKY_WIN/etc (puro,
  testado).
- `reconstruction.py` -- Call Reverse Engineering: reconstrói o
  contexto de mercado no momento do sinal (rede real, smoke-tested).
- `repository.py` -- I/O de `SignalRecord`.
- `hypotheses.py` -- agregação estatística por estratégia/ativo (puro,
  testado), nunca declara VALIDATED com amostra < 30.
"""

from learning.classification import (
    BAD_TRADE_GOOD_RESULT,
    GOOD_TRADE_BAD_RESULT,
    LUCKY_WIN,
    PENDING_RESULT,
    VALID_SIGNAL,
    WEAK_SIGNAL,
    classify_signal,
    compute_quality_score,
)
from learning.hypotheses import IN_TEST, OBSERVATION, REJECTED, VALIDATED, Hypothesis, build_hypotheses
from learning.reconstruction import ReconstructedContext, reconstruct_context
from learning.schema import ExternalSignalInput, SignalResultUpdate

__all__ = [
    "ExternalSignalInput", "SignalResultUpdate",
    "classify_signal", "compute_quality_score",
    "VALID_SIGNAL", "WEAK_SIGNAL", "LUCKY_WIN", "BAD_TRADE_GOOD_RESULT", "GOOD_TRADE_BAD_RESULT", "PENDING_RESULT",
    "reconstruct_context", "ReconstructedContext",
    "build_hypotheses", "Hypothesis", "OBSERVATION", "IN_TEST", "VALIDATED", "REJECTED",
]
