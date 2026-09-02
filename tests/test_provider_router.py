"""
tests/test_provider_router.py
================================

Testes do `ProviderRouter` — cobre roteamento por asset class,
fallback entre providers e o caso `DATA_UNAVAILABLE`, tudo com
providers mockados (sem rede), conforme pedido no Documento 1:

    "BTCUSDT -> provider correto"
    "XAUUSD -> provider correto"
    "NAS100 -> provider correto"
    "Nenhum símbolo deve ser enviado para um provider incompatível."
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from models.candle import Candle
from providers.base import DataUnavailableError, MarketDataError, MarketDataProvider, Quote
from providers.router import DEFAULT_PROVIDER_PRIORITY, ProviderRouter
from symbols.mapper import AssetClass
from validation.data_quality import DataQualityError


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
    """Provider mockado — nunca faz rede, comportamento controlado pelo teste."""

    def __init__(
        self,
        name: str,
        supported_classes: tuple[str, ...],
        fail: bool = False,
        return_invalid_candles: bool = False,
    ) -> None:
        self.name = name
        self._supported_classes = supported_classes
        self._fail = fail
        self._return_invalid_candles = return_invalid_candles
        self.calls: list[str] = []

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class in self._supported_classes

    def get_candles(self, canonical_symbol: str, timeframe: str, limit: int) -> list[Candle]:
        self.calls.append(canonical_symbol)
        if self._fail:
            raise MarketDataError(f"[{self.name}] símbolo indisponível: {canonical_symbol}")
        if self._return_invalid_candles:
            return _valid_candles(5)  # menos que o mínimo -> falha na validação
        return _valid_candles(200)

    def get_quote(self, canonical_symbol: str) -> Quote:
        if self._fail:
            raise MarketDataError(f"[{self.name}] quote indisponível: {canonical_symbol}")
        return Quote(
            canonical_symbol=canonical_symbol, provider=self.name,
            last_price=100.0, bid=99.9, ask=100.1, spread=0.2,
        )


def test_crypto_routes_to_bybit_primary() -> None:
    bybit = _FakeProvider("bybit_crypto", ("crypto",))
    binance = _FakeProvider("binance", ("crypto",))
    router = ProviderRouter(providers=[bybit, binance])

    result = router.get_market_data("BTCUSDT", "1H")

    assert result.provider == "bybit_crypto"
    assert result.canonical_symbol == "BTCUSDT"
    assert result.asset_class == "crypto"
    assert bybit.calls == ["BTCUSDT"]
    assert binance.calls == []  # fallback nunca deve ter sido chamado


def test_crypto_falls_back_to_binance_when_bybit_fails() -> None:
    bybit = _FakeProvider("bybit_crypto", ("crypto",), fail=True)
    binance = _FakeProvider("binance", ("crypto",))
    router = ProviderRouter(providers=[bybit, binance])

    result = router.get_market_data("ETHUSDT", "4H")

    assert result.provider == "binance"
    assert bybit.calls == ["ETHUSDT"]
    assert binance.calls == ["ETHUSDT"]


def test_falls_back_when_primary_returns_low_quality_data() -> None:
    bybit = _FakeProvider("bybit_crypto", ("crypto",), return_invalid_candles=True)
    binance = _FakeProvider("binance", ("crypto",))
    router = ProviderRouter(providers=[bybit, binance])

    result = router.get_market_data("SOLUSDT", "1H")

    assert result.provider == "binance"


def test_tradfi_routes_to_bybit_tradfi() -> None:
    tradfi = _FakeProvider("bybit_tradfi", ("forex", "metal", "index"))
    router = ProviderRouter(providers=[tradfi])

    result = router.get_market_data("XAUUSD", "5m")

    assert result.provider == "bybit_tradfi"
    assert result.canonical_symbol == "XAUUSD"
    assert result.asset_class == "metal"


def test_nas100_routes_to_bybit_tradfi() -> None:
    tradfi = _FakeProvider("bybit_tradfi", ("forex", "metal", "index"))
    router = ProviderRouter(providers=[tradfi])

    result = router.get_market_data("NAS100", "15m")

    assert result.provider == "bybit_tradfi"
    assert result.asset_class == "index"


def test_incompatible_provider_is_never_called_for_wrong_asset_class() -> None:
    """Um provider só de cripto nunca deve ser sequer chamado para XAUUSD."""
    crypto_only = _FakeProvider("bybit_crypto", ("crypto",))
    router = ProviderRouter(providers=[crypto_only])

    with pytest.raises(DataUnavailableError):
        router.get_market_data("XAUUSD", "5m")

    assert crypto_only.calls == []  # nunca chamado - asset class incompatível


def test_all_providers_failing_raises_data_unavailable() -> None:
    p1 = _FakeProvider("bybit_tradfi", ("metal",), fail=True)
    router = ProviderRouter(
        providers=[p1],
        priority={AssetClass.METAL: ("bybit_tradfi",)},
    )

    with pytest.raises(DataUnavailableError) as exc_info:
        router.get_market_data("XAUUSD", "5m")

    assert "XAUUSD" in str(exc_info.value)
    assert exc_info.value.tried == ["bybit_tradfi"]


def test_no_provider_registered_for_asset_class_raises_data_unavailable() -> None:
    router = ProviderRouter(providers=[], priority={})

    with pytest.raises(DataUnavailableError) as exc_info:
        router.get_market_data("XAUUSD", "5m")

    assert exc_info.value.tried == []


def test_unrecognized_symbol_is_not_masked_as_data_unavailable() -> None:
    from symbols.mapper import SymbolNotRecognizedError

    router = ProviderRouter(providers=[])
    with pytest.raises(SymbolNotRecognizedError):
        router.get_market_data("NOTASYMBOL999", "1H")


def test_get_quote_uses_same_fallback_without_fetching_candles() -> None:
    bybit = _FakeProvider("bybit_crypto", ("crypto",), fail=True)
    binance = _FakeProvider("binance", ("crypto",))
    router = ProviderRouter(providers=[bybit, binance])

    quote = router.get_quote("BTCUSDT")

    assert quote.provider == "binance"
    assert bybit.calls == []  # get_quote não chama get_candles


def test_default_priority_config_has_crypto_with_binance_fallback() -> None:
    assert DEFAULT_PROVIDER_PRIORITY[AssetClass.CRYPTO] == ("bybit_crypto", "binance")


def test_default_priority_config_has_tradfi_classes() -> None:
    assert "bybit_tradfi" in DEFAULT_PROVIDER_PRIORITY[AssetClass.METAL]
    assert "bybit_tradfi" in DEFAULT_PROVIDER_PRIORITY[AssetClass.INDEX]
    assert "bybit_tradfi" in DEFAULT_PROVIDER_PRIORITY[AssetClass.FOREX]
