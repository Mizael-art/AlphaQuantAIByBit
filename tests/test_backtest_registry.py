"""
tests/test_backtest_registry.py
==================================

Testes do `backtest/registry.py` -- resolução de estratégia por nome
público (o que a Action `/backtest` recebe do GPT).
"""

from __future__ import annotations

import pytest

from backtest.example_strategies import SmaCrossStrategy
from backtest.registry import StrategyNotRegisteredError, available_strategies, build_strategy


def test_available_strategies_includes_sma_cross() -> None:
    assert "sma_cross" in available_strategies()


def test_build_strategy_returns_correct_type_with_defaults() -> None:
    strategy = build_strategy("sma_cross")
    assert isinstance(strategy, SmaCrossStrategy)
    assert strategy.fast_period == 20  # default do dataclass


def test_build_strategy_applies_custom_params() -> None:
    strategy = build_strategy("sma_cross", {"fast_period": 5, "slow_period": 15})
    assert isinstance(strategy, SmaCrossStrategy)
    assert strategy.fast_period == 5
    assert strategy.slow_period == 15


def test_build_strategy_unknown_name_raises() -> None:
    with pytest.raises(StrategyNotRegisteredError):
        build_strategy("estrategia_que_nao_existe")


def test_build_strategy_invalid_param_raises() -> None:
    with pytest.raises(StrategyNotRegisteredError):
        build_strategy("sma_cross", {"parametro_que_nao_existe": 1})
