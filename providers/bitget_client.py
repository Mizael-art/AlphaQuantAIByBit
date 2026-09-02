"""
providers/bitget_client.py
=============================

Cliente HTTP de baixo nível para a API pública V2 (Spot) da Bitget
(https://www.bitget.com/api-doc/spot/market/Get-Candle-Data). Endpoints
públicos, sem API Key:

- GET /api/v2/spot/market/candles           -> candles OHLCV (até 1000)
- GET /api/v2/spot/market/history-candles   -> candles OHLCV mais antigos
- GET /api/v2/spot/market/tickers           -> último preço / bid / ask
"""

from __future__ import annotations

import time
from typing import Any

import requests

BITGET_BASE_URL = "https://api.bitget.com"

ENDPOINT_CANDLES = "/api/v2/spot/market/candles"
ENDPOINT_HISTORY_CANDLES = "/api/v2/spot/market/history-candles"
ENDPOINT_TICKERS = "/api/v2/spot/market/tickers"

# Bitget usa "granularity" nesse formato -- confirmado pela documentação oficial.
BITGET_GRANULARITY_MAP: dict[str, str] = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1H": "1h", "4H": "4h", "6H": "6h", "12H": "12h", "1D": "1day", "1W": "1week",
}

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5
REQUEST_TIMEOUT = 10


class BitgetAPIError(Exception):
    """Erro genérico levantado quando a Bitget retorna uma resposta inválida ou de erro."""


class BitgetClient:
    """Cliente HTTP para os endpoints públicos de Market Data (V2 Spot) da Bitget."""

    def __init__(self, base_url: str = BITGET_BASE_URL, timeout: int = REQUEST_TIMEOUT) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._session = requests.Session()

    def _request(self, endpoint: str, params: dict[str, Any]) -> list[Any]:
        url = f"{self.base_url}{endpoint}"
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._session.get(url, params=params, timeout=self.timeout)
                if response.status_code != 200:
                    raise BitgetAPIError(f"Bitget retornou status {response.status_code} para {endpoint}: {response.text}")

                data = response.json()
                # Formato padrão Bitget: {"code": "00000", "msg": "success", "data": [...]}
                if data.get("code") != "00000":
                    raise BitgetAPIError(f"Erro da Bitget em {endpoint}: code={data.get('code')} msg={data.get('msg')}")

                return data.get("data", [])

            except (requests.RequestException, BitgetAPIError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

        raise BitgetAPIError(f"Falha ao consultar {endpoint} após {MAX_RETRIES} tentativas: {last_error}") from last_error

    def get_candles(
        self, symbol: str, granularity: str, limit: int = 200, end_time: int | None = None
    ) -> list[list[str]]:
        """
        GET /api/v2/spot/market/candles

        Returns:
            Lista de candles brutos: [ts, open, high, low, close,
            baseVol, quoteVol, usdtVol]. Ordem não garantida
            explicitamente na doc -- o provider ordena por timestamp
            defensivamente antes de devolver.
        """
        params: dict[str, Any] = {
            "symbol": symbol, "granularity": granularity, "limit": min(limit, 1000),
        }
        if end_time is not None:
            params["endTime"] = end_time
        return self._request(ENDPOINT_CANDLES, params=params)

    def get_ticker(self, symbol: str) -> dict[str, Any]:
        """GET /api/v2/spot/market/tickers?symbol=X -> primeiro item da lista."""
        data = self._request(ENDPOINT_TICKERS, params={"symbol": symbol})
        if not data:
            raise BitgetAPIError(f"Nenhum ticker retornado para {symbol}.")
        return data[0]

    def close(self) -> None:
        self._session.close()
