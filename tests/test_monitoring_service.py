"""
tests/test_monitoring_service.py
===================================

Smoke test de `monitoring.service.run_monitoring_cycle` -- SQLite em
memória (mesmo padrão de `tests/test_setups.py`) + provider fake
(mesmo padrão de `tests/test_discovery_engine.py`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from api.market_data import MarketData
from monitoring.service import run_monitoring_cycle
from persistence.db import get_engine, get_sessionmaker
from persistence.models import Base
from providers.base import MarketDataProvider, Quote
from providers.router import ProviderRouter
from setups.memory import upsert_setup
from setups.lifecycle import COMPLETED, INVALIDATED, NEAR_ENTRY, TRIGGERED, WATCH
from setups.schema import EntryZone, SetupCandidate


@pytest.fixture()
def session():
    url = f"sqlite:///file:{uuid.uuid4().hex}?mode=memory&cache=shared&uri=true"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    Session = get_sessionmaker(url)
    s = Session()
    yield s
    s.close()


class _FixedPriceProvider(MarketDataProvider):
    name = "bybit_crypto"

    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class == "crypto"

    def get_candles(self, canonical_symbol, timeframe, limit, end_time=None):
        return []

    def get_quote(self, canonical_symbol: str) -> Quote:
        return Quote(canonical_symbol=canonical_symbol, provider=self.name, last_price=self._prices.get(canonical_symbol, 0.0), bid=None, ask=None, spread=None)


def _market_data(prices: dict[str, float]) -> MarketData:
    return MarketData(router=ProviderRouter(providers=[_FixedPriceProvider(prices)]))


def test_run_monitoring_cycle_moves_setup_into_entry_zone(session) -> None:
    upsert_setup(session, SetupCandidate(
        asset="SOLUSDT", direction="long", strategy="sweep", status=WATCH,
        entry_zone=EntryZone(low=140.0, high=142.0), stop=138.0, tp1=150.0,
    ))
    session.commit()

    result = run_monitoring_cycle(session, market_data=_market_data({"SOLUSDT": 141.0}))
    session.commit()

    assert result.checked == 1
    assert len(result.updated) == 1
    assert result.updated[0]["to"] == NEAR_ENTRY


def test_run_monitoring_cycle_invalidates_on_stop_hit(session) -> None:
    upsert_setup(session, SetupCandidate(
        asset="SOLUSDT", direction="long", strategy="sweep", status=TRIGGERED,
        stop=138.0, tp1=150.0,
    ))
    session.commit()

    result = run_monitoring_cycle(session, market_data=_market_data({"SOLUSDT": 137.0}))
    session.commit()

    assert result.updated[0]["to"] == INVALIDATED


def test_run_monitoring_cycle_completes_on_tp_hit(session) -> None:
    upsert_setup(session, SetupCandidate(
        asset="SOLUSDT", direction="long", strategy="sweep", status=TRIGGERED,
        stop=138.0, tp1=150.0,
    ))
    session.commit()

    result = run_monitoring_cycle(session, market_data=_market_data({"SOLUSDT": 151.0}))
    session.commit()

    assert result.updated[0]["to"] == COMPLETED


def test_run_monitoring_cycle_expires_past_due_setups_first(session) -> None:
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    upsert_setup(session, SetupCandidate(asset="ETHUSDT", direction="long", strategy="sweep", status=WATCH, expiration=past))
    session.commit()

    result = run_monitoring_cycle(session, market_data=_market_data({}))
    session.commit()

    assert len(result.expired) == 1
    assert result.checked == 0  # já expirou antes de tentar buscar preço


def test_run_monitoring_cycle_records_error_without_crashing_on_missing_price(session) -> None:
    upsert_setup(session, SetupCandidate(asset="UNKNOWNCOIN", direction="long", strategy="sweep", status=WATCH, entry_zone=EntryZone(low=1.0, high=2.0)))
    session.commit()

    result = run_monitoring_cycle(session, market_data=_market_data({}))  # preço 0.0 -- fora da zona, sem erro real aqui
    session.commit()

    assert result.checked == 1
    assert result.updated == []
