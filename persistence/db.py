"""
persistence/db.py
====================

Configuração de engine/sessão do SQLAlchemy (Fase 2 do Plano de
Evolução -- Documento 2/Master, "criar banco de dados").

Produção (Render): variável de ambiente `DATABASE_URL` aponta pro
Postgres gerenciado (`postgresql+psycopg://...`). Local/testes: sem
`DATABASE_URL`, cai para SQLite em arquivo (`alphaquant.db`, no
diretório de trabalho) -- e os testes usam SQLite em memória via
`get_engine(url="sqlite:///:memory:")` explicitamente, nunca tocando
o arquivo local.

Nenhum código de negócio (em `setups/`) importa `sqlalchemy`
diretamente fora deste módulo e de `persistence/models.py` -- mantém
a opção de trocar de ORM/driver sem espalhar a dependência pelo
projeto.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from persistence.models import Base

_DEFAULT_LOCAL_URL = "sqlite:///alphaquant.db"


def _normalize_url(url: str) -> str:
    """
    O Render fornece a connection string do Postgres gerenciado como
    `postgres://...` ou `postgresql://...` (sem dialeto/driver
    explícito) -- o SQLAlchemy exige o driver na URL. Este projeto usa
    `psycopg` (v3, ver requirements.txt), não `psycopg2`.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@lru_cache(maxsize=8)
def get_engine(url: str | None = None) -> Engine:
    """
    `lru_cache` por `url` -- cada URL distinta (produção, dev local,
    `sqlite:///:memory:` de um teste) recebe seu próprio engine/pool,
    sem recriar conexões a cada chamada.
    """
    resolved_url = _normalize_url(url or os.environ.get("DATABASE_URL") or _DEFAULT_LOCAL_URL)
    connect_args = {"check_same_thread": False} if resolved_url.startswith("sqlite") else {}
    engine = create_engine(resolved_url, connect_args=connect_args, future=True)
    Base.metadata.create_all(engine)
    return engine


def get_sessionmaker(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False, future=True)


@contextmanager
def session_scope(url: str | None = None):
    """Context manager padrão: commit em sucesso, rollback em exceção."""
    session = get_sessionmaker(url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
