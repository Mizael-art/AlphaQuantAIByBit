"""
strategy_dsl
============

DSL de estratégia genérica para o backtest (Documento 1 do Plano de
Evolução do AlphaQuant X). Permite descrever qualquer estratégia
quantitativa determinística por schema, sem precisar de código Python
pré-registrado por estratégia (ver `backtest/registry.py` para o
mecanismo antigo, ainda em uso por `/backtest`).

Pipeline: `schema.GenericStrategySchema` (validação) ->
`generic_strategy.GenericStrategy` (interpreta regras/indicadores,
implementa `backtest.strategy.Strategy`) -> reaproveita
`backtest.simulator.BacktestSimulator` -> `portfolio` (position
sizing, trade log, equity curve) -> `executor.run_generic_backtest`
(orquestração ponta a ponta, usado por `POST /backtest/generic`).
"""

from strategy_dsl.capabilities import get_schema_capabilities
from strategy_dsl.errors import (
    InvalidRuleError,
    SchemaValidationError,
    StrategyDslError,
    UnsupportedFunctionError,
    UnsupportedIndicatorError,
    UnsupportedStrategyError,
)
from strategy_dsl.executor import run_generic_backtest, schema_capabilities
from strategy_dsl.generic_strategy import GenericStrategy
from strategy_dsl.schema import GenericStrategySchema

__all__ = [
    "GenericStrategySchema",
    "GenericStrategy",
    "run_generic_backtest",
    "schema_capabilities",
    "get_schema_capabilities",
    "StrategyDslError",
    "UnsupportedIndicatorError",
    "UnsupportedFunctionError",
    "InvalidRuleError",
    "SchemaValidationError",
    "UnsupportedStrategyError",
]
