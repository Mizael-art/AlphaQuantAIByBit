"""
backtest
========

Motor de backtest histórico.

Pipeline: `HistoryFetcher` (paginação de histórico longo) ->
`BacktestSimulator` (execução bar-a-bar de uma `Strategy`, sem
lookahead) -> `calculate_performance` (Win Rate, Profit Factor,
Expectância, MAE/MFE, Drawdown).

Ainda não expõe endpoint HTTP -- falta decidir/confirmar com o
usuário o formato final de "estratégia" antes de expor isso como
action do GPT.
"""

from backtest.costs import ZERO_COST, CostModel
from backtest.history_fetcher import HistoryFetchError, HistoryFetcher, HistoryResult
from backtest.performance import PerformanceReport, calculate_performance
from backtest.simulator import BacktestSimulator, Trade
from backtest.strategy import Signal, Strategy

__all__ = [
    "HistoryFetcher",
    "HistoryResult",
    "HistoryFetchError",
    "Strategy",
    "Signal",
    "BacktestSimulator",
    "Trade",
    "CostModel",
    "ZERO_COST",
    "PerformanceReport",
    "calculate_performance",
]

