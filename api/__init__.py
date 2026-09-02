"""
api
===

Pacote responsável pela comunicação com providers de Market Data.

Este pacote expõe apenas `BinanceClient` no nível do pacote — o
cliente de baixo nível continua útil isoladamente (ex.: como
dependência de `providers.binance_provider` e para o order book, que
ainda é cripto-only). `MarketData` (a fachada de alto nível) deve ser
importada diretamente de `api.market_data`, não daqui: importá-la
neste `__init__.py` causaria um import circular, porque
`api.market_data` depende de `providers`, e `providers.binance_provider`
depende de `api.binance_client` (que precisa deste pacote `api` já
inicializado).
"""

from api.binance_client import BinanceClient

__all__ = [
    "BinanceClient",
]

