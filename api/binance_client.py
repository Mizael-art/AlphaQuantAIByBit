"""
api/binance_client.py
======================

Cliente HTTP de baixo nível para os endpoints públicos da Binance.

Este módulo NÃO utiliza API Key — todos os endpoints consumidos aqui
são públicos (dados de mercado), conforme especificado na Fase 1 do
projeto:

- GET /api/v3/klines        -> candles OHLCV
- GET /api/v3/ticker/price  -> preço atual (last price)
- GET /api/v3/depth         -> order book (bids/asks)

O cliente é propositalmente "burro": ele apenas faz a requisição,
valida a resposta e devolve os dados brutos (listas/dicionários do
JSON da Binance). Qualquer transformação (DataFrame, dataclasses,
indicadores, etc.) é responsabilidade das camadas superiores
(`api.market_data`, `indicators`, `structure`, `analysis`).
"""

from __future__ import annotations

import time
from typing import Any

import requests

from config import (
    BINANCE_BASE_URL,
    ENDPOINT_DEPTH,
    ENDPOINT_KLINES,
    ENDPOINT_TICKER_PRICE,
    MAX_KLINES_LIMIT,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF_SECONDS,
    TIMEFRAME_MAP,
)


class BinanceAPIError(Exception):
    """Erro genérico levantado quando a Binance retorna uma resposta inválida."""


class BinanceClient:
    """
    Cliente HTTP para os endpoints públicos (Market Data) da Binance.

    Todas as chamadas são feitas via `requests`, com retry simples e
    backoff linear em caso de falha de rede ou erro temporário (5xx).

    Exemplo de uso:
        client = BinanceClient()
        candles = client.get_klines("BTCUSDT", "4H")
        price = client.get_price("BTCUSDT")
        depth = client.get_depth("BTCUSDT")
    """

    def __init__(self, base_url: str = BINANCE_BASE_URL, timeout: int = REQUEST_TIMEOUT) -> None:
        self.base_url = base_url
        self.timeout = timeout
        # Sessão reutilizável: melhora performance (keep-alive) em
        # múltiplas requisições consecutivas.
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # MÉTODO INTERNO DE REQUISIÇÃO (com retry/backoff)
    # ------------------------------------------------------------------
    def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """
        Executa uma requisição GET contra a Binance com retentativas.

        Levanta `BinanceAPIError` caso todas as tentativas falhem ou a
        Binance retorne um payload de erro reconhecível (ex.: {"code": ..., "msg": ...}).
        """
        url = f"{self.base_url}{endpoint}"
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._session.get(url, params=params, timeout=self.timeout)

                # A Binance retorna erros de negócio com status 4xx/5xx
                # e um corpo JSON no formato {"code": -1121, "msg": "..."}.
                if response.status_code != 200:
                    raise BinanceAPIError(
                        f"Binance retornou status {response.status_code} "
                        f"para {endpoint}: {response.text}"
                    )

                data = response.json()

                # Alguns erros vêm com status 200 mas corpo de erro (raro,
                # mas defensivo é melhor do que confiar cegamente).
                if isinstance(data, dict) and "code" in data and "msg" in data:
                    raise BinanceAPIError(
                        f"Erro da Binance em {endpoint}: "
                        f"code={data['code']} msg={data['msg']}"
                    )

                return data

            except (requests.RequestException, BinanceAPIError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

        # Se chegou aqui, todas as tentativas falharam.
        raise BinanceAPIError(
            f"Falha ao consultar {endpoint} após {MAX_RETRIES} tentativas: {last_error}"
        ) from last_error

    # ------------------------------------------------------------------
    # KLINES (CANDLES OHLCV)
    # ------------------------------------------------------------------
    def get_klines(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[list[Any]]:
        """
        Busca candles OHLCV brutos no endpoint /api/v3/klines.

        Args:
            symbol: par de negociação, ex. "BTCUSDT".
            timeframe: timeframe amigável, ex. "4H", "1D" (ver config.TIMEFRAME_MAP).
            limit: quantidade de candles (máximo 1000, conforme a Binance).
            start_time: timestamp em milissegundos (opcional).
            end_time: timestamp em milissegundos (opcional).

        Returns:
            Lista de candles no formato bruto da Binance, onde cada candle é:
            [
                open_time, open, high, low, close, volume,
                close_time, quote_asset_volume, number_of_trades,
                taker_buy_base_volume, taker_buy_quote_volume, ignore
            ]
        """
        if timeframe not in TIMEFRAME_MAP:
            raise ValueError(
                f"Timeframe '{timeframe}' inválido. "
                f"Valores aceitos: {list(TIMEFRAME_MAP.keys())}"
            )

        safe_limit = min(limit, MAX_KLINES_LIMIT)

        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": TIMEFRAME_MAP[timeframe],
            "limit": safe_limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        return self._request(ENDPOINT_KLINES, params=params)

    # ------------------------------------------------------------------
    # PREÇO ATUAL
    # ------------------------------------------------------------------
    def get_price(self, symbol: str) -> float:
        """
        Busca o último preço negociado para o símbolo informado, via
        /api/v3/ticker/price.

        Returns:
            Preço atual como float.
        """
        params = {"symbol": symbol.upper()}
        data = self._request(ENDPOINT_TICKER_PRICE, params=params)

        try:
            return float(data["price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BinanceAPIError(
                f"Resposta inesperada de {ENDPOINT_TICKER_PRICE} para {symbol}: {data}"
            ) from exc

    # ------------------------------------------------------------------
    # ORDER BOOK (DEPTH)
    # ------------------------------------------------------------------
    def get_depth(self, symbol: str, limit: int = 100) -> dict[str, Any]:
        """
        Busca o order book (bids/asks) via /api/v3/depth.

        Args:
            symbol: par de negociação, ex. "BTCUSDT".
            limit: profundidade do book (valores aceitos pela Binance:
                5, 10, 20, 50, 100, 500, 1000, 5000).

        Returns:
            Dicionário bruto da Binance com as chaves "lastUpdateId",
            "bids" e "asks".
        """
        params = {"symbol": symbol.upper(), "limit": limit}
        return self._request(ENDPOINT_DEPTH, params=params)

    # ------------------------------------------------------------------
    # LIMPEZA DE RECURSOS
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Encerra a sessão HTTP subjacente. Útil em scripts de curta duração."""
        self._session.close()

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, *_exc_info: Any) -> None:
        self.close()
