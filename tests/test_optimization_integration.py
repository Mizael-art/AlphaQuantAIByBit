"""
tests/test_optimization_integration.py
==========================================

Smoke test de walk_forward e parameter_sweep com provider fake -- mesmo
padrao de tests/test_discovery_engine.py e tests/test_learning_reconstruction.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backtest.history_fetcher import HistoryFetcher
from models.candle import Candle
from optimization.parameter_sweep import run_parameter_sweep
from optimization.walk_forward import run_walk_forward
from providers.base import MarketDataProvider, Quote
from providers.router import ProviderRouter


def _flat_then_trending(flat_n: int, trend_n: int, start: datetime) -> list[Candle]:
    candles = []
    t = start
    price = 100.0
    for _ in range(flat_n):
        candles.append(Candle(open_time=t, open=price, high=price + 0.1, low=price - 0.1, close=price, volume=100.0, close_time=t + timedelta(hours=1)))
        t += timedelta(hours=1)
    for _ in range(trend_n):
        o = price
        c = price + 1.0
        h, l = max(o, c) + 0.2, min(o, c) - 0.2
        candles.append(Candle(open_time=t, open=o, high=h, low=l, close=c, volume=100.0, close_time=t + timedelta(hours=1)))
        price = c
        t += timedelta(hours=1)
    return candles


class _FakeProvider(MarketDataProvider):
    name = "bybit_crypto"

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class == "crypto"

    def get_candles(self, canonical_symbol: str, timeframe: str, limit: int, end_time=None) -> list[Candle]:
        if end_time is None:
            return self._candles[-limit:]
        filtered = [c for c in self._candles if c.open_time <= end_time]
        return filtered[-limit:]

    def get_quote(self, canonical_symbol: str) -> Quote:
        return Quote(canonical_symbol=canonical_symbol, provider=self.name, last_price=150.0, bid=None, ask=None, spread=None)


def _fetcher(candles: list[Candle]) -> HistoryFetcher:
    return HistoryFetcher(router=ProviderRouter(providers=[_FakeProvider(candles)]))


def _sma_cross_schema(**overrides) -> dict:
    base = {
        "name": "sma_cross_sweep_test",
        "market": {"symbols": ["ETHUSDT"], "timeframe": "1h", "exchange": "BINANCE"},
        "direction": "long",
        "indicators": [
            {"id": "FAST", "type": "SMA", "period": 3, "source": "close"},
            {"id": "SLOW", "type": "SMA", "period": 6, "source": "close"},
        ],
        "entry": {"long": ["FAST crosses above SLOW"], "short": []},
        "filters": [],
        "exit": {
            "stop_loss": {"type": "percent", "value": 1.0},
            "take_profit": {"type": "rr", "value": 2.0},
        },
        "execution": {"intrabar_priority": "stop_first"},
        "position_sizing": {"type": "risk_percent", "value": 1.0},
        "costs": {},
        "starting_capital": 10_000.0,
    }
    base.update(overrides)
    return base


def test_walk_forward_runs_multiple_windows_and_aggregates() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_then_trending(15, 80, start)
    fetcher = _fetcher(candles)

    windows = [
        (start, start + timedelta(hours=40)),
        (start + timedelta(hours=40), start + timedelta(hours=95)),
    ]
    result = run_walk_forward(_sma_cross_schema(), windows, fetcher, min_candles=10)

    assert len(result.windows) == 2
    assert "expectancy_r" in result.stability
    assert result.stability["windows_total"] == 2


def test_parameter_sweep_runs_grid_and_flags_overfitting_warning() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_then_trending(15, 80, start)
    fetcher = _fetcher(candles)

    grid = {"exit.take_profit.value": [2.0, 3.0]}
    report = run_parameter_sweep(_sma_cross_schema(), grid, fetcher, start, start + timedelta(hours=95), min_candles=10)

    assert len(report.results) == 2
    assert "overfitting" in report.overfitting_warning.lower() or "espaco pesquisado" in report.overfitting_warning.lower()


def test_parameter_sweep_rejects_grid_above_max_combinations() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = _flat_then_trending(15, 80, start)
    fetcher = _fetcher(candles)

    grid = {"exit.take_profit.value": [2.0, 3.0, 4.0, 5.0]}
    with pytest.raises(ValueError):
        run_parameter_sweep(_sma_cross_schema(), grid, fetcher, start, start + timedelta(hours=95), max_combinations=2)
