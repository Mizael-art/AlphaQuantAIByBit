"""
persistence/models.py
========================

Modelos ORM:

- `SetupRecord` (Fase 2 -- Documento 2, seção 14).
- `AccountState`, `OpenPositionRecord`, `RiskEvent` (Fase 4 -- Risk Engine).
- `SignalRecord` (Fase 5 -- Learning Engine / Signal Feature Database:
  Documento 2, seção 30; Documento Master, seção 27, 30).

`playbooks` (stats persistidas), `backtests` salvos, `market_regimes`
etc. (Documento Master, seção 46) ficam para quando algo realmente os
usar -- criar a tabela antes disso só adicionaria uma migração vazia.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SetupRecord(Base):
    __tablename__ = "setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # "long" | "short"
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False)

    entry_zone_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_zone_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(256), nullable=True)
    stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp1: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp2: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp3: Mapped[float | None] = mapped_column(Float, nullable=True)
    rr: Mapped[float | None] = mapped_column(Float, nullable=True)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: histórico de score ao longo da vida do setup (Documento 2, seção 15:
    #: "Score: 78 -> 83 -> 88") -- lista de {"timestamp": iso, "score": float}.
    score_history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    invalidation: Mapped[str | None] = mapped_column(String(256), nullable=True)
    expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reason_for_change: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        # Documento 2, seção 15 (Setup Memory): não duplicar um setup pro
        # mesmo ativo+direção+estratégia enquanto ele estiver em aberto --
        # a unicidade real (só entre estados não-terminais) é garantida em
        # código (`setups/memory.py`), não pelo banco, porque SQL puro não
        # expressa bem "único apenas quando status IN (...)" de forma
        # portável entre SQLite e Postgres. Este índice só acelera a busca
        # que o `memory.py` já precisa fazer.
        Index("ix_setups_lookup", "asset", "direction", "strategy", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset": self.asset,
            "direction": self.direction,
            "strategy": self.strategy,
            "status": self.status,
            "entry_zone": (
                {"low": self.entry_zone_low, "high": self.entry_zone_high}
                if self.entry_zone_low is not None or self.entry_zone_high is not None
                else None
            ),
            "trigger": self.trigger,
            "stop": self.stop,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "rr": self.rr,
            "score": self.score,
            "score_history": self.score_history,
            "invalidation": self.invalidation,
            "expiration": self.expiration.isoformat() if self.expiration else None,
            "reason_for_change": self.reason_for_change,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status_changed_at": self.status_changed_at.isoformat(),
        }


class AccountState(Base):
    """
    Singleton por `account_id` (Fase 4 -- Risk Engine). Capital e
    limites de risco vivem juntos aqui porque ambos mudam raramente e
    são sempre lidos juntos (`risk/repository.py`) -- evita duas
    consultas onde uma resolve.
    """

    __tablename__ = "account_state"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")

    starting_capital: Mapped[float] = mapped_column(Float, nullable=False)
    current_capital: Mapped[float] = mapped_column(Float, nullable=False)

    #: limites configuráveis (Documento 2, seção 21) -- percentuais (ex.: 1.0 = 1%).
    max_risk_per_trade_pct: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    daily_loss_limit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    weekly_loss_limit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=6.0)
    monthly_drawdown_limit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=12.0)
    max_open_risk_pct: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "starting_capital": self.starting_capital,
            "current_capital": self.current_capital,
            "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "weekly_loss_limit_pct": self.weekly_loss_limit_pct,
            "monthly_drawdown_limit_pct": self.monthly_drawdown_limit_pct,
            "max_open_risk_pct": self.max_open_risk_pct,
            "updated_at": self.updated_at.isoformat(),
        }


class OpenPositionRecord(Base):
    """Posições abertas no momento -- soma de `risk_pct` = Open Risk (Documento Master, seção 21)."""

    __tablename__ = "open_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")

    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    risk_pct: Mapped[float] = mapped_column(Float, nullable=False)
    #: grupo de correlação (Fase 3, `discovery.correlation`) -- opcional,
    #: usado pelo Risk Engine para negar/reduzir uma segunda posição no
    #: mesmo cluster em vez de só emitir uma nota informativa.
    correlation_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    setup_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # referência informativa a SetupRecord.id

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_open_positions_account", "account_id"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset": self.asset,
            "direction": self.direction,
            "risk_pct": self.risk_pct,
            "correlation_group": self.correlation_group,
            "setup_id": self.setup_id,
            "opened_at": self.opened_at.isoformat(),
        }


class RiskEvent(Base):
    """Log de trades encerrados (realizados) -- base para os limites diário/semanal/mensal."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")

    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    risk_pct: Mapped[float] = mapped_column(Float, nullable=False)
    pnl_pct: Mapped[float] = mapped_column(Float, nullable=False)  # % do capital, positivo ou negativo

    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_risk_events_account_closed", "account_id", "closed_at"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset": self.asset,
            "direction": self.direction,
            "risk_pct": self.risk_pct,
            "pnl_pct": self.pnl_pct,
            "closed_at": self.closed_at.isoformat(),
        }


class SignalRecord(Base):
    """
    Sinal externo (call de terceiros) + contexto reconstruído no
    momento em que foi emitido (Documento 2, seção 30). `result`/
    `r_multiple` ficam `None` até o resultado ser conhecido -- um
    sinal registrado sem resultado ainda é útil (entra no Reverse
    Engineering), só não entra nas estatísticas de hipótese até ter
    resultado.
    """

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp1: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp2: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp3: Mapped[float | None] = mapped_column(Float, nullable=True)
    rr: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str] = mapped_column(String(128), nullable=False)  # de onde veio o sinal (grupo/pessoa/canal)
    strategy_guess: Mapped[str | None] = mapped_column(String(64), nullable=True)  # estratégia implícita inferida

    #: contexto reconstruído no momento do sinal (regime, estrutura, bos/choch,
    #: quality/confirmation score) -- ver learning/reconstruction.py. JSON porque
    #: a composição exata do contexto pode evoluir sem exigir migração de schema.
    reconstructed_context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    result: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "win" | "loss" | "breakeven" | None
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    execution_quality: Mapped[str | None] = mapped_column(String(256), nullable=True)

    signal_quality_label: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ver learning/classification.py

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_signals_asset_strategy", "asset", "strategy_guess"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset": self.asset,
            "direction": self.direction,
            "timeframe": self.timeframe,
            "signal_time": self.signal_time.isoformat(),
            "entry": self.entry,
            "stop": self.stop,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "rr": self.rr,
            "source": self.source,
            "strategy_guess": self.strategy_guess,
            "reconstructed_context": self.reconstructed_context,
            "result": self.result,
            "r_multiple": self.r_multiple,
            "execution_quality": self.execution_quality,
            "signal_quality_label": self.signal_quality_label,
            "created_at": self.created_at.isoformat(),
        }


class ScanSnapshot(Base):
    """
    Última execução do scan contínuo de fundo (`scanner/background_loop.py`).

    Existe para desacoplar o scan (lento, minutos mesmo otimizado para
    um universo de 700+ ativos) do ciclo de request/response de uma
    GPT Action (timeout curto, tipicamente ~45s). O loop de fundo
    escreve aqui a cada ciclo completo; o endpoint `GET /scan/latest`
    só LÊ essa linha -- nunca dispara um scan novo na hora, então
    responde em milissegundos.

    Uma linha por `scan_key` (permite rodar mais de uma configuração
    de scan em paralelo no futuro, ex. universos ou timeframes
    diferentes, sem qualquer migração) -- `scan_key` é sempre
    sobrescrito (upsert), nunca acumula histórico; para histórico de
    sinais já existe `SignalRecord`.
    """

    __tablename__ = "scan_snapshots"

    scan_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    #: JSON completo de `ScanResult.to_dict()`/`UniverseScanResult.to_dict()`.
    #: `None` quando o ciclo mais recente terminou em erro (ver `error`).
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    #: mensagem de erro do ciclo mais recente, se o scan falhou por
    #: inteiro (ex.: Bybit fora do ar). O snapshot ANTERIOR bem-sucedido
    #: não é apagado nesse caso -- ver `persistence/scan_snapshot.py`.
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    #: incrementado a cada ciclo completo (sucesso ou erro) -- serve
    #: pro chamador perceber se o loop de fundo travou (o número para
    #: de subir) mesmo que `finished_at` pareça razoável.
    cycle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        return {
            "scan_key": self.scan_key,
            "result": self.result_json,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "cycle_count": self.cycle_count,
        }
