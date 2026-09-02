"""
fundamentals
============

Os 4 motores pedidos no Documento 4, seção 19 -- interfaces abstratas
para dados que NENHUMA exchange fornece (macro, calendário de eventos,
unlocks de tokens, fundamentos do ativo), cada uma com uma
implementação de referência gratuita e um fallback explícito
("Null...Provider") para quando nenhum vendor está configurado.

Nenhum destes motores está conectado ao `snapshot/` ainda -- são
interfaces prontas para os motores superiores (Evidence & Scoring,
Decision Intelligence) consumirem quando a integração for priorizada
(Documento 4, Fase 4). Trocar a implementação de referência por um
vendor pago no futuro não deve exigir nenhuma mudança nos motores
superiores -- só a instanciação do provider muda.

    MacroDataProvider          -- fundamentals/macro.py
    EconomicEventsProvider     -- fundamentals/events.py
    TokenUnlockProvider        -- fundamentals/unlocks.py
    CryptoFundamentalsProvider -- fundamentals/crypto_fundamentals.py
"""

from fundamentals.base import FundamentalsDataProvider, FundamentalsUnavailableError
from fundamentals.crypto_fundamentals import (
    CoinGeckoFundamentalsProvider,
    CryptoFundamentals,
    CryptoFundamentalsProvider,
    NullCryptoFundamentalsProvider,
)
from fundamentals.events import (
    EconomicEvent,
    EconomicEventsProvider,
    NullEconomicEventsProvider,
    StaticCuratedEventsProvider,
)
from fundamentals.macro import FredMacroProvider, MacroDataPoint, MacroDataProvider, NullMacroProvider
from fundamentals.unlocks import (
    DefiLlamaUnlockProvider,
    NullTokenUnlockProvider,
    TokenUnlockEvent,
    TokenUnlockProvider,
)

__all__ = [
    "FundamentalsDataProvider",
    "FundamentalsUnavailableError",
    # Motor 1
    "MacroDataProvider",
    "MacroDataPoint",
    "FredMacroProvider",
    "NullMacroProvider",
    # Motor 2
    "EconomicEventsProvider",
    "EconomicEvent",
    "StaticCuratedEventsProvider",
    "NullEconomicEventsProvider",
    # Motor 3
    "TokenUnlockProvider",
    "TokenUnlockEvent",
    "DefiLlamaUnlockProvider",
    "NullTokenUnlockProvider",
    # Motor 4
    "CryptoFundamentalsProvider",
    "CryptoFundamentals",
    "CoinGeckoFundamentalsProvider",
    "NullCryptoFundamentalsProvider",
]
