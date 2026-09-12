"""
persistence
===========

Camada de persistência (Fase 2 do Plano de Evolução). Postgres em
produção via `DATABASE_URL`, SQLite local/testes por default -- ver
`persistence/db.py`.
"""

from persistence.db import get_engine, get_sessionmaker, session_scope
from persistence.models import (
    AccountState,
    Base,
    OpenPositionRecord,
    RiskEvent,
    ScanSnapshot,
    SetupRecord,
    SignalRecord,
)

__all__ = [
    "get_engine", "get_sessionmaker", "session_scope", "Base",
    "SetupRecord", "AccountState", "OpenPositionRecord", "RiskEvent", "SignalRecord",
    "ScanSnapshot",
]
