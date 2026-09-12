"""
tests/test_risk_repository.py
================================

Testes de `risk/repository.py` (I/O sobre SQLite em memória) --
mesmo padrão de `tests/test_setups.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from persistence.db import get_engine, get_sessionmaker
from persistence.models import Base
from risk.repository import (
    build_risk_limits,
    build_risk_state,
    close_position,
    get_or_create_account,
    list_open_positions,
    open_position,
)


@pytest.fixture()
def session():
    url = f"sqlite:///file:{uuid.uuid4().hex}?mode=memory&cache=shared&uri=true"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    Session = get_sessionmaker(url)
    s = Session()
    yield s
    s.close()


def test_get_or_create_account_requires_starting_capital_for_new_account(session) -> None:
    with pytest.raises(ValueError):
        get_or_create_account(session, "acc1")


def test_get_or_create_account_creates_once_and_reuses(session) -> None:
    first = get_or_create_account(session, "acc1", starting_capital=10_000.0)
    session.commit()
    second = get_or_create_account(session, "acc1", starting_capital=999.0)  # ignorado -- já existe
    assert first.account_id == second.account_id
    assert second.current_capital == 10_000.0


def test_open_and_close_position_updates_capital(session) -> None:
    account = get_or_create_account(session, "acc1", starting_capital=10_000.0)
    session.commit()

    position = open_position(session, "acc1", asset="SOLUSDT", direction="long", risk_pct=1.0)
    session.commit()
    assert position.id is not None

    event = close_position(session, "acc1", position.id, pnl_pct=2.0)  # ganhou 2R equivalente em % de capital
    session.commit()

    assert event.pnl_pct == 2.0
    updated_account = get_or_create_account(session, "acc1")
    assert updated_account.current_capital == pytest.approx(10_200.0)
    assert list_open_positions(session, "acc1") == []


def test_close_position_raises_for_unknown_position(session) -> None:
    get_or_create_account(session, "acc1", starting_capital=10_000.0)
    session.commit()
    with pytest.raises(ValueError):
        close_position(session, "acc1", position_id=9999, pnl_pct=1.0)


def test_build_risk_state_sums_open_risk_and_realized_pnl(session) -> None:
    get_or_create_account(session, "acc1", starting_capital=10_000.0)
    session.commit()

    open_position(session, "acc1", asset="SOLUSDT", direction="long", risk_pct=1.0)
    open_position(session, "acc1", asset="ETHUSDT", direction="long", risk_pct=1.5)
    session.commit()

    account = get_or_create_account(session, "acc1")
    state = build_risk_state(session, account, correlation_group=None)

    assert state.open_risk_pct == pytest.approx(2.5)
    assert state.realized_pnl_today_pct == 0.0


def test_build_risk_state_only_counts_pnl_within_window(session) -> None:
    account = get_or_create_account(session, "acc1", starting_capital=10_000.0)
    session.commit()

    p1 = open_position(session, "acc1", asset="SOLUSDT", direction="long", risk_pct=1.0)
    session.commit()
    close_position(session, "acc1", p1.id, pnl_pct=-1.0)
    session.commit()

    account = get_or_create_account(session, "acc1")
    state_now = build_risk_state(session, account, correlation_group=None, now=datetime.now(timezone.utc))
    assert state_now.realized_pnl_today_pct == pytest.approx(-1.0)

    far_future = datetime.now(timezone.utc) + timedelta(days=10)
    state_future = build_risk_state(session, account, correlation_group=None, now=far_future)
    assert state_future.realized_pnl_today_pct == 0.0  # fora da janela de 24h a partir de `now`


def test_build_risk_state_detects_correlated_open_position(session) -> None:
    get_or_create_account(session, "acc1", starting_capital=10_000.0)
    session.commit()
    open_position(session, "acc1", asset="BTCUSDT", direction="long", risk_pct=1.0, correlation_group="majors")
    session.commit()

    account = get_or_create_account(session, "acc1")
    state_same_cluster = build_risk_state(session, account, correlation_group="majors")
    state_other_cluster = build_risk_state(session, account, correlation_group="defi")

    assert state_same_cluster.correlated_open_position_exists is True
    assert state_other_cluster.correlated_open_position_exists is False


def test_build_risk_limits_reflects_account_config(session) -> None:
    account = get_or_create_account(session, "acc1", starting_capital=10_000.0)
    account.max_risk_per_trade_pct = 2.0
    session.commit()

    limits = build_risk_limits(account)
    assert limits.max_risk_per_trade_pct == 2.0
