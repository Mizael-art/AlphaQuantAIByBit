"""
tests/test_okx_and_bitget_providers.py
=========================================

Testes dos providers OKX e Bitget com clientes de baixo nível
mockados via injeção de dependência -- sem rede.
"""

from __future__ import annotations

import pytest

from providers.base import MarketDataError
from providers.bitget_provider import BitgetProvider
from providers.okx_provider import OKXProvider, _to_okx_inst_id


class _FakeOKXClient:
    def __init__(self, rows: list[list[str]] | None = None, raise_on_candles: bool = False) -> None:
        self._rows = rows or []
        self._raise = raise_on_candles
        self.requested_inst_ids: list[str] = []

    def get_candles(self, inst_id, bar, limit=300, after=None):
        self.requested_inst_ids.append(inst_id)
        if self._raise:
            from providers.okx_client import OKXAPIError
            raise OKXAPIError("símbolo inválido")
        return self._rows

    def get_ticker(self, inst_id):
        return {"last": "2400.5", "bidPx": "2400.0", "askPx": "2401.0"}

    def close(self):
        pass


class _FakeBitgetClient:
    def __init__(self, rows: list[list[str]] | None = None, raise_on_candles: bool = False) -> None:
        self._rows = rows or []
        self._raise = raise_on_candles

    def get_candles(self, symbol, granularity, limit=200, end_time=None):
        if self._raise:
            from providers.bitget_client import BitgetAPIError
            raise BitgetAPIError("símbolo inválido")
        return self._rows

    def get_ticker(self, symbol):
        return {"lastPr": "2400.5", "bidPr": "2400.0", "askPr": "2401.0"}

    def close(self):
        pass


def _okx_row(ts_ms: int, price: float) -> list[str]:
    return [str(ts_ms), str(price), str(price + 1), str(price - 1), str(price + 0.5), "10.5", "1000", "1000", "1"]


def _bitget_row(ts_ms: int, price: float) -> list[str]:
    return [str(ts_ms), str(price), str(price + 1), str(price - 1), str(price + 0.5), "10.5", "1000", "1000"]


def test_okx_inst_id_conversion() -> None:
    assert _to_okx_inst_id("BTCUSDT") == "BTC-USDT"
    assert _to_okx_inst_id("TRXUSDT") == "TRX-USDT"


def test_okx_inst_id_conversion_unrecognized_raises() -> None:
    with pytest.raises(ValueError):
        _to_okx_inst_id("NOTASYMBOL")


def test_okx_provider_converts_and_reverses_candles() -> None:
    rows = [_okx_row(1_700_000_000_000 + i * 3_600_000, 100 + i) for i in reversed(range(5))]  # OKX: mais recente primeiro
    client = _FakeOKXClient(rows=rows)
    provider = OKXProvider(client=client)

    candles = provider.get_candles("BTCUSDT", "1H", limit=5)

    assert len(candles) == 5
    assert candles[0].open_time < candles[-1].open_time  # invertido para cronológico
    assert client.requested_inst_ids == ["BTC-USDT"]


def test_okx_provider_supports_only_crypto() -> None:
    provider = OKXProvider(client=_FakeOKXClient())
    assert provider.supports("BTCUSDT", "crypto") is True
    assert provider.supports("XAUUSD", "metal") is False


def test_okx_provider_raises_market_data_error() -> None:
    provider = OKXProvider(client=_FakeOKXClient(raise_on_candles=True))
    with pytest.raises(MarketDataError):
        provider.get_candles("BTCUSDT", "1H", limit=5)


def test_okx_provider_quote() -> None:
    provider = OKXProvider(client=_FakeOKXClient())
    quote = provider.get_quote("ETHUSDT")
    assert quote.last_price == 2400.5
    assert quote.spread == pytest.approx(1.0)


def test_bitget_provider_converts_and_sorts_candles() -> None:
    rows = [_bitget_row(1_700_000_000_000 + i * 3_600_000, 100 + i) for i in range(5)]  # já ascendente
    provider = BitgetProvider(client=_FakeBitgetClient(rows=rows))

    candles = provider.get_candles("BTCUSDT", "1H", limit=5)

    assert len(candles) == 5
    assert candles[0].open_time < candles[-1].open_time


def test_bitget_provider_supports_only_crypto() -> None:
    provider = BitgetProvider(client=_FakeBitgetClient())
    assert provider.supports("BTCUSDT", "crypto") is True
    assert provider.supports("NAS100", "index") is False


def test_bitget_provider_raises_market_data_error() -> None:
    provider = BitgetProvider(client=_FakeBitgetClient(raise_on_candles=True))
    with pytest.raises(MarketDataError):
        provider.get_candles("BTCUSDT", "1H", limit=5)


def test_bitget_provider_quote() -> None:
    provider = BitgetProvider(client=_FakeBitgetClient())
    quote = provider.get_quote("BTCUSDT")
    assert quote.last_price == 2400.5
    assert quote.bid == 2400.0
    assert quote.ask == 2401.0
