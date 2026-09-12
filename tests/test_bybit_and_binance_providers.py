"""
tests/test_bybit_and_binance_providers.py
============================================

Testes dos providers concretos (`BybitCryptoProvider`,
`BybitTradFiProvider`, `BinanceProvider`) com o cliente HTTP de baixo
nível mockado via injeção de dependência — sem nenhuma chamada de
rede real. Cobre conversão de candle bruto -> `Candle` normalizado e
tratamento de erro do provider.
"""

from __future__ import annotations

import pytest

from providers.base import MarketDataError
from providers.binance_provider import BinanceProvider
from providers.bybit_provider import BybitCryptoProvider, BybitTradFiProvider
from symbols.mapper import SymbolMapper


# ----------------------------------------------------------------------
# Fakes de baixo nível (substituem BybitClient / BinanceClient reais)
# ----------------------------------------------------------------------
class _FakeBybitClient:
    def __init__(self, kline_rows: list[list[str]] | None = None, raise_on_kline: bool = False) -> None:
        self._kline_rows = kline_rows or []
        self._raise_on_kline = raise_on_kline
        self.requested_symbols: list[str] = []

    def get_kline(self, category: str, symbol: str, interval: str, limit: int = 500, end: int | None = None):
        self.requested_symbols.append(symbol)
        if self._raise_on_kline:
            from providers.bybit_client import BybitAPIError
            raise BybitAPIError(f"símbolo inválido: {symbol}")
        return self._kline_rows

    def get_tickers(self, category: str, symbol: str):
        return {"lastPrice": "2400.5", "bid1Price": "2400.0", "ask1Price": "2401.0"}

    def close(self) -> None:
        pass


class _FakeBinanceClient:
    def __init__(self, klines: list[list] | None = None, raise_on_klines: bool = False) -> None:
        self._klines = klines or []
        self._raise = raise_on_klines

    def get_klines(self, symbol: str, timeframe: str, limit: int = 500, end_time: int | None = None):
        if self._raise:
            from api.binance_client import BinanceAPIError
            raise BinanceAPIError(f"símbolo inválido: {symbol}")
        return self._klines

    def get_price(self, symbol: str) -> float:
        if self._raise:
            from api.binance_client import BinanceAPIError
            raise BinanceAPIError(f"símbolo inválido: {symbol}")
        return 65000.5

    def close(self) -> None:
        pass


def _bybit_raw_row(open_time_ms: int, price: float) -> list[str]:
    """[start, open, high, low, close, volume, turnover] -- formato oficial V5."""
    return [str(open_time_ms), str(price), str(price + 1), str(price - 1), str(price + 0.5), "10.5", "1000.0"]


def _binance_raw_row(open_time_ms: int, price: float) -> list:
    """Formato de array bruto da Binance /api/v3/klines (12 campos)."""
    return [
        open_time_ms, str(price), str(price + 1), str(price - 1), str(price + 0.5),
        "10.5", open_time_ms + 3_600_000, "1000.0", 42, "5.0", "500.0", "0",
    ]


# ----------------------------------------------------------------------
# BybitCryptoProvider
# ----------------------------------------------------------------------
def test_bybit_crypto_provider_converts_candles() -> None:
    # A Bybit V5 retorna do candle mais recente para o mais antigo -- o
    # fake precisa simular exatamente isso para o teste validar a inversão.
    rows = [_bybit_raw_row(1_700_000_000_000 + i * 3_600_000, 100 + i) for i in reversed(range(5))]
    fake_client = _FakeBybitClient(kline_rows=rows)
    provider = BybitCryptoProvider(client=fake_client, mapper=SymbolMapper())

    candles = provider.get_candles("BTCUSDT", "1H", limit=5)

    assert len(candles) == 5
    # Bybit retorna do mais recente pro mais antigo; provider deve inverter.
    assert candles[0].open_time < candles[-1].open_time
    assert candles[0].taker_buy_volume is None  # Bybit não expõe esse campo -- nunca fabricado
    assert fake_client.requested_symbols == ["BTCUSDT"]  # sem override para cripto


def test_bybit_crypto_provider_supports_only_crypto() -> None:
    provider = BybitCryptoProvider(client=_FakeBybitClient(), mapper=SymbolMapper())
    assert provider.supports("BTCUSDT", "crypto") is True
    assert provider.supports("XAUUSD", "metal") is False


def test_bybit_crypto_provider_raises_market_data_error_on_api_failure() -> None:
    provider = BybitCryptoProvider(client=_FakeBybitClient(raise_on_kline=True), mapper=SymbolMapper())
    with pytest.raises(MarketDataError):
        provider.get_candles("BTCUSDT", "1H", limit=5)


def test_bybit_crypto_quote_conversion() -> None:
    provider = BybitCryptoProvider(client=_FakeBybitClient(), mapper=SymbolMapper())
    quote = provider.get_quote("ETHUSDT")
    assert quote.last_price == 2400.5
    assert quote.bid == 2400.0
    assert quote.ask == 2401.0
    assert quote.spread == pytest.approx(1.0)


# ----------------------------------------------------------------------
# BybitTradFiProvider (experimental) -- symbol mapping deve usar o override
# ----------------------------------------------------------------------
def test_bybit_tradfi_provider_uses_symbol_override() -> None:
    """XAUUSD deve virar 'XAUUSD+' antes de ir pro client -- nunca símbolo cru."""
    fake_client = _FakeBybitClient(kline_rows=[_bybit_raw_row(1_700_000_000_000, 2400)])
    provider = BybitTradFiProvider(client=fake_client, mapper=SymbolMapper())

    provider.get_candles("XAUUSD", "5m", limit=1)

    assert fake_client.requested_symbols == ["XAUUSD+"]


def test_bybit_tradfi_provider_supports_only_tradfi_classes() -> None:
    provider = BybitTradFiProvider(client=_FakeBybitClient(), mapper=SymbolMapper())
    assert provider.supports("XAUUSD", "metal") is True
    assert provider.supports("NAS100", "index") is True
    assert provider.supports("BTCUSDT", "crypto") is False


def test_bybit_tradfi_provider_failure_does_not_crash_caller() -> None:
    """Se o endpoint experimental falhar, deve levantar MarketDataError normalmente
    (permitindo que o ProviderRouter trate como falha de provider, não como crash)."""
    provider = BybitTradFiProvider(client=_FakeBybitClient(raise_on_kline=True), mapper=SymbolMapper())
    with pytest.raises(MarketDataError):
        provider.get_candles("XAUUSD", "5m", limit=1)


# ----------------------------------------------------------------------
# BinanceProvider (adapter)
# ----------------------------------------------------------------------
def test_binance_provider_converts_candles() -> None:
    rows = [_binance_raw_row(1_700_000_000_000 + i * 3_600_000, 100 + i) for i in range(5)]
    provider = BinanceProvider(client=_FakeBinanceClient(klines=rows))

    candles = provider.get_candles("BTCUSDT", "1H", limit=5)

    assert len(candles) == 5
    assert candles[0].taker_buy_volume is not None  # Binance expõe esse campo


def test_binance_provider_supports_only_crypto() -> None:
    provider = BinanceProvider(client=_FakeBinanceClient())
    assert provider.supports("BTCUSDT", "crypto") is True
    assert provider.supports("XAUUSD", "metal") is False


def test_binance_provider_raises_market_data_error_on_failure() -> None:
    provider = BinanceProvider(client=_FakeBinanceClient(raise_on_klines=True))
    with pytest.raises(MarketDataError):
        provider.get_candles("XAUUSD", "1H", limit=5)  # símbolo inválido na Binance


def test_binance_provider_quote_has_no_bid_ask() -> None:
    """/ticker/price não expõe bid/ask -- não deve inventar spread."""
    provider = BinanceProvider(client=_FakeBinanceClient())
    quote = provider.get_quote("BTCUSDT")
    assert quote.last_price == 65000.5
    assert quote.bid is None
    assert quote.ask is None
    assert quote.spread is None
