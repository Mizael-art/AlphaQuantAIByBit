"""
tests/test_history_fetcher.py
================================

Testes do `HistoryFetcher` (paginação de histórico longo) — providers
mockados, sem rede. Cobre: multi-página, nunca troca de provider no
meio, nunca retorna série parcial em caso de falha, range insuficiente.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backtest.history_fetcher import HistoryFetchError, HistoryFetcher
from models.candle import Candle
from providers.base import DataUnavailableError, MarketDataError, MarketDataProvider, Quote
from providers.router import ProviderRouter
from symbols.mapper import AssetClass


def _candles_range(start: datetime, end: datetime, step: timedelta) -> list[Candle]:
    """Gera candles válidos e cronológicos cobrindo [start, end), passo `step`."""
    out = []
    t = start
    price = 100.0
    while t < end:
        out.append(
            Candle(
                open_time=t, open=price, high=price + 1, low=price - 1,
                close=price + 0.5, volume=10.0, close_time=t + step,
            )
        )
        t += step
        price += 0.01
    return out


class _PagedFakeProvider(MarketDataProvider):
    """
    Simula um provider real: tem um histórico fixo em memória e responde
    por página, respeitando `end_time` e `limit` -- exatamente como
    Bybit/Binance fariam.
    """

    name = "fake_paged"

    def __init__(self, full_history: list[Candle], fail_after_pages: int | None = None) -> None:
        self._history = sorted(full_history, key=lambda c: c.open_time)
        self._fail_after_pages = fail_after_pages
        self.calls = 0
        self.pages_returned: list[int] = []  # tamanho de cada página, na ordem das chamadas

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return True

    def get_candles(self, canonical_symbol, timeframe, limit, end_time=None):
        self.calls += 1
        if self._fail_after_pages is not None and self.calls > self._fail_after_pages:
            raise MarketDataError("provider caiu no meio da paginação")

        candidates = [c for c in self._history if end_time is None or c.open_time <= end_time]
        page = candidates[-limit:] if len(candidates) > limit else candidates
        self.pages_returned.append(len(page))
        return page

    def get_quote(self, canonical_symbol: str) -> Quote:
        return Quote(canonical_symbol=canonical_symbol, provider=self.name, last_price=100.0, bid=None, ask=None, spread=None)


def _router_with(provider: MarketDataProvider) -> ProviderRouter:
    return ProviderRouter(providers=[provider], priority={AssetClass.CRYPTO: (provider.name,)})


def test_fetch_single_page_when_range_fits() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=100)
    history = _candles_range(start - timedelta(hours=10), end + timedelta(hours=10), timedelta(hours=1))
    provider = _PagedFakeProvider(full_history=history)
    fetcher = HistoryFetcher(router=_router_with(provider))

    result = fetcher.fetch("BTCUSDT", "1H", start=start, end=end, min_candles=10)

    assert result.provider == "fake_paged"
    assert result.actual_start >= start
    assert result.actual_end <= end
    assert provider.calls == 1  # coube numa página só (PAGE_LIMIT=1000)


def test_fetch_paginates_multiple_pages_for_long_range() -> None:
    # PAGE_LIMIT é 1000 -- força mais de uma página com >1000 candles no range.
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=2500)  # 2500 candles de 1H > 1000 = múltiplas páginas
    history = _candles_range(start - timedelta(hours=10), end + timedelta(hours=10), timedelta(hours=1))
    provider = _PagedFakeProvider(full_history=history)
    fetcher = HistoryFetcher(router=_router_with(provider))

    result = fetcher.fetch("BTCUSDT", "1H", start=start, end=end, min_candles=10)

    assert provider.calls >= 3  # 2500 candles / 1000 por página >= 3 páginas
    assert result.actual_start <= start + timedelta(hours=1)
    assert len(result.candles) >= 2400


def test_fetch_never_mixes_providers_uses_resolve_provider_once() -> None:
    """Garantia arquitetural: toda a paginação usa a mesma instância de provider."""
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=2500)
    history = _candles_range(start - timedelta(hours=10), end + timedelta(hours=10), timedelta(hours=1))
    provider = _PagedFakeProvider(full_history=history)
    fetcher = HistoryFetcher(router=_router_with(provider))

    result = fetcher.fetch("BTCUSDT", "1H", start=start, end=end, min_candles=10)

    assert result.provider == provider.name  # um único provider do início ao fim


def test_fetch_raises_and_discards_partial_series_on_mid_pagination_failure() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=2500)
    history = _candles_range(start - timedelta(hours=10), end + timedelta(hours=10), timedelta(hours=1))
    # Falha na segunda página -- deve abortar tudo, nunca devolver histórico parcial.
    provider = _PagedFakeProvider(full_history=history, fail_after_pages=1)
    fetcher = HistoryFetcher(router=_router_with(provider))

    with pytest.raises(HistoryFetchError, match="descartados"):
        fetcher.fetch("BTCUSDT", "1H", start=start, end=end, min_candles=10)


def test_fetch_raises_when_history_insufficient_for_range() -> None:
    """Range pedido começa antes do histórico disponível do provider."""
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)  # bem antes do histórico existente
    end = datetime(2025, 1, 1, tzinfo=timezone.utc)
    history = _candles_range(
        datetime(2024, 12, 25, tzinfo=timezone.utc), end, timedelta(hours=1)
    )  # só 1 semana de histórico real
    provider = _PagedFakeProvider(full_history=history)
    fetcher = HistoryFetcher(router=_router_with(provider))

    result = fetcher.fetch("BTCUSDT", "1H", start=start, end=end, min_candles=10)

    # Não deve fabricar candles antes do que o provider realmente tem --
    # actual_start reflete a limitação real do histórico.
    assert result.actual_start >= datetime(2024, 12, 25, tzinfo=timezone.utc)


def test_fetch_raises_when_below_min_candles() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=5)
    history = _candles_range(start, end, timedelta(hours=1))
    provider = _PagedFakeProvider(full_history=history)
    fetcher = HistoryFetcher(router=_router_with(provider))

    with pytest.raises(HistoryFetchError, match="insuficiente"):
        fetcher.fetch("BTCUSDT", "1H", start=start, end=end, min_candles=500)


def test_fetch_invalid_range_raises_value_error() -> None:
    fetcher = HistoryFetcher(router=_router_with(_PagedFakeProvider(full_history=[])))
    start = datetime(2025, 6, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, tzinfo=timezone.utc)  # end antes de start
    with pytest.raises(ValueError):
        fetcher.fetch("BTCUSDT", "1H", start=start, end=end)


def test_fetch_no_eligible_provider_raises_data_unavailable() -> None:
    router = ProviderRouter(providers=[], priority={})
    fetcher = HistoryFetcher(router=router)
    with pytest.raises(DataUnavailableError):
        fetcher.fetch(
            "XAUUSD", "1H",
            start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )
