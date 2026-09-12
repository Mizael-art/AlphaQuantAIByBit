"""
learning/repository.py
=========================

I/O de `SignalRecord` sobre a `Session` do SQLAlchemy.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from persistence.models import SignalRecord
from learning.schema import ExternalSignalInput, SignalResultUpdate


def create_signal(session: Session, candidate: ExternalSignalInput, reconstructed_context: dict, signal_quality_label: str | None) -> SignalRecord:
    record = SignalRecord(
        asset=candidate.asset,
        direction=candidate.direction,
        timeframe=candidate.timeframe,
        signal_time=candidate.signal_time,
        entry=candidate.entry,
        stop=candidate.stop,
        tp1=candidate.tp1,
        tp2=candidate.tp2,
        tp3=candidate.tp3,
        rr=candidate.rr,
        source=candidate.source,
        strategy_guess=candidate.strategy_guess,
        reconstructed_context=reconstructed_context,
        result=candidate.result,
        r_multiple=candidate.r_multiple,
        execution_quality=candidate.execution_quality,
        signal_quality_label=signal_quality_label,
    )
    session.add(record)
    session.flush()
    return record


def update_signal_result(session: Session, signal_id: int, update: SignalResultUpdate, signal_quality_label: str) -> SignalRecord:
    record = session.get(SignalRecord, signal_id)
    if record is None:
        raise ValueError(f"Sinal {signal_id} não encontrado.")
    record.result = update.result
    record.r_multiple = update.r_multiple
    record.execution_quality = update.execution_quality or record.execution_quality
    record.signal_quality_label = signal_quality_label
    session.flush()
    return record


def list_signals(
    session: Session,
    asset: str | None = None,
    strategy_guess: str | None = None,
    signal_quality_label: str | None = None,
) -> list[SignalRecord]:
    stmt = select(SignalRecord)
    if asset is not None:
        stmt = stmt.where(SignalRecord.asset == asset)
    if strategy_guess is not None:
        stmt = stmt.where(SignalRecord.strategy_guess == strategy_guess)
    if signal_quality_label is not None:
        stmt = stmt.where(SignalRecord.signal_quality_label == signal_quality_label)
    stmt = stmt.order_by(SignalRecord.signal_time.desc())
    return list(session.execute(stmt).scalars().all())


def get_signal(session: Session, signal_id: int) -> SignalRecord | None:
    return session.get(SignalRecord, signal_id)
