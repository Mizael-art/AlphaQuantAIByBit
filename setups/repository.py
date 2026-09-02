"""
setups/repository.py
=======================

CRUD do `SetupRecord` sobre uma `Session` do SQLAlchemy. Nenhuma regra
de negócio de "criar vs. atualizar" mora aqui -- isso é
`setups/memory.py`. Este módulo só sabe ler/escrever registros.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from persistence.models import SetupRecord
from setups.lifecycle import TERMINAL_STATUSES, validate_transition
from setups.schema import SetupCandidate


def get_open_setup(session: Session, asset: str, direction: str, strategy: str) -> SetupRecord | None:
    """
    "Setup Memory" (Documento 2, seção 15): procura um setup já em
    aberto (status não-terminal) para o mesmo ativo+direção+estratégia
    -- é essa busca que decide se um candidato novo vira um registro
    novo ou uma atualização do existente.
    """
    stmt = (
        select(SetupRecord)
        .where(SetupRecord.asset == asset, SetupRecord.direction == direction, SetupRecord.strategy == strategy)
        .where(SetupRecord.status.not_in(TERMINAL_STATUSES))
        .order_by(SetupRecord.updated_at.desc())
    )
    return session.execute(stmt).scalars().first()


def create_setup(session: Session, candidate: SetupCandidate) -> SetupRecord:
    now = datetime.now(timezone.utc)
    record = SetupRecord(
        asset=candidate.asset,
        direction=candidate.direction,
        strategy=candidate.strategy,
        status=candidate.status,
        entry_zone_low=candidate.entry_zone.low if candidate.entry_zone else None,
        entry_zone_high=candidate.entry_zone.high if candidate.entry_zone else None,
        trigger=candidate.trigger,
        stop=candidate.stop,
        tp1=candidate.tp1,
        tp2=candidate.tp2,
        tp3=candidate.tp3,
        rr=candidate.rr,
        score=candidate.score,
        score_history=([{"timestamp": now.isoformat(), "score": candidate.score}] if candidate.score is not None else []),
        invalidation=candidate.invalidation,
        expiration=candidate.expiration,
        reason_for_change=candidate.reason,
        status_changed_at=now,
    )
    session.add(record)
    session.flush()  # popula record.id sem precisar commitar ainda
    return record


def apply_update(session: Session, record: SetupRecord, candidate: SetupCandidate, reason_note: str) -> SetupRecord:
    """
    Atualiza um `SetupRecord` existente in-place com os dados do novo
    candidato -- nunca cria um segundo registro para o mesmo
    ativo+direção+estratégia enquanto o existente estiver em aberto.
    """
    validate_transition(record.status, candidate.status)

    now = datetime.now(timezone.utc)
    status_changed = record.status != candidate.status

    if candidate.score is not None and candidate.score != record.score:
        record.score_history = [*record.score_history, {"timestamp": now.isoformat(), "score": candidate.score}]
    record.score = candidate.score if candidate.score is not None else record.score

    if candidate.entry_zone is not None:
        record.entry_zone_low = candidate.entry_zone.low
        record.entry_zone_high = candidate.entry_zone.high
    record.trigger = candidate.trigger if candidate.trigger is not None else record.trigger
    record.stop = candidate.stop if candidate.stop is not None else record.stop
    record.tp1 = candidate.tp1 if candidate.tp1 is not None else record.tp1
    record.tp2 = candidate.tp2 if candidate.tp2 is not None else record.tp2
    record.tp3 = candidate.tp3 if candidate.tp3 is not None else record.tp3
    record.rr = candidate.rr if candidate.rr is not None else record.rr
    record.invalidation = candidate.invalidation if candidate.invalidation is not None else record.invalidation
    record.expiration = candidate.expiration if candidate.expiration is not None else record.expiration

    record.status = candidate.status
    record.reason_for_change = reason_note
    if status_changed:
        record.status_changed_at = now

    session.flush()
    return record


def list_setups(
    session: Session,
    asset: str | None = None,
    status_in: list[str] | None = None,
    exclude_terminal: bool = False,
) -> list[SetupRecord]:
    stmt = select(SetupRecord)
    if asset is not None:
        stmt = stmt.where(SetupRecord.asset == asset)
    if status_in is not None:
        stmt = stmt.where(SetupRecord.status.in_(status_in))
    if exclude_terminal:
        stmt = stmt.where(SetupRecord.status.not_in(TERMINAL_STATUSES))
    stmt = stmt.order_by(SetupRecord.updated_at.desc())
    return list(session.execute(stmt).scalars().all())


def get_changed_since(session: Session, since: datetime) -> list[SetupRecord]:
    """Documento Master, seção 14 -- 'o que mudou desde a última análise'."""
    stmt = select(SetupRecord).where(SetupRecord.updated_at >= since).order_by(SetupRecord.updated_at.desc())
    return list(session.execute(stmt).scalars().all())
