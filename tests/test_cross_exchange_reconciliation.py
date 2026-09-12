"""
tests/test_cross_exchange_reconciliation.py
===============================================

Testes do `CrossExchangeReconciliationEngine` -- o cenário central do
Documento 4: TRX/USDT com wick diferente em cada exchange. Providers
mockados, sem rede.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from models.candle import Candle
from providers.base import MarketDataError, MarketDataProvider, Quote
from reconciliation.cross_exchange import CrossExchangeReconciliationEngine, NoExchangeAvailableError


def _candles(n: int, last_close: float, last_high: float, last_low: float) -> list[Candle]:
    """N candles onde só o ÚLTIMO importa pro teste (o resto é padding cronológico)."""
    now = datetime.now(timezone.utc)
    delta = timedelta(minutes=15)
    out = []
    for i in range(n - 1):
        t = now - delta * (n - i)
        out.append(Candle(open_time=t, open=100.0, high=101.0, low=99.0, close=100.0, volume=10.0, close_time=t + delta))
    t = now - delta
    out.append(Candle(open_time=t, open=100.0, high=last_high, low=last_low, close=last_close, volume=10.0, close_time=t + delta))
    return out


class _FakeExchange(MarketDataProvider):
    def __init__(self, name: str, last_close: float, last_high: float, last_low: float, fail: bool = False) -> None:
        self.name = name
        self._close, self._high, self._low = last_close, last_high, last_low
        self._fail = fail

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class == "crypto"

    def get_candles(self, canonical_symbol, timeframe, limit, end_time=None):
        if self._fail:
            raise MarketDataError(f"{self.name} indisponível")
        return _candles(limit, self._close, self._high, self._low)

    def get_quote(self, canonical_symbol: str) -> Quote:
        return Quote(canonical_symbol=canonical_symbol, provider=self.name, last_price=self._close, bid=None, ask=None, spread=None)

    def close(self):
        pass


def test_all_exchanges_agree_gives_high_confidence() -> None:
    exchanges = [
        _FakeExchange("binance", 0.3340, 0.3345, 0.3335),
        _FakeExchange("bybit_crypto", 0.3341, 0.3346, 0.3336),
        _FakeExchange("okx", 0.3339, 0.3344, 0.3334),
        _FakeExchange("bitget", 0.3340, 0.3345, 0.3335),
    ]
    engine = CrossExchangeReconciliationEngine(providers=exchanges)

    result = engine.get_consensus("TRXUSDT", "15m", limit=10)

    assert result.confidence == "HIGH"
    assert result.isolated_wick_exchanges == []
    assert result.wick_high_consensus_score == 100.0


def test_one_exchange_isolated_wick_is_detected() -> None:
    """Cenário exato do Documento 4: Binance mostra high bem maior -- as outras concordam entre si."""
    exchanges = [
        _FakeExchange("binance", 0.3340, 0.3345, 0.3335),   # high normal
        _FakeExchange("bybit_crypto", 0.3339, 0.3339, 0.3334),
        _FakeExchange("okx", 0.3338, 0.3338, 0.3333),
        _FakeExchange("bitget", 0.3339, 0.3339, 0.3334),
    ]
    # força um wick isolado: Binance tem high MUITO acima das outras.
    exchanges[0] = _FakeExchange("binance", 0.3340, 0.3400, 0.3335)  # high 0.34 vs ~0.3338 das outras
    engine = CrossExchangeReconciliationEngine(providers=exchanges)

    result = engine.get_consensus("TRXUSDT", "15m", limit=10)

    assert "binance" in result.isolated_wick_exchanges
    assert result.wick_high_consensus_score < 100.0


def test_consensus_price_is_median_not_mean() -> None:
    # closes: 100, 100, 100, 1000 -- média seria puxada pro outlier, mediana não.
    exchanges = [
        _FakeExchange("binance", 100.0, 101.0, 99.0),
        _FakeExchange("bybit_crypto", 100.0, 101.0, 99.0),
        _FakeExchange("okx", 100.0, 101.0, 99.0),
        _FakeExchange("bitget", 1000.0, 1001.0, 999.0),  # outlier
    ]
    engine = CrossExchangeReconciliationEngine(providers=exchanges)

    result = engine.get_consensus("BTCUSDT", "15m", limit=10)

    assert result.consensus_price == 100.0  # mediana -- não puxada pelo outlier da Bitget
    assert result.price_spread == pytest.approx(900.0)


def test_execution_venue_price_is_separate_from_consensus() -> None:
    exchanges = [
        _FakeExchange("binance", 100.0, 101.0, 99.0),
        _FakeExchange("bitget", 100.5, 101.5, 99.5),
    ]
    engine = CrossExchangeReconciliationEngine(providers=exchanges)

    result = engine.get_consensus("BTCUSDT", "15m", limit=10, execution_venue="bitget")

    assert result.execution_price == 100.5
    assert result.execution_venue == "bitget"
    assert result.consensus_price != result.execution_price  # não confunde os dois conceitos


def test_execution_venue_not_available_returns_none_not_fabricated() -> None:
    exchanges = [_FakeExchange("binance", 100.0, 101.0, 99.0)]
    engine = CrossExchangeReconciliationEngine(providers=exchanges)

    result = engine.get_consensus("BTCUSDT", "15m", limit=10, execution_venue="bitget")

    assert result.execution_price is None  # bitget não estava entre os providers -- não inventa preço


def test_one_exchange_failing_does_not_break_the_others() -> None:
    exchanges = [
        _FakeExchange("binance", 100.0, 101.0, 99.0),
        _FakeExchange("bybit_crypto", 100.0, 101.0, 99.0, fail=True),
        _FakeExchange("okx", 100.1, 101.1, 99.1),
    ]
    engine = CrossExchangeReconciliationEngine(providers=exchanges)

    result = engine.get_consensus("BTCUSDT", "15m", limit=10)

    binance_view = next(v for v in result.exchanges if v.exchange == "binance")
    bybit_view = next(v for v in result.exchanges if v.exchange == "bybit_crypto")
    assert binance_view.available is True
    assert bybit_view.available is False
    assert bybit_view.unavailable_reason  # motivo declarado, nunca omitido


def test_single_exchange_gives_low_confidence_no_crash() -> None:
    exchanges = [_FakeExchange("binance", 100.0, 101.0, 99.0)]
    engine = CrossExchangeReconciliationEngine(providers=exchanges)

    result = engine.get_consensus("BTCUSDT", "15m", limit=10)

    assert result.confidence == "LOW"  # fonte única, sem confirmação cruzada
    assert result.consensus_price == 100.0


def test_all_exchanges_failing_raises_not_silently_empty() -> None:
    exchanges = [
        _FakeExchange("binance", 100.0, 101.0, 99.0, fail=True),
        _FakeExchange("okx", 100.0, 101.0, 99.0, fail=True),
    ]
    engine = CrossExchangeReconciliationEngine(providers=exchanges)

    with pytest.raises(NoExchangeAvailableError):
        engine.get_consensus("BTCUSDT", "15m", limit=10)


def test_no_eligible_exchange_for_asset_class_raises() -> None:
    engine = CrossExchangeReconciliationEngine(providers=[])
    with pytest.raises(NoExchangeAvailableError):
        engine.get_consensus("BTCUSDT", "15m", limit=10)
