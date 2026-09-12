"""
tests/test_backtest_endpoint.py
==================================

Testes do endpoint HTTP `/backtest` (`server.py`) -- o que faltava
para o GPT conseguir rodar um backtest via Action (o motor
`backtest/` já existia, mas não tinha nenhum endpoint exposto).

Sem rede real: injeta um `ProviderRouter` com um provider fake no
lugar de `build_default_router` -- mesmo padrão de dependency
injection já usado no resto do projeto (`HistoryFetcher(router=...)`).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import server
from models.candle import Candle
from providers.base import MarketDataProvider, Quote
from providers.router import ProviderRouter

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _oscillating_candles(n: int) -> list[Candle]:
    """Preço oscilante (seno) -- garante múltiplos cruzamentos de SMA, ao contrário de uma tendência monotônica."""
    candles = []
    for i in range(n):
        base = 200 + 20 * math.sin(i / 15.0)
        open_ = base - 0.2
        close = base
        high = max(open_, close) + 0.5
        low = min(open_, close) - 0.5
        candles.append(
            Candle(
                open_time=START + timedelta(hours=i),
                open=open_, high=high, low=low, close=close, volume=1000.0,
                close_time=START + timedelta(hours=i + 1),
            )
        )
    return candles


class _FakeProvider(MarketDataProvider):
    """Nome igual a um provider real (`bybit_crypto`) para ser elegível via `DEFAULT_PROVIDER_PRIORITY`."""

    name = "bybit_crypto"

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return True

    def get_candles(self, canonical_symbol, timeframe, limit, end_time=None):
        if end_time is None:
            return self._candles[-limit:]
        subset = [c for c in self._candles if c.open_time <= end_time]
        return subset[-limit:]

    def get_quote(self, canonical_symbol: str) -> Quote:
        return Quote(
            canonical_symbol=canonical_symbol, provider=self.name,
            last_price=self._candles[-1].close, bid=None, ask=None, spread=None,
        )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    candles = _oscillating_candles(500)
    fake_router = ProviderRouter(providers=[_FakeProvider(candles)])
    monkeypatch.setattr(server, "build_default_router", lambda: fake_router)
    return TestClient(server.app)


def test_backtest_strategies_lists_sma_cross(client: TestClient) -> None:
    response = client.get("/backtest/strategies")
    assert response.status_code == 200
    assert "sma_cross" in response.json()["strategies"]


def test_backtest_runs_end_to_end_and_produces_trades(client: TestClient) -> None:
    response = client.post(
        "/backtest",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1H",
            "start": START.isoformat(),
            "end": (START + timedelta(hours=500)).isoformat(),
            "strategy": "sma_cross",
            "strategy_params": {"fast_period": 10, "slow_period": 30, "stop_lookback": 5, "reward_risk_ratio": 2.0},
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["meta"]["canonical_symbol"] == "BTCUSDT"
    assert data["trades_count"] > 0
    assert data["performance"] is not None
    assert data["performance"]["total_trades"] == data["trades_count"]
    assert data["performance_note"] is None


def test_backtest_accepts_tradingview_perpetual_symbol_format(client: TestClient) -> None:
    """Regressão: 'CLUSDT.P' (TradingView) precisa resolver para o mesmo ativo que 'CLUSDT'."""
    response = client.post(
        "/backtest",
        json={
            "symbol": "BYBIT:CLUSDT.P",
            "timeframe": "1H",
            "start": START.isoformat(),
            "end": (START + timedelta(hours=500)).isoformat(),
            "strategy": "sma_cross",
        },
    )
    assert response.status_code == 200
    assert response.json()["meta"]["canonical_symbol"] == "CLUSDT"


def test_backtest_unknown_strategy_returns_422(client: TestClient) -> None:
    response = client.post(
        "/backtest",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1H",
            "start": START.isoformat(),
            "strategy": "estrategia_inexistente",
        },
    )
    assert response.status_code == 422


def test_backtest_applies_cost_model(client: TestClient) -> None:
    response = client.post(
        "/backtest",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1H",
            "start": START.isoformat(),
            "end": (START + timedelta(hours=500)).isoformat(),
            "strategy": "sma_cross",
            "cost_model": {"spread_bps": 5.0, "slippage_bps": 2.0, "commission_bps": 1.0},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cost_model"]["is_zero_cost"] is False
    assert data["cost_model"]["spread_bps"] == 5.0


def test_backtest_defaults_to_zero_cost_when_not_informed(client: TestClient) -> None:
    response = client.post(
        "/backtest",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1H",
            "start": START.isoformat(),
            "end": (START + timedelta(hours=500)).isoformat(),
            "strategy": "sma_cross",
        },
    )
    assert response.status_code == 200
    assert response.json()["cost_model"]["is_zero_cost"] is True


def test_backtest_invalid_date_range_returns_422(client: TestClient) -> None:
    response = client.post(
        "/backtest",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1H",
            "start": (START + timedelta(hours=10)).isoformat(),
            "end": START.isoformat(),  # end antes de start
            "strategy": "sma_cross",
        },
    )
    assert response.status_code == 422


def test_backtest_accepts_naive_datetime_without_crashing(client: TestClient) -> None:
    """
    Regressão: o GPT manda datas sem timezone (ex.: "2026-07-01T00:00:00",
    sem "Z"/offset) -- payload real reportado em produção. Sem normalizar
    para UTC, isso comparava datetime naive com Candle.open_time (sempre
    UTC-aware) e estourava TypeError não tratado -> HTTP 500 genérico em
    vez de um erro claro (ou, como aqui, um resultado válido).
    """
    response = client.post(
        "/backtest",
        json={
            "symbol": "SOLUSDT",
            "timeframe": "1H",
            "start": "2026-01-05T00:00:00",  # sem timezone -- exatamente o payload que quebrava
            "end": "2026-01-15T00:00:00",
            "strategy": "sma_cross",
            "cost_model": {"spread_bps": 0, "slippage_bps": 0, "commission_bps": 0},
            "min_candles": 50,
        },
    )
    assert response.status_code == 200
    data = response.json()
    # a data naive deve ter sido normalizada para UTC, não descartada.
    assert data["meta"]["requested_range"][0] == "2026-01-05T00:00:00+00:00"
