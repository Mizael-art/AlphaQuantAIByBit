"""
providers/okx_client.py
=========================

Cliente HTTP de baixo nível para a API pública V5 da OKX
(https://www.okx.com/docs-v5/en/). Endpoints públicos, sem API Key:

- GET /api/v5/market/candles   -> candles OHLCV (últimas 1440 entradas)
- GET /api/v5/market/ticker    -> último preço / bid / ask
"""

from __future__ import annotations

import time
from typing import Any

import requests

OKX_BASE_URL = "https://www.okx.com"

ENDPOINT_CANDLES = "/api/v5/market/candles"
ENDPOINT_TICKER = "/api/v5/market/ticker"

# OKX usa "bar" nesse formato -- confirmado pela documentação oficial.
OKX_BAR_MAP: dict[str, str] = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1H": "1H", "2H": "2H", "4H": "4H", "6H": "6H", "12H": "12H",
    "1D": "1D", "1W": "1W", "1M": "1M",
}

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5
REQUEST_TIMEOUT = 10


class OKXAPIError(Exception):
    """Erro genérico levantado quando a OKX retorna uma resposta inválida ou de erro."""


class OKXClient:
    """Cliente HTTP para os endpoints públicos de Market Data (V5) da OKX."""

    def __init__(self, base_url: str = OKX_BASE_URL, timeout: int = REQUEST_TIMEOUT) -> None:
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
                    raise OKXAPIError(f"OKX retornou status {response.status_code} para {endpoint}: {response.text}")

                data = response.json()
                # Formato padrão OKX: {"code": "0", "msg": "", "data": [...]}
                if data.get("code") != "0":
                    raise OKXAPIError(f"Erro da OKX em {endpoint}: code={data.get('code')} msg={data.get('msg')}")

                return data.get("data", [])

            except (requests.RequestException, OKXAPIError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

        raise OKXAPIError(f"Falha ao consultar {endpoint} após {MAX_RETRIES} tentativas: {last_error}") from last_error

    def get_candles(
        self, inst_id: str, bar: str, limit: int = 300, after: int | None = None
    ) -> list[list[str]]:
        """
        GET /api/v5/market/candles

        Args:
            after: quando informado, retorna candles com timestamp
                ANTERIOR a este valor (paginação -- mesmo semânticas
                do `end`/`endTime` da Bybit/Binance).

        Returns:
            Lista de candles brutos: [ts, o, h, l, c, vol, volCcy,
            volCcyQuote, confirm], do mais recente para o mais antigo
            (confirmado na documentação -- inverter para cronológico).
        """
        params: dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": min(limit, 300)}
        if after is not None:
            params["after"] = after
        return self._request(ENDPOINT_CANDLES, params=params)

    def get_ticker(self, inst_id: str) -> dict[str, Any]:
        """GET /api/v5/market/ticker -> primeiro (único) item da lista."""
        data = self._request(ENDPOINT_TICKER, params={"instId": inst_id})
        if not data:
            raise OKXAPIError(f"Nenhum ticker retornado para {inst_id}.")
        return data[0]

    def close(self) -> None:
        self._session.close()
