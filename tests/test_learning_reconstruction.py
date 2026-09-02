"""
tests/test_learning_reconstruction.py
========================================

Smoke test de `learning/reconstruction.py` com provider fake -- mesmo
padrão de `tests/test_discovery_engine.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backtest.history_fetcher import HistoryFetcher
from learning.reconstruction import reconstruct_context
from models.candle import Candle
from providers.base import MarketDataProvider, Quote
from providers.router import ProviderRouter


def _candles(n: int, end: datetime) -> list[Candle]:
    delta = timedelta(hours=1)
    candles = []
    price = 100.0
    for i in range(n):
        open_time = end - delta * (n - i)
        price += 0.1
        o, c = price - 0.1, price
        h, l = max(o, c) + 0.2, min(o, c) - 0.2
        candles.append(Candle(open_time=open_time, open=o, high=h, low=l, close=c, volume=100.0, close_time=open_time + delta))
    return candles


class _FakeProvider(MarketDataProvider):
    name = "bybit_crypto"

    def __init__(self, end: datetime) -> None:
        self._end = end

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class == "crypto"

    def get_candles(self, canonical_symbol: str, timeframe: str, limit: int, end_time=None) -> list[Candle]:
        end = end_time or self._end
        return _candles(min(limit, 300), end)

    def get_quote(self, canonical_symbol: str) -> Quote:
        return Quote(canonical_symbol=canonical_symbol, provider=self.name, last_price=150.0, bid=None, ask=None, spread=None)


def test_reconstruct_context_returns_facts_and_inferences_without_hypothesis() -> None:
    signal_time = datetime.now(timezone.utc) - timedelta(days=1)
    fetcher = HistoryFetcher(router=ProviderRouter(providers=[_FakeProvider(signal_time)]))

    context = reconstruct_context("ETHUSDT", "long", "1H", signal_time, fetcher)
    d = context.to_dict()

    assert "trend" in d["facts"]
    assert "regime" in d["facts"]
    assert "quality_score" in d["inferences"]
    assert "não é reconstruível" in d["hypothesis_note"]
