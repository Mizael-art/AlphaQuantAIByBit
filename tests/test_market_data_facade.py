"""
tests/test_market_data_facade.py
===================================

Testes de `api.market_data.MarketData` com um `ProviderRouter` real
mas providers mockados por baixo (sem rede) — garante que a interface
pública (get_candles/get_ohlcv_dataframe/get_current_price) continua
funcionando após a refatoração multi-provider, e que
`DataUnavailableError` propaga em vez de ser mascarado.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api.market_data import MarketData
from models.candle import Candle
from providers.base import DataUnavailableError, MarketDataError, MarketDataProvider, Quote
from providers.router import ProviderRouter


def _valid_candles(n: int = 200) -> list[Candle]:
    now = datetime.now(timezone.utc)
    delta = timedelta(hours=1)
    candles = []
    price = 100.0
    for i in range(n):
        open_time = now - delta * (n - i)
        candles.append(
            Candle(
                open_time=open_time, open=price, high=price + 1, low=price - 1,
                close=price + 0.5, volume=10.0, close_time=open_time + delta,
            )
        )
        price += 0.1
    return candles


class _FakeProvider(MarketDataProvider):
    def __init__(self, name: str, supported_classes: tuple[str, ...], fail: bool = False) -> None:
        self.name = name
        self._supported = supported_classes
        self._fail = fail

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class in self._supported

    def get_candles(self, canonical_symbol: str, timeframe: str, limit: int) -> list[Candle]:
        if self._fail:
            raise MarketDataError("indisponível")
        return _valid_candles(200)

    def get_quote(self, canonical_symbol: str) -> Quote:
        if self._fail:
            raise MarketDataError("indisponível")
        return Quote(canonical_symbol=canonical_symbol, provider=self.name, last_price=123.45, bid=None, ask=None, spread=None)


def test_get_candles_returns_normalized_candles() -> None:
    router = ProviderRouter(providers=[_FakeProvider("bybit_crypto", ("crypto",))])
    md = MarketData(router=router)

    candles = md.get_candles("BTCUSDT", "1H")

    assert len(candles) == 200
    assert md.last_result is not None
    assert md.last_result.provider == "bybit_crypto"


def test_get_ohlcv_dataframe_has_expected_schema() -> None:
    router = ProviderRouter(providers=[_FakeProvider("bybit_crypto", ("crypto",))])
    md = MarketData(router=router)

    df = md.get_ohlcv_dataframe("BTCUSDT", "1H")

    expected_columns = {
        "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_volume",
    }
    assert expected_columns.issubset(set(df.columns))
    assert df.index.name == "open_time"
    assert len(df) == 200


def test_get_current_price_uses_quote_without_candles() -> None:
    router = ProviderRouter(providers=[_FakeProvider("bybit_crypto", ("crypto",))])
    md = MarketData(router=router)

    price = md.get_current_price("BTCUSDT")

    assert price == 123.45


def test_data_unavailable_propagates_not_masked() -> None:
    router = ProviderRouter(providers=[_FakeProvider("bybit_tradfi", ("metal",), fail=True)])
    md = MarketData(router=router)

    with pytest.raises(DataUnavailableError):
        md.get_ohlcv_dataframe("XAUUSD", "5m")


def test_order_book_rejected_for_non_crypto_asset_class() -> None:
    router = ProviderRouter(providers=[_FakeProvider("bybit_tradfi", ("metal",))])
    md = MarketData(router=router)

    with pytest.raises(DataUnavailableError, match="Order book"):
        md.get_order_book("XAUUSD")
