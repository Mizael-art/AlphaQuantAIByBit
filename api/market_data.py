"""
api/market_data.py
====================

Camada de alto nível de Market Data. A partir desta refatoração, NÃO
fala mais diretamente com a Binance — delega ao `ProviderRouter`
(`providers/router.py`), que escolhe o provider certo por asset class
(Bybit primário, Binance fallback para cripto; Bybit TradFi para
XAUUSD/NAS100/etc.) e aplica o Data Quality Layer antes de devolver
qualquer candle.

A interface pública (`get_candles`, `get_ohlcv_dataframe`,
`get_current_price`, `get_order_book`) foi mantida IDÊNTICA à versão
anterior de propósito — `app.py`, `snapshot/market_snapshot.py` e
`scanner/screener.py` continuam funcionando sem alteração.

Diferença de comportamento: antes, um símbolo não suportado pela
Binance levantava `BinanceAPIError` genérico. Agora, se NENHUM
provider elegível conseguir atender, é levantado
`providers.DataUnavailableError` — explícito, com a lista de
providers tentados — em vez de mascarar como erro de rede da Binance.
"""

from __future__ import annotations

import pandas as pd

from api.binance_client import BinanceAPIError, BinanceClient
from config import DEFAULT_KLINES_LIMIT, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME
from models.candle import Candle
from providers import DataUnavailableError, MarketDataResult, ProviderRouter, build_default_router
from symbols.mapper import SymbolMapper


class MarketData:
    """
    Orquestra a busca e a conversão de dados de mercado, através do
    ProviderRouter multi-source.

    Exemplo de uso (idêntico a antes — só o que acontece por baixo mudou):
        market_data = MarketData()
        df = market_data.get_ohlcv_dataframe("ETHUSDT", "4H")
        price = market_data.get_current_price("ETHUSDT")

        df = market_data.get_ohlcv_dataframe("XAUUSD", "5m")   # agora funciona
        price = market_data.get_current_price("NAS100")        # agora funciona
    """

    def __init__(self, router: ProviderRouter | None = None) -> None:
        # Permite injeção de dependência (útil em testes, com um router mockado).
        self._router = router or build_default_router()
        # Cliente Binance dedicado só para o order book (ver get_order_book):
        # depth/profundidade de book não faz parte da interface
        # MarketDataProvider (é um recurso cripto-específico, não
        # normalizável entre Bybit/Binance/TradFi de forma genérica).
        self._depth_client = BinanceClient()
        # Guarda o resultado normalizado da última busca de candles bem-sucedida,
        # usado por quem quiser o metadado de proveniência (`data_source`)
        # sem repetir a chamada.
        self.last_result: MarketDataResult | None = None

    # ------------------------------------------------------------------
    # CANDLES
    # ------------------------------------------------------------------
    def get_candles(
        self,
        symbol: str = DEFAULT_SYMBOL,
        timeframe: str = DEFAULT_TIMEFRAME,
        limit: int = DEFAULT_KLINES_LIMIT,
    ) -> list[Candle]:
        """
        Busca candles através do ProviderRouter e já os devolve como
        objetos `Candle` normalizados (agnósticos de provider).

        Raises:
            DataUnavailableError: nenhum provider elegível conseguiu
                fornecer dados válidos para este símbolo/timeframe.
        """
        # fetch_quote=False: ninguém consome `MarketDataResult.quote` neste
        # caminho (ver docstring de `ProviderRouter.get_market_data`) --
        # pular essa chamada corta uma requisição HTTP inteira por
        # símbolo/timeframe, sem mudar nenhum dado retornado aqui. Quem
        # precisa do preço atual chama `get_current_price`, que continua
        # buscando o ticker normalmente.
        result = self._router.get_market_data(
            symbol=symbol, timeframe=timeframe, limit=limit, fetch_quote=False
        )
        self.last_result = result
        return result.candles

    def get_ohlcv_dataframe(
        self,
        symbol: str = DEFAULT_SYMBOL,
        timeframe: str = DEFAULT_TIMEFRAME,
        limit: int = DEFAULT_KLINES_LIMIT,
    ) -> pd.DataFrame:
        """
        Busca candles e retorna um `pandas.DataFrame` OHLCV pronto para
        cálculo de indicadores.

        Colunas: open_time, open, high, low, close, volume, close_time,
        quote_volume, trades, taker_buy_volume. Índice: open_time (datetime, UTC).

        Nota: `quote_volume`, `trades` e `taker_buy_volume` podem vir
        `None` quando o provider usado não expõe esses campos (ex.:
        Bybit) — nunca são preenchidos com um valor estimado. Módulos
        que dependem deles (ex.: `order_flow.delta`) devem checar
        disponibilidade antes de calcular.
        """
        candles = self.get_candles(symbol=symbol, timeframe=timeframe, limit=limit)

        if not candles:
            return pd.DataFrame(
                columns=[
                    "open_time", "open", "high", "low", "close",
                    "volume", "close_time", "quote_volume", "trades",
                    "taker_buy_volume",
                ]
            ).set_index("open_time")

        df = pd.DataFrame([candle.to_dict() for candle in candles])
        df["open_time"] = pd.to_datetime(df["open_time"])
        df["close_time"] = pd.to_datetime(df["close_time"])
        df = df.set_index("open_time").sort_index()
        return df

    # ------------------------------------------------------------------
    # PREÇO ATUAL
    # ------------------------------------------------------------------
    def get_current_price(self, symbol: str = DEFAULT_SYMBOL) -> float:
        """
        Retorna o último preço negociado para o símbolo, via o mesmo
        ProviderRouter (chamada leve — não busca/valida candles de novo).
        """
        quote = self._router.get_quote(symbol)
        return quote.last_price

    # ------------------------------------------------------------------
    # ORDER BOOK
    # ------------------------------------------------------------------
    def get_order_book(self, symbol: str = DEFAULT_SYMBOL, limit: int = 100) -> dict:
        """
        Retorna o order book bruto (bids/asks) para o símbolo.

        Disponível hoje apenas para cripto via Binance (mantido como
        estava). Para TradFi, não há provider de order book validado
        ainda — levanta `DataUnavailableError` de forma explícita em
        vez de tentar mascarar.
        """
        canonical = SymbolMapper().resolve(symbol)
        if canonical.asset_class.value != "crypto":
            raise DataUnavailableError(
                symbol=canonical.canonical_symbol,
                timeframe="order_book",
                tried=[],
                reason="Order book só implementado para cripto (Binance) nesta versão.",
            )
        try:
            return self._depth_client.get_depth(symbol=canonical.canonical_symbol, limit=limit)
        except BinanceAPIError as exc:
            raise DataUnavailableError(
                symbol=canonical.canonical_symbol,
                timeframe="order_book",
                tried=["binance"],
                reason=str(exc),
            ) from exc

    def close(self) -> None:
        """Encerra as sessões HTTP subjacentes (router + client de depth)."""
        self._router.close()
        self._depth_client.close()

    def __enter__(self) -> "MarketData":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()
