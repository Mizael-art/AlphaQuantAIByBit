"""
tests/test_fundamentals.py
=============================

Testes dos 4 motores de `fundamentals/` (Documento 4, seção 19):
MacroDataProvider, EconomicEventsProvider, TokenUnlockProvider,
CryptoFundamentalsProvider.

Sem rede real: as implementações de referência (FRED, DefiLlama,
CoinGecko) recebem uma sessão HTTP fake via injeção de dependência,
igual ao padrão já usado em `test_bybit_and_binance_providers.py`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from fundamentals.base import FundamentalsUnavailableError
from fundamentals.crypto_fundamentals import CoinGeckoFundamentalsProvider, NullCryptoFundamentalsProvider
from fundamentals.events import NullEconomicEventsProvider, StaticCuratedEventsProvider
from fundamentals.macro import FredMacroProvider, NullMacroProvider
from fundamentals.unlocks import DefiLlamaUnlockProvider, NullTokenUnlockProvider

EVENTS_CALENDAR_PATH = Path(__file__).resolve().parent.parent / "fundamentals" / "data" / "events_calendar.json"


# ----------------------------------------------------------------------
# Fakes de baixo nível (substituem requests.Session real)
# ----------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload: dict, status_ok: bool = True) -> None:
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self) -> None:
        if not self._status_ok:
            import requests

            raise requests.HTTPError("mock HTTP error")

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, payload: dict, status_ok: bool = True) -> None:
        self._payload = payload
        self._status_ok = status_ok
        self.requested_urls: list[str] = []

    def get(self, url: str, params: dict | None = None, timeout: int | None = None) -> _FakeResponse:
        self.requested_urls.append(url)
        return _FakeResponse(self._payload, status_ok=self._status_ok)

    def close(self) -> None:
        pass


# ----------------------------------------------------------------------
# Motor 1: MacroDataProvider
# ----------------------------------------------------------------------
def test_null_macro_provider_raises_on_get_series() -> None:
    provider = NullMacroProvider()
    with pytest.raises(FundamentalsUnavailableError):
        provider.get_series("DFF", date(2026, 1, 1), date(2026, 1, 31))


def test_null_macro_provider_get_latest_returns_none() -> None:
    provider = NullMacroProvider()
    assert provider.get_latest("DFF") is None


def test_fred_macro_provider_requires_api_key() -> None:
    with pytest.raises(FundamentalsUnavailableError):
        FredMacroProvider(api_key="")


def test_fred_macro_provider_parses_observations() -> None:
    payload = {
        "observations": [
            {"date": "2026-06-01", "value": "4.25", "realtime_start": "2026-06-02"},
            {"date": "2026-07-01", "value": ".", "realtime_start": "2026-07-02"},  # sem dado -- deve ser ignorado
            {"date": "2026-08-01", "value": "4.50", "realtime_start": "2026-08-02"},
        ]
    }
    session = _FakeSession(payload)
    provider = FredMacroProvider(api_key="fake-key", session=session)

    points = provider.get_series("DFF", date(2026, 1, 1), date(2026, 12, 31))

    assert len(points) == 2  # o ponto "." foi descartado
    assert points[0].value == 4.25
    assert points[0].observed_at == datetime(2026, 6, 2, tzinfo=timezone.utc)
    assert points[1].value == 4.50
    assert session.requested_urls  # confirma que passou pela sessão fake, não pela rede real


def test_fred_macro_provider_get_latest_respects_point_in_time() -> None:
    payload = {
        "observations": [
            {"date": "2026-06-01", "value": "4.25", "realtime_start": "2026-06-02"},
            {"date": "2026-08-01", "value": "4.50", "realtime_start": "2026-08-02"},
        ]
    }
    provider = FredMacroProvider(api_key="fake-key", session=_FakeSession(payload))

    # as_of ANTES da publicação de agosto -- não deve enxergar o valor de agosto ainda.
    as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
    latest = provider.get_latest("DFF", as_of=as_of)

    assert latest is not None
    assert latest.value == 4.25  # o ponto de agosto (observed_at 08/ago) ainda não existia em 01/jul.


# ----------------------------------------------------------------------
# Motor 2: EconomicEventsProvider
# ----------------------------------------------------------------------
def test_null_events_provider_raises() -> None:
    provider = NullEconomicEventsProvider()
    with pytest.raises(FundamentalsUnavailableError):
        provider.get_events(date(2026, 1, 1), date(2026, 12, 31))


def test_static_curated_events_provider_missing_file_raises() -> None:
    with pytest.raises(FundamentalsUnavailableError):
        StaticCuratedEventsProvider("/path/que/nao/existe.json")


def test_static_curated_events_provider_loads_shipped_calendar() -> None:
    """Integra com o arquivo real entregue no projeto -- garante que o
    seed de FOMC 2026 está no formato esperado e é carregável."""
    provider = StaticCuratedEventsProvider(EVENTS_CALENDAR_PATH)

    events = provider.get_events(date(2026, 1, 1), date(2026, 12, 31))

    assert len(events) == 3
    assert all(e.category == "interest_rate" for e in events)
    assert [e.scheduled_at.date() for e in events] == [date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)]


def test_static_curated_events_provider_filters_by_importance_and_range() -> None:
    provider = StaticCuratedEventsProvider(EVENTS_CALENDAR_PATH)

    events_in_q4 = provider.get_events(date(2026, 10, 1), date(2026, 12, 31))
    assert len(events_in_q4) == 2

    events_none = provider.get_events(date(2026, 1, 1), date(2026, 1, 31))
    assert events_none == []


def test_static_curated_events_provider_point_in_time() -> None:
    """Nenhum evento deve vazar antes de seu `observed_at` (anúncio do calendário)."""
    provider = StaticCuratedEventsProvider(EVENTS_CALENDAR_PATH)

    as_of_before_announcement = datetime(2024, 1, 1, tzinfo=timezone.utc)
    events = provider.get_events(date(2026, 1, 1), date(2026, 12, 31), as_of=as_of_before_announcement)

    assert events == []


# ----------------------------------------------------------------------
# Motor 3: TokenUnlockProvider
# ----------------------------------------------------------------------
def test_null_unlock_provider_raises() -> None:
    provider = NullTokenUnlockProvider()
    with pytest.raises(FundamentalsUnavailableError):
        provider.get_upcoming_unlocks("ARBUSDT", date(2026, 1, 1), date(2026, 12, 31))


def test_defillama_unlock_provider_unmapped_symbol_raises() -> None:
    provider = DefiLlamaUnlockProvider(symbol_to_slug={}, session=_FakeSession({}))
    with pytest.raises(FundamentalsUnavailableError):
        provider.get_upcoming_unlocks("ARBUSDT", date(2026, 1, 1), date(2026, 12, 31))


def test_defillama_unlock_provider_parses_events() -> None:
    future_ts = int(datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp())
    payload = {
        "events": [
            {"timestamp": future_ts, "noOfTokens": [1_000_000.0], "category": "insiders"},
        ]
    }
    provider = DefiLlamaUnlockProvider(
        symbol_to_slug={"ARBUSDT": "arbitrum"},
        session=_FakeSession(payload),
    )

    unlocks = provider.get_upcoming_unlocks("ARBUSDT", date(2026, 1, 1), date(2026, 12, 31))

    assert len(unlocks) == 1
    assert unlocks[0].amount_tokens == 1_000_000.0
    assert unlocks[0].symbol == "ARBUSDT"
    assert unlocks[0].source == "defillama"


# ----------------------------------------------------------------------
# Motor 4: CryptoFundamentalsProvider
# ----------------------------------------------------------------------
def test_null_fundamentals_provider_raises() -> None:
    provider = NullCryptoFundamentalsProvider()
    with pytest.raises(FundamentalsUnavailableError):
        provider.get_fundamentals("BTCUSDT")


def test_coingecko_provider_unmapped_symbol_raises() -> None:
    provider = CoinGeckoFundamentalsProvider(symbol_to_coingecko_id={}, session=_FakeSession({}))
    with pytest.raises(FundamentalsUnavailableError):
        provider.get_fundamentals("BTCUSDT")


def test_coingecko_provider_parses_market_data() -> None:
    payload = {
        "categories": ["Smart Contract Platform"],
        "market_data": {
            "market_cap": {"usd": 2_000_000_000_000.0},
            "circulating_supply": 19_800_000.0,
            "total_supply": 21_000_000.0,
            "max_supply": 21_000_000.0,
            "fully_diluted_valuation": {"usd": 2_100_000_000_000.0},
        },
    }
    provider = CoinGeckoFundamentalsProvider(
        symbol_to_coingecko_id={"BTCUSDT": "bitcoin"},
        session=_FakeSession(payload),
    )

    fundamentals = provider.get_fundamentals("BTCUSDT")

    assert fundamentals is not None
    assert fundamentals.market_cap_usd == 2_000_000_000_000.0
    assert fundamentals.max_supply == 21_000_000.0
    assert fundamentals.category == "Smart Contract Platform"
    assert fundamentals.source == "coingecko"
