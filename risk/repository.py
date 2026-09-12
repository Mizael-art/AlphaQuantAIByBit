"""
risk/repository.py
=====================

I/O do Risk Engine sobre `Session` do SQLAlchemy -- consulta estado da
conta, soma PnL realizado por janela (dia/semana/mês), soma open risk,
registra/fecha posições. `risk/engine.py` nunca importa isto
diretamente (só o endpoint em `server.py` orquestra os dois).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from persistence.models import AccountState, OpenPositionRecord, RiskEvent
from risk.engine import AccountRiskState, RiskLimits

_DEFAULT_ACCOUNT_ID = "default"


def get_or_create_account(session: Session, account_id: str = _DEFAULT_ACCOUNT_ID, starting_capital: float | None = None) -> AccountState:
    account = session.get(AccountState, account_id)
    if account is not None:
        return account

    if starting_capital is None:
        raise ValueError(
            f"Conta '{account_id}' ainda não existe -- informe starting_capital para criá-la "
            "(o Risk Engine nunca assume capital inicial, mesma regra do backtest -- Documento 1, seção 8)."
        )
    account = AccountState(account_id=account_id, starting_capital=starting_capital, current_capital=starting_capital)
    session.add(account)
    session.flush()
    return account


def _sum_realized_pnl_since(session: Session, account_id: str, since: datetime) -> float:
    stmt = select(RiskEvent).where(RiskEvent.account_id == account_id, RiskEvent.closed_at >= since)
    events = session.execute(stmt).scalars().all()
    return sum(e.pnl_pct for e in events)


def _sum_open_risk(session: Session, account_id: str) -> float:
    stmt = select(OpenPositionRecord).where(OpenPositionRecord.account_id == account_id)
    positions = session.execute(stmt).scalars().all()
    return sum(p.risk_pct for p in positions)


def _has_correlated_open_position(session: Session, account_id: str, correlation_group: str | None) -> bool:
    if correlation_group is None:
        return False
    stmt = select(OpenPositionRecord).where(
        OpenPositionRecord.account_id == account_id, OpenPositionRecord.correlation_group == correlation_group
    )
    return session.execute(stmt).scalars().first() is not None


def build_risk_state(session: Session, account: AccountState, correlation_group: str | None, now: datetime | None = None) -> AccountRiskState:
    now = now or datetime.now(timezone.utc)
    day_start = now - timedelta(hours=24)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    return AccountRiskState(
        current_capital=account.current_capital,
        realized_pnl_today_pct=_sum_realized_pnl_since(session, account.account_id, day_start),
        realized_pnl_week_pct=_sum_realized_pnl_since(session, account.account_id, week_start),
        realized_pnl_month_pct=_sum_realized_pnl_since(session, account.account_id, month_start),
        open_risk_pct=_sum_open_risk(session, account.account_id),
        correlated_open_position_exists=_has_correlated_open_position(session, account.account_id, correlation_group),
    )


def build_risk_limits(account: AccountState) -> RiskLimits:
    return RiskLimits(
        max_risk_per_trade_pct=account.max_risk_per_trade_pct,
        daily_loss_limit_pct=account.daily_loss_limit_pct,
        weekly_loss_limit_pct=account.weekly_loss_limit_pct,
        monthly_drawdown_limit_pct=account.monthly_drawdown_limit_pct,
        max_open_risk_pct=account.max_open_risk_pct,
    )


def open_position(
    session: Session,
    account_id: str,
    asset: str,
    direction: str,
    risk_pct: float,
    correlation_group: str | None = None,
    setup_id: int | None = None,
) -> OpenPositionRecord:
    record = OpenPositionRecord(
        account_id=account_id, asset=asset, direction=direction, risk_pct=risk_pct,
        correlation_group=correlation_group, setup_id=setup_id,
    )
    session.add(record)
    session.flush()
    return record


def close_position(session: Session, account_id: str, position_id: int, pnl_pct: float) -> RiskEvent:
    """
    Remove a posição de `open_positions`, registra o resultado em
    `risk_events` (alimenta os limites diário/semanal/mensal) e ajusta
    `current_capital` da conta.

    Raises:
        ValueError: posição não encontrada (ou não pertence a esta conta).
    """
    position = session.get(OpenPositionRecord, position_id)
    if position is None or position.account_id != account_id:
        raise ValueError(f"Posição {position_id} não encontrada para a conta '{account_id}'.")

    event = RiskEvent(
        account_id=account_id, asset=position.asset, direction=position.direction,
        risk_pct=position.risk_pct, pnl_pct=pnl_pct,
    )
    session.add(event)

    account = get_or_create_account(session, account_id)
    account.current_capital = account.current_capital * (1 + pnl_pct / 100)

    session.delete(position)
    session.flush()
    return event


def list_open_positions(session: Session, account_id: str = _DEFAULT_ACCOUNT_ID) -> list[OpenPositionRecord]:
    stmt = select(OpenPositionRecord).where(OpenPositionRecord.account_id == account_id)
    return list(session.execute(stmt).scalars().all())
