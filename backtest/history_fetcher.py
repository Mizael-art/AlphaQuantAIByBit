"""
backtest/history_fetcher.py
==============================

Busca histórico de candles mais longo do que um provider entrega numa
única chamada (Binance e Bybit V5 limitam a 1000 candles por request).

Regra crítica: TODA a série histórica de um fetch vem do MESMO
provider — nunca faz fallback no meio da paginação. Se o provider
falhar na página N, a busca inteira falha (levanta o erro), em vez de
silenciosamente continuar com outro provider e produzir uma série
"Frankenstein" (ex.: metade Bybit, metade Binance, com possíveis
diferenças de preço/volume entre venues). Isso segue o mesmo
princípio de "nunca inventar/mascarar dado" do resto do motor —
misturar fontes é uma forma sutil de inventar dado.

Sem cache persistente nesta versão (Render roda com disco efêmero por
padrão) — cada chamada busca o histórico sob demanda, em memória, só
durante a duração da requisição.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from models.candle import Candle
from providers.base import DataUnavailableError, MarketDataError
from providers.router import ProviderRouter
from validation.data_quality import DataQualityError, validate_candles

logger = logging.getLogger("alphaquant.backtest.history_fetcher")

# Limite de candles por página, por provider (ambos capam em 1000 —
# ver documentação oficial da Binance /klines e da Bybit V5 /kline).
PAGE_LIMIT = 1000

# Segurança contra loop infinito (ex.: bug de paginação, provider que
# não avança o cursor). 500 páginas * 1000 candles = 500k candles,
# bem além de qualquer backtest razoável em qualquer timeframe.
MAX_PAGES = 500


class HistoryFetchError(Exception):
    """Erro ao buscar/paginar histórico — nunca produz série parcial silenciosa."""


@dataclass(frozen=True, slots=True)
class HistoryResult:
    """Histórico completo e validado, pronto para o simulador de backtest."""

    canonical_symbol: str
    asset_class: str
    provider: str
    timeframe: str
    candles: list[Candle]
    requested_start: datetime
    requested_end: datetime
    actual_start: datetime
    actual_end: datetime

    def to_meta_dict(self) -> dict:
        return {
            "canonical_symbol": self.canonical_symbol,
            "asset_class": self.asset_class,
            "provider": self.provider,
            "timeframe": self.timeframe,
            "candles_count": len(self.candles),
            "requested_range": [self.requested_start.isoformat(), self.requested_end.isoformat()],
            "actual_range": [self.actual_start.isoformat(), self.actual_end.isoformat()],
        }


class HistoryFetcher:
    """
    Pagina candles de um único provider até cobrir o range solicitado.

    Exemplo:
        fetcher = HistoryFetcher(router=build_default_router())
        result = fetcher.fetch(
            symbol="XAUUSD", timeframe="5m",
            start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end=datetime(2025, 7, 1, tzinfo=timezone.utc),
        )
    """

    def __init__(self, router: ProviderRouter) -> None:
        self._router = router

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        min_candles: int = 50,
    ) -> HistoryResult:
        """
        Busca todos os candles de `symbol`/`timeframe` entre `start` e
        `end` (padrão: agora), paginando quantas vezes forem
        necessárias contra um único provider.

        Raises:
            ValueError: range inválido (`start` >= `end`).
            DataUnavailableError: nenhum provider elegível registrado
                para a asset class deste símbolo.
            HistoryFetchError: o provider falhou em alguma página (a
                série NUNCA é retornada parcial/incompleta sem avisar).
        """
        end = end or datetime.now(timezone.utc)
        if start >= end:
            raise ValueError(f"Range inválido: start ({start}) deve ser anterior a end ({end}).")

        provider, canonical_symbol, asset_class = self._router.resolve_provider(symbol)

        collected: list[Candle] = []
        cursor = end
        pages_fetched = 0

        while pages_fetched < MAX_PAGES:
            pages_fetched += 1
            try:
                page = provider.get_candles(
                    canonical_symbol, timeframe, limit=PAGE_LIMIT, end_time=cursor
                )
            except (MarketDataError, ValueError) as exc:
                raise HistoryFetchError(
                    f"Falha ao paginar histórico de {canonical_symbol} ({timeframe}) via "
                    f"'{provider.name}' na página {pages_fetched} "
                    f"(já coletados {len(collected)} candles, descartados -- "
                    f"não retorno série parcial): {exc}"
                ) from exc

            if not page:
                break  # provider não tem mais dados anteriores a `cursor`.

            collected = page + collected
            oldest_open_time = page[0].open_time

            if oldest_open_time <= start:
                break  # já cobrimos o range pedido.
            if len(page) < PAGE_LIMIT:
                break  # provider devolveu menos que o limite -- não há mais histórico antes disso.

            cursor = oldest_open_time - timedelta(milliseconds=1)

        else:
            raise HistoryFetchError(
                f"Paginação de {canonical_symbol} ({timeframe}) excedeu {MAX_PAGES} páginas "
                f"sem cobrir o range solicitado -- abortado por segurança (possível loop)."
            )

        # Dedup (defensivo -- providers não deveriam repetir candle no
        # limite exato de uma página, mas não custa garantir) e recorte
        # exato ao range pedido.
        deduped: dict[datetime, Candle] = {c.open_time: c for c in collected}
        in_range = sorted(
            (c for c in deduped.values() if start <= c.open_time <= end),
            key=lambda c: c.open_time,
        )

        if len(in_range) < min_candles:
            raise HistoryFetchError(
                f"Histórico insuficiente para {canonical_symbol} ({timeframe}) no range "
                f"{start.isoformat()} - {end.isoformat()}: {len(in_range)} candles via "
                f"'{provider.name}', mínimo {min_candles}. Pode ser um range antes da "
                f"existência do ativo/listagem, ou o provider não ter esse histórico."
            )

        try:
            validate_candles(
                in_range, canonical_symbol, timeframe, min_candles=min_candles,
                check_freshness=False,  # histórico passado é esperado ser "velho" -- não é stale.
            )
        except DataQualityError as exc:
            raise HistoryFetchError(
                f"Histórico de {canonical_symbol} ({timeframe}) via '{provider.name}' "
                f"não passou na validação de qualidade: {exc}"
            ) from exc

        return HistoryResult(
            canonical_symbol=canonical_symbol,
            asset_class=asset_class,
            provider=provider.name,
            timeframe=timeframe,
            candles=in_range,
            requested_start=start,
            requested_end=end,
            actual_start=in_range[0].open_time,
            actual_end=in_range[-1].open_time,
        )
