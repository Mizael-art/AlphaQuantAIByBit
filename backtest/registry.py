"""
backtest/registry.py
=======================

Registro de estratégias disponíveis para o endpoint HTTP `/backtest`.

Por que um registro (ver docstring de `backtest/strategy.py`): o GPT
só envia parâmetros estruturados para uma Action HTTP, nunca código
Python arbitrário — então uma "estratégia" precisa ser identificável
por um nome curto + parâmetros numéricos, resolvida aqui para uma
instância concreta de `Strategy`.

Adicionar uma estratégia nova = adicionar uma entrada no dict
`_REGISTRY` abaixo. Nunca requer tocar em `server.py` nem no
simulador.
"""

from __future__ import annotations

from typing import Any, Callable

from backtest.example_strategies import SmaCrossStrategy
from backtest.strategy import Strategy


class StrategyNotRegisteredError(Exception):
    """Levantada quando o nome/parâmetros de estratégia pedidos são inválidos."""


# nome público (usado na Action) -> factory que constrói a Strategy.
# Aceita tanto a classe diretamente (kwargs = campos do dataclass)
# quanto uma função, se uma estratégia futura precisar de setup mais
# elaborado que um dataclass simples.
_REGISTRY: dict[str, Callable[..., Strategy]] = {
    "sma_cross": SmaCrossStrategy,
}


def available_strategies() -> list[str]:
    """Nomes de estratégia aceitos pelo endpoint `/backtest` (e por `/backtest/strategies`)."""
    return sorted(_REGISTRY)


def build_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    """
    Constrói uma `Strategy` a partir do nome público + parâmetros.

    Args:
        name: chave em `_REGISTRY` (ver `available_strategies()`).
        params: parâmetros da estratégia (ex.: `{"fast_period": 10}`).
            Passados diretamente como kwargs para a factory — nomes
            errados ou fora do intervalo esperado geram
            `StrategyNotRegisteredError` com o motivo, nunca são
            ignorados silenciosamente.

    Raises:
        StrategyNotRegisteredError: nome não registrado, ou parâmetros
            incompatíveis com a estratégia.
    """
    factory = _REGISTRY.get(name)
    if factory is None:
        raise StrategyNotRegisteredError(
            f"Estratégia '{name}' não registrada. Disponíveis: {available_strategies()}."
        )

    params = params or {}
    try:
        return factory(**params)
    except TypeError as exc:
        raise StrategyNotRegisteredError(
            f"Parâmetros inválidos para a estratégia '{name}': {exc}"
        ) from exc
