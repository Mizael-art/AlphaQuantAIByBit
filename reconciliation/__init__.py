"""
reconciliation
==============

Dois motores de consenso, ambos consultando exchanges em PARALELO
(nunca em fallback/cascata -- isso é o `ProviderRouter`, a EXECUTION
VIEW):

    CrossExchangeReconciliationEngine -- consenso de PREÇO/CANDLE
        bruto (mediana, spread, wick isolado). MARKET VIEW.

    StructureConsensusEngine -- roda Structure/SMC independentemente
        por exchange e compara BOS/CHOCH/HH-HL-LH-LL, liquidity
        sweeps, FVGs e Order Blocks. STRUCTURE VIEW (Documento 4,
        seções 5-9 e 15-17).

`NoExchangeAvailableError` é compartilhada pelos dois -- é o mesmo
tipo de falha ("nenhuma fonte respondeu") nos dois motores.
"""

from reconciliation.cross_exchange import (
    ConsensusResult,
    CrossExchangeReconciliationEngine,
    ExchangeView,
    NoExchangeAvailableError,
)
from reconciliation.structure_consensus import (
    BooleanConsensus,
    ExchangeStructureView,
    StructureConsensusEngine,
    StructureConsensusResult,
)

__all__ = [
    "CrossExchangeReconciliationEngine",
    "ConsensusResult",
    "ExchangeView",
    "NoExchangeAvailableError",
    "StructureConsensusEngine",
    "StructureConsensusResult",
    "ExchangeStructureView",
    "BooleanConsensus",
]
