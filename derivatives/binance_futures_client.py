"""
derivatives/binance_futures_client.py
========================================

Cliente HTTP para os endpoints públicos da Binance **Futures**
(USDT-M), usados para extrair dados de derivativos sem depender de
provedores pagos como CoinGlass:

- GET /fapi/v1/openInterest          -> Open Interest atual
- GET /fapi/v1/premiumIndex          -> Funding Rate atual + Mark Price
- GET /futures/data/globalLongShortAccountRatio -> Long/Short Ratio (contas)
- GET /futures/data/topLongShortPositionRatio    -> Long/Short Ratio (top traders, por posição)

Todos os endpoints acima são públicos — nenhuma API Key é necessária.

Observação: nem todo par listado no mercado Spot tem um contrato
futuro correspondente. Se o símbolo não existir em Futures, os
métodos abaixo levantam `BinanceAPIError`, e a camada de análise deve
tratar isso como "derivativos indisponíveis para este ativo".
"""

from __future__ import annotations

import time
from typing import Any

import requests

from api.binance_client import BinanceAPIError
from config import MAX_RETRIES, REQUEST_TIMEOUT, RETRY_BACKOFF_SECONDS

BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"

ENDPOINT_OPEN_INTEREST = "/fapi/v1/openInterest"
ENDPOINT_PREMIUM_INDEX = "/fapi/v1/premiumIndex"
ENDPOINT_GLOBAL_LONG_SHORT_RATIO = "/futures/data/globalLongShortAccountRatio"
ENDPOINT_TOP_LONG_SHORT_POSITION_RATIO = "/futures/data/topLongShortPositionRatio"


class BinanceFuturesClient:
    """
    Cliente HTTP para os endpoints públicos de dados de mercado da
    Binance Futures (USDT-M). Não requer API Key.
    """

    def __init__(self, base_url: str = BINANCE_FUTURES_BASE_URL, timeout: int = REQUEST_TIMEOUT) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._session = requests.Session()

    def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{endpoint}"
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._session.get(url, params=params, timeout=self.timeout)

                if response.status_code != 200:
                    raise BinanceAPIError(
                        f"Binance Futures retornou status {response.status_code} "
                        f"para {endpoint}: {response.text}"
                    )

                data = response.json()

                if isinstance(data, dict) and "code" in data and "msg" in data:
                    raise BinanceAPIError(
                        f"Erro da Binance Futures em {endpoint}: code={data['code']} msg={data['msg']}"
                    )

                return data

            except (requests.RequestException, BinanceAPIError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

        raise BinanceAPIError(
            f"Falha ao consultar {endpoint} (Futures) após {MAX_RETRIES} tentativas: {last_error}"
        ) from last_error

    def get_open_interest(self, symbol: str) -> dict[str, Any]:
        """Retorna o Open Interest atual (em contratos/moeda base) para o símbolo."""
        return self._request(ENDPOINT_OPEN_INTEREST, params={"symbol": symbol.upper()})

    def get_premium_index(self, symbol: str) -> dict[str, Any]:
        """
        Retorna o Funding Rate atual, o Mark Price e o Index Price via
        /fapi/v1/premiumIndex — o snapshot mais atual (o próximo
        funding só é cobrado no horário programado, mas a taxa
        projetada já vem aqui).
        """
        return self._request(ENDPOINT_PREMIUM_INDEX, params={"symbol": symbol.upper()})

    def get_global_long_short_ratio(self, symbol: str, period: str = "1h", limit: int = 1) -> list[dict[str, Any]]:
        """
        Retorna a razão Long/Short de TODAS as contas (não só top
        traders) para o símbolo, na granularidade `period`
        (5m,15m,30m,1h,2h,4h,6h,12h,1d).
        """
        return self._request(
            ENDPOINT_GLOBAL_LONG_SHORT_RATIO,
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )

    def get_top_long_short_position_ratio(
        self, symbol: str, period: str = "1h", limit: int = 1
    ) -> list[dict[str, Any]]:
        """
        Retorna a razão Long/Short por POSIÇÃO dos "top traders" (contas
        com maior volume/posição) — geralmente considerado um proxy
        melhor de "smart money" do que a razão de contas totais.
        """
        return self._request(
            ENDPOINT_TOP_LONG_SHORT_POSITION_RATIO,
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "BinanceFuturesClient":
        return self

    def __exit__(self, *_exc_info: Any) -> None:
        self.close()
