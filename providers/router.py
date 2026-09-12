"""
providers/router.py
=====================

Provider Router: ponto único de decisão de "qual provider usar para
qual ativo".

Fluxo (conforme Documento 1):
    symbol bruto
        -> SymbolMapper.resolve()          (canonical_symbol + asset_class)
        -> lista de providers elegíveis, em ordem de prioridade
        -> tenta cada um: get_candles + get_quote
        -> valida com DataValidator
        -> primeiro que passar: retorna
        -> nenhum passar: DataUnavailableError (nunca inventa dado)

Nenhum módulo acima deste (api/market_data.py, app.py, snapshot,
scanner) deve decidir "qual provider" sozinho — essa decisão vive
só aqui.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from models.candle import Candle
from providers.base import DataUnavailableError, MarketDataError, MarketDataProvider, Quote
from symbols.mapper import AssetClass, SymbolMapper, SymbolNotRecognizedError
from validation.data_quality import DataQualityError, validate_candles

logger = logging.getLogger("alphaquant.providers.router")


@dataclass(frozen=True, slots=True)
class MarketDataResult:
    """Resultado normalizado e já validado do ProviderRouter."""

    canonical_symbol: str
    asset_class: str
    provider: str
    timeframe: str
    candles: list[Candle]
    quote: Quote | None

    def to_meta_dict(self) -> dict[str, Any]:
        """Metadados de proveniência — usados para o campo `data_source` no JSON final."""
        return {
            "canonical_symbol": self.canonical_symbol,
            "asset_class": self.asset_class,
            "provider": self.provider,
            "timeframe": self.timeframe,
            "candles_count": len(self.candles),
        }


# Prioridade de providers por asset class. Ordem importa: o primeiro
# que "supports()" a asset class E retornar dados válidos vence.
#
# CRYPTO: Bybit é primário (o usuário opera por lá), Binance é
# fallback (implementação já existente, reaproveitada).
#
# FOREX/METAL/INDEX: só existe hoje o provider experimental da Bybit
# TradFi (ver providers/bybit_provider.py — não confirmado contra a
# API real). Não adicionamos um segundo provider "de mentira" só para
# preencher a lista — se a Bybit TradFi não responder, o resultado
# correto é DATA_UNAVAILABLE, e é isso que o router faz.
DEFAULT_PROVIDER_PRIORITY: dict[AssetClass, tuple[str, ...]] = {
    AssetClass.CRYPTO: ("bybit_crypto", "binance"),
    AssetClass.FOREX: ("bybit_tradfi",),
    AssetClass.METAL: ("bybit_tradfi",),
    AssetClass.INDEX: ("bybit_tradfi",),
}


class ProviderRouter:
    """
    Registry + lógica de fallback entre providers de Market Data.

    Exemplo:
        router = ProviderRouter(providers=[BybitCryptoProvider(), BinanceProvider(), BybitTradFiProvider()])
        result = router.get_market_data("XAUUSD", "5m")
    """

    def __init__(
        self,
        providers: list[MarketDataProvider],
        mapper: SymbolMapper | None = None,
        priority: dict[AssetClass, tuple[str, ...]] | None = None,
    ) -> None:
        self._providers_by_name: dict[str, MarketDataProvider] = {p.name: p for p in providers}
        self._mapper = mapper or SymbolMapper()
        self._priority = priority or DEFAULT_PROVIDER_PRIORITY

    def get_market_data(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        min_candles: int = 200,
        fetch_quote: bool = True,
    ) -> MarketDataResult:
        """
        Resolve o símbolo, tenta os providers elegíveis em ordem de
        prioridade e retorna o primeiro resultado válido.

        Args:
            fetch_quote: quando `False`, pula a chamada de rede extra
                para o ticker e devolve `quote=None`. Existe porque boa
                parte dos consumidores (qualquer coisa que só quer o
                DataFrame de candles, ex. `MarketData.get_ohlcv_dataframe`)
                nunca usa o campo `quote` do resultado — antes desta
                mudança, toda busca de candles pagava uma requisição
                HTTP de ticker inteiramente desperdiçada. Quem precisa
                do preço atual deve usar `get_quote()`/
                `MarketData.get_current_price`, que é o caminho
                dedicado e continua sempre buscando o ticker.

        Raises:
            SymbolNotRecognizedError: símbolo não mapeável (propagada,
                não é um problema de provider — é de input).
            DataUnavailableError: todos os providers elegíveis
                falharam (rede, símbolo inexistente no provider, ou
                dados que não passaram na validação de qualidade).
        """
        canonical = self._mapper.resolve(symbol)
        candidate_names = self._priority.get(canonical.asset_class, ())

        tried: list[str] = []
        last_reason = ""

        for provider_name in candidate_names:
            provider = self._providers_by_name.get(provider_name)
            if provider is None:
                continue  # provider configurado na prioridade mas não registrado nesta instância.

            if not provider.supports(canonical.canonical_symbol, canonical.asset_class.value):
                continue

            tried.append(provider_name)
            try:
                candles = provider.get_candles(canonical.canonical_symbol, timeframe, limit)
                validate_candles(
                    candles, canonical.canonical_symbol, timeframe, min_candles=min_candles
                )
                quote = provider.get_quote(canonical.canonical_symbol) if fetch_quote else None
            except (MarketDataError, DataQualityError, ValueError) as exc:
                last_reason = str(exc)
                logger.warning(
                    "Provider %s falhou para %s (%s): %s",
                    provider_name, canonical.canonical_symbol, timeframe, exc,
                )
                continue

            return MarketDataResult(
                canonical_symbol=canonical.canonical_symbol,
                asset_class=canonical.asset_class.value,
                provider=provider_name,
                timeframe=timeframe,
                candles=candles,
                quote=quote,
            )

        raise DataUnavailableError(
            symbol=canonical.canonical_symbol,
            timeframe=timeframe,
            tried=tried,
            reason=last_reason,
        )

    def get_quote(self, symbol: str) -> Quote:
        """
        Busca só o preço atual (sem candles), com o mesmo fallback de
        provider do `get_market_data` — mais leve para chamadas que só
        precisam do último preço (ex.: `MarketData.get_current_price`),
        evitando buscar e validar candles de novo à toa.

        Raises:
            DataUnavailableError: todos os providers elegíveis falharam.
        """
        canonical = self._mapper.resolve(symbol)
        candidate_names = self._priority.get(canonical.asset_class, ())

        tried: list[str] = []
        last_reason = ""

        for provider_name in candidate_names:
            provider = self._providers_by_name.get(provider_name)
            if provider is None or not provider.supports(
                canonical.canonical_symbol, canonical.asset_class.value
            ):
                continue

            tried.append(provider_name)
            try:
                return provider.get_quote(canonical.canonical_symbol)
            except MarketDataError as exc:
                last_reason = str(exc)
                logger.warning(
                    "Provider %s falhou (quote) para %s: %s", provider_name, symbol, exc
                )
                continue

        raise DataUnavailableError(
            symbol=canonical.canonical_symbol, timeframe="quote", tried=tried, reason=last_reason
        )

    def resolve_provider(self, symbol: str) -> tuple[MarketDataProvider, str, str]:
        """
        Resolve o símbolo e retorna a INSTÂNCIA do primeiro provider
        elegível (por prioridade), sem buscar candles nem validar
        dados ainda.

        Usado por quem precisa fazer múltiplas chamadas contra o MESMO
        provider (ex.: `backtest.history_fetcher` paginando histórico
        longo) — nunca misturar candles de dois providers diferentes
        dentro de uma mesma série histórica, mesmo que um fallback
        estivesse disponível para uma chamada isolada.

        Raises:
            DataUnavailableError: nenhum provider elegível está
                registrado/disponível para a asset class do símbolo.
        """
        canonical = self._mapper.resolve(symbol)
        candidate_names = self._priority.get(canonical.asset_class, ())

        for provider_name in candidate_names:
            provider = self._providers_by_name.get(provider_name)
            if provider is not None and provider.supports(
                canonical.canonical_symbol, canonical.asset_class.value
            ):
                return provider, canonical.canonical_symbol, canonical.asset_class.value

        raise DataUnavailableError(
            symbol=canonical.canonical_symbol,
            timeframe="n/a",
            tried=[],
            reason="Nenhum provider elegível registrado para esta asset class.",
        )

    def close(self) -> None:
        for provider in self._providers_by_name.values():
            provider.close()
