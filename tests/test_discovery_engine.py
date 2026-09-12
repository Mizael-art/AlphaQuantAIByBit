"""
tests/test_discovery_engine.py
=================================

Teste de integração do Discovery Engine com um `MarketDataProvider`
fake (sem rede) -- mesmo padrão de `tests/test_market_data_facade.py`.
Não valida números específicos (isso já é coberto pelos testes puros
de `regime`/`scoring`/`playbook`/`discovery.correlation`) -- valida que
o pipeline inteiro roda ponta a ponta e produz um shape consistente.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.market_data import MarketData
from discovery.engine import scan_opportunities
from models.candle import Candle
from providers.base import MarketDataProvider, Quote
from providers.router import ProviderRouter


def _candles(n: int, pattern: str) -> list[Candle]:
    """`pattern`: 'up' (tendência de alta constante) ou 'flat' (lateral com ruído pequeno)."""
    now = datetime.now(timezone.utc)
    delta = timedelta(hours=1)
    candles = []
    price = 100.0
    for i in range(n):
        open_time = now - delta * (n - i)
        if pattern == "up":
            price += 0.15
            o, c = price - 0.15, price
        else:
            # Lateral com um pequeno seno determinístico -- nunca sobe/desce de forma consistente.
            offset = 0.5 * (1 if i % 4 < 2 else -1)
            o, c = price, price + offset
        h, l = max(o, c) + 0.3, min(o, c) - 0.3
        candles.append(Candle(open_time=open_time, open=o, high=h, low=l, close=c, volume=100.0, close_time=open_time + delta))
    return candles


class _FakeProvider(MarketDataProvider):
    """Provider fake -- candles variam por símbolo (BTCUSDT/ETHUSDT em alta, XYZUSDT lateral)."""

    name = "bybit_crypto"

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class == "crypto"

    def get_candles(self, canonical_symbol: str, timeframe: str, limit: int) -> list[Candle]:
        pattern = "flat" if canonical_symbol.startswith("XYZ") else "up"
        return _candles(max(limit, 210), pattern)

    def get_quote(self, canonical_symbol: str) -> Quote:
        return Quote(canonical_symbol=canonical_symbol, provider=self.name, last_price=150.0, bid=None, ask=None, spread=None)


def _fake_market_data() -> MarketData:
    router = ProviderRouter(providers=[_FakeProvider()])
    return MarketData(router=router)


def test_scan_opportunities_runs_end_to_end_and_returns_expected_shape() -> None:
    result = scan_opportunities(
        symbols=["ETHUSDT", "XYZUSDT"],
        btc_symbol="BTCUSDT",
        direction=None,
        timeframe="1H",
        top_n=5,
        market_data=_fake_market_data(),
    )

    assert "opportunities" in result
    assert "no_edge" in result
    assert "btc_regime" in result
    assert isinstance(result["opportunities"], list)
    assert isinstance(result["no_edge"], list)
    # Todo símbolo pedido deve aparecer em algum lugar -- como oportunidade OU como no_edge/erro.
    covered = {o["symbol"] for o in result["opportunities"]} | {n["symbol"] for n in result["no_edge"]} | set(result["errors"])
    assert covered == {"ETHUSDT", "XYZUSDT"}


def test_scan_opportunities_ranks_by_overall_score_descending() -> None:
    result = scan_opportunities(
        symbols=["ETHUSDT", "XYZUSDT"],
        btc_symbol="BTCUSDT",
        direction="long",
        timeframe="1H",
        top_n=10,
        market_data=_fake_market_data(),
    )
    scores = [o["overall_opportunity_score"] for o in result["opportunities"]]
    assert scores == sorted(scores, reverse=True)


def test_scan_opportunities_respects_top_n() -> None:
    result = scan_opportunities(
        symbols=["ETHUSDT", "XYZUSDT"],
        btc_symbol="BTCUSDT",
        timeframe="1H",
        top_n=1,
        market_data=_fake_market_data(),
    )
    assert len(result["opportunities"]) <= 1
