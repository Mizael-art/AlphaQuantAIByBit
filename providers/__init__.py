"""
providers
=========

Market Data Layer multi-provider.

Expõe:
    MarketDataProvider   -- interface comum
    Quote                -- preço atual normalizado
    MarketDataError       -- erro de um provider individual
    DataUnavailableError -- nenhum provider elegível conseguiu atender
    ProviderRouter        -- decide qual provider usar por asset class,
                             com fallback
    build_default_router  -- factory com o registro padrão de providers
                             (Bybit primário para cripto e TradFi
                             experimental, Binance como fallback cripto)
    build_reconciliation_providers -- factory com as exchanges usadas
                             pelo CrossExchangeReconciliationEngine e
                             pelo StructureConsensusEngine (consulta
                             em PARALELO, não em fallback -- ver
                             docstring de `providers.router`)

CRITICAL: `build_default_router` (EXECUTION VIEW / fallback) e
`build_reconciliation_providers` (MARKET VIEW / STRUCTURE VIEW,
consenso) são duas listas DELIBERADAMENTE separadas, mesmo que hoje
se sobreponham parcialmente. OKX e Bitget entram como fontes de
CONSENSO -- não entram no fallback de execução do ProviderRouter sem
uma decisão explícita nesse sentido (mudaria qual exchange o sistema
usa pra decidir "onde operar", que é uma decisão de produto, não uma
consequência automática de "agora temos mais exchanges").
"""

from providers.base import DataUnavailableError, MarketDataError, MarketDataProvider, Quote
from providers.binance_provider import BinanceProvider
from providers.bitget_provider import BitgetProvider
from providers.bybit_provider import BybitCryptoProvider, BybitTradFiProvider
from providers.okx_provider import OKXProvider
from providers.router import MarketDataResult, ProviderRouter


def build_default_router() -> ProviderRouter:
    """
    Monta o `ProviderRouter` padrão do AlphaQuant Engine:

        CRYPTO           -> Bybit (primário) -> Binance (fallback)
        FOREX/METAL/INDEX -> Bybit TradFi (experimental)

    Usado por `api/market_data.py`. Instâncias de teste devem construir
    seu próprio `ProviderRouter` com providers mockados, em vez de usar
    esta factory.
    """
    return ProviderRouter(
        providers=[
            BybitCryptoProvider(),
            BinanceProvider(),
            BybitTradFiProvider(),
        ]
    )


def build_reconciliation_providers() -> list[MarketDataProvider]:
    """
    Monta a lista de exchanges cripto usada pelo
    `CrossExchangeReconciliationEngine` e pelo `StructureConsensusEngine`
    (Documento 4, Fase 1/2): Binance, Bybit, OKX, Bitget -- consultadas
    em paralelo, sem ordem de prioridade (não é fallback).

    Cada instância abre sua própria sessão HTTP; quem chamar esta
    factory é responsável por fechar as sessões (`provider.close()`)
    quando a lista não for mais usada -- os engines de reconciliação já
    fazem isso no próprio `close()`.
    """
    return [
        BinanceProvider(),
        BybitCryptoProvider(),
        OKXProvider(),
        BitgetProvider(),
    ]


__all__ = [
    "DataUnavailableError",
    "MarketDataError",
    "MarketDataProvider",
    "Quote",
    "ProviderRouter",
    "MarketDataResult",
    "BinanceProvider",
    "BybitCryptoProvider",
    "BybitTradFiProvider",
    "OKXProvider",
    "BitgetProvider",
    "build_default_router",
    "build_reconciliation_providers",
]
