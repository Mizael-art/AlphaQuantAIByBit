"""
fundamentals/crypto_fundamentals.py
======================================

MOTOR 4/4 -- CryptoFundamentalsProvider (Documento 4, seção 19)

Fundamentos do ATIVO em si (market cap, supply circulante/total/máximo,
FDV -- fully diluted valuation, categoria/setor) -- contexto que nenhum
candle de exchange carrega, mas que importa para avaliar diluição
futura (supply travado ainda a liberar) e o tamanho relativo do ativo.

Vendor evaluation: CoinGecko `/coins/{id}` público é gratuito, sem API
key, e cobre praticamente qualquer ativo listado -- por isso é a
implementação de referência aqui. Limitação real do tier gratuito:
rate limit baixo (dezenas de req/min) e sem SLA -- se o volume de
consultas do AlphaQuant crescer, o tier pago da CoinGecko (ou
CoinMarketCap como alternativa) precisa ser cotado e comparado antes
de contratar, conforme a seção 19 pede.

NOTA DE AMBIENTE: este sandbox não tem acesso de rede a
`api.coingecko.com` (fora da allowlist). Implementado e coberto por
testes unitários com HTTP mockado, mas NÃO validado contra a API real.

Point-in-Time: `CryptoFundamentals.observed_at` é o instante da
consulta (CoinGecko só expõe o estado ATUAL, não um histórico
point-in-time de market cap/supply via este endpoint) -- por isso este
motor não deve ser usado para reconstruir o passado em backtest sem
antes confirmar que a fonte tem, de fato, série histórica point-in-time
(o endpoint `/coins/{id}/history` da própria CoinGecko é o candidato
natural para isso, mas fica fora do escopo desta primeira entrega).
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from fundamentals.base import FundamentalsDataProvider, FundamentalsUnavailableError

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
REQUEST_TIMEOUT = 10


@dataclass(frozen=True, slots=True)
class CryptoFundamentals:
    """Fundamentos de um ativo cripto, com proveniência Point-in-Time."""

    symbol: str
    market_cap_usd: float | None
    circulating_supply: float | None
    total_supply: float | None
    max_supply: float | None
    fully_diluted_valuation_usd: float | None
    category: str | None
    observed_at: datetime
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "market_cap_usd": self.market_cap_usd,
            "circulating_supply": self.circulating_supply,
            "total_supply": self.total_supply,
            "max_supply": self.max_supply,
            "fully_diluted_valuation_usd": self.fully_diluted_valuation_usd,
            "category": self.category,
            "observed_at": self.observed_at.isoformat(),
            "source": self.source,
        }


class CryptoFundamentalsProvider(FundamentalsDataProvider):
    """Interface para fundamentos de um ativo cripto (market cap, supply, FDV)."""

    @abstractmethod
    def get_fundamentals(self, symbol: str, as_of: datetime | None = None) -> CryptoFundamentals | None:
        """
        Retorna os fundamentos atuais do ativo.

        Args:
            as_of: reservado para quando uma fonte com histórico
                Point-in-Time real for integrada (ver nota do módulo);
                a implementação de referência atual (CoinGecko
                `/coins/{id}`) só expõe o estado corrente e ignora
                este parâmetro -- retorna sempre "agora".

        Returns:
            `None` quando o ativo não é coberto pela fonte configurada.
        """


class NullCryptoFundamentalsProvider(CryptoFundamentalsProvider):
    """Fallback explícito: nenhuma fonte de fundamentos configurada."""

    name = "none_configured"

    def get_fundamentals(self, symbol: str, as_of: datetime | None = None) -> CryptoFundamentals | None:
        raise FundamentalsUnavailableError(
            "Nenhum CryptoFundamentalsProvider configurado. Configure "
            "CoinGeckoFundamentalsProvider (ou outro vendor) antes de consultar fundamentos."
        )


class CoinGeckoFundamentalsProvider(CryptoFundamentalsProvider):
    """Fundamentos via CoinGecko `/coins/{id}` -- gratuito, sem API key."""

    name = "coingecko"

    def __init__(
        self,
        symbol_to_coingecko_id: dict[str, str],
        session: requests.Session | None = None,
    ) -> None:
        """
        Args:
            symbol_to_coingecko_id: mapa símbolo canônico -> id da
                CoinGecko (ex.: {"BTCUSDT": "bitcoin", "ETHUSDT": "ethereum"}).
                A CoinGecko identifica ativos por id próprio, não por
                par de trading.
        """
        self._symbol_to_id = symbol_to_coingecko_id
        self._session = session or requests.Session()

    def _resolve_id(self, symbol: str) -> str:
        coingecko_id = self._symbol_to_id.get(symbol.upper())
        if coingecko_id is None:
            raise FundamentalsUnavailableError(
                f"[{self.name}] símbolo {symbol} não mapeado para um id CoinGecko."
            )
        return coingecko_id

    def get_fundamentals(self, symbol: str, as_of: datetime | None = None) -> CryptoFundamentals | None:
        coingecko_id = self._resolve_id(symbol)
        try:
            response = self._session.get(
                f"{COINGECKO_BASE_URL}/coins/{coingecko_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "true",
                    "community_data": "false",
                    "developer_data": "false",
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise FundamentalsUnavailableError(
                f"[{self.name}] falha de rede para {symbol} ({coingecko_id}): {exc}"
            ) from exc

        payload = response.json()
        market_data = payload.get("market_data", {})

        return CryptoFundamentals(
            symbol=symbol.upper(),
            market_cap_usd=(market_data.get("market_cap") or {}).get("usd"),
            circulating_supply=market_data.get("circulating_supply"),
            total_supply=market_data.get("total_supply"),
            max_supply=market_data.get("max_supply"),
            fully_diluted_valuation_usd=(market_data.get("fully_diluted_valuation") or {}).get("usd"),
            category=(payload.get("categories") or [None])[0],
            observed_at=datetime.now(timezone.utc),
            source=self.name,
        )

    def close(self) -> None:
        self._session.close()
