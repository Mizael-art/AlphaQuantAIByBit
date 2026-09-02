"""
strategy_dsl/executor.py
===========================

Orquestra o backtest genérico ponta a ponta:

    validar schema -> buscar histórico -> preparar indicadores/regras
    -> simular -> position sizing -> performance -> equity curve
    -> montar relatório final

Documento 1, seção 22 ("validação automática"): nada disso roda
parcialmente -- qualquer falha em qualquer etapa aborta com um erro
estruturado (`StrategyDslError.to_dict()`), nunca um resultado
incompleto.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from pydantic import ValidationError

from backtest.costs import CostModel
from backtest.history_fetcher import HistoryFetcher, HistoryFetchError, HistoryResult
from backtest.performance import calculate_performance
from backtest.simulator import BacktestSimulator
from models.candle import Candle
from providers.base import DataUnavailableError
from strategy_dsl.capabilities import get_schema_capabilities
from strategy_dsl.errors import SchemaValidationError, StrategyDslError
from strategy_dsl.generic_strategy import GenericStrategy
from strategy_dsl.portfolio import build_equity_curve, build_trade_report
from strategy_dsl.schema import GenericStrategySchema


def _sample_quality(trade_count: int) -> str:
    if trade_count < 30:
        return "insufficient"
    if trade_count < 100:
        return "in_validation"
    if trade_count < 300:
        return "moderate_confidence"
    return "high_confidence"


def parse_schema(raw_schema: dict) -> GenericStrategySchema:
    """
    Raises:
        SchemaValidationError: schema estruturalmente inválido --
            nunca tenta "consertar" campos ausentes/incoerentes.
    """
    try:
        return GenericStrategySchema(**raw_schema)
    except ValidationError as exc:
        raise SchemaValidationError(str(exc)) from exc


def run_generic_backtest(
    raw_schema: dict,
    history_fetcher: HistoryFetcher,
    start: datetime,
    end: datetime | None,
    min_candles: int = 50,
) -> dict:
    """
    Executa o backtest genérico completo.

    Returns:
        dict pronto para serialização JSON (mesmo shape retornado pelo
        endpoint `/backtest/generic`).

    Raises:
        StrategyDslError: (ou subclasse) em qualquer etapa de
            validação/execução -- o chamador HTTP decide o status
            code, mas o corpo do erro (`.to_dict()`) já vem pronto
            pra devolver ao cliente sem reformulação.
        HistoryFetchError, DataUnavailableError: erro de dado (não é
            um erro do DSL em si -- o chamador trata separadamente,
            igual já faz `/backtest`).
    """
    schema = parse_schema(raw_schema)

    history: HistoryResult = history_fetcher.fetch(
        symbol=schema.market.symbols[0],
        timeframe=schema.market.timeframe,
        start=start,
        end=end,
        min_candles=min_candles,
    )

    df = _candles_to_df(history.candles)

    strategy = GenericStrategy(schema=schema)
    strategy.prepare(df)

    cost_model = CostModel(
        commission_bps=schema.costs.commission_bps,
        spread_bps=schema.costs.spread_bps,
        slippage_bps=schema.costs.slippage_bps,
    )

    simulator = BacktestSimulator(
        strategy=strategy,
        cost_model=cost_model,
        intrabar_priority=schema.execution.intrabar_priority,
    )
    try:
        trades = simulator.run(history.candles)
    except (ValueError, TypeError) as exc:
        raise StrategyDslError(f"Falha ao simular a estratégia: {exc}") from exc

    result_type = "gross" if cost_model.is_zero_cost else "net"

    if not trades:
        return {
            "meta": history.to_meta_dict(),
            "strategy": {"name": schema.name, "description": schema.description},
            "execution": {
                "intrabar_priority": schema.execution.intrabar_priority,
                "entry_at": schema.execution.entry_at,
            },
            "result_type": result_type,
            "trades_count": 0,
            "rejected_signals_count": len(simulator.rejected_signals),
            "performance": None,
            "performance_note": (
                "A estratégia não gerou nenhum trade válido no período -- sem base "
                "para métricas de performance. Isso não significa que a estratégia "
                "seja ruim, só que as regras de entrada nunca dispararam (ou os sinais "
                "gerados falharam na validação estrutural -- ver rejected_signals_count)."
            ),
            "trade_log": [],
            "equity_curve": None,
            "sample_quality": _sample_quality(0),
        }

    performance = calculate_performance(trades)
    trade_report = build_trade_report(trades, schema)
    equity_curve = build_equity_curve(trade_report, schema.starting_capital or 0.0) if schema.starting_capital else None

    return {
        "meta": history.to_meta_dict(),
        "strategy": {"name": schema.name, "description": schema.description},
        "execution": {
            "intrabar_priority": schema.execution.intrabar_priority,
            "entry_at": schema.execution.entry_at,
        },
        "result_type": result_type,
        "trades_count": len(trades),
        "rejected_signals_count": len(simulator.rejected_signals),
        "performance": performance.to_dict(),
        "sample_quality": _sample_quality(len(trades)),
        "trade_log": [e.to_dict() for e in trade_report],
        "equity_curve": equity_curve,
        "risks": [
            r
            for r in [
                "Backtest histórico não garante desempenho futuro.",
                "Custos, slippage e execução real podem diferir do simulado.",
                None if len(trades) >= 30 else "Amostra abaixo de 30 trades -- insuficiente para validação estatística.",
            ]
            if r is not None
        ],
    }


def _candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame([c.to_dict() for c in candles])
    df["open_time"] = pd.to_datetime(df["open_time"])
    return df.set_index("open_time", drop=False).sort_index()


def schema_capabilities() -> dict:
    return get_schema_capabilities()
