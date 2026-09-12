"""
optimization/parameter_sweep.py
==================================

Parameter Sweep (Documento 1, seção 17). Reaproveita
strategy_dsl.executor.run_generic_backtest -- não recalcula simulação.
Mesma convencao de integracao com rede nao coberta por teste de
unidade alem de smoke test (ver walk_forward.py).

Documento 1, secao 17, e explicito: "o motor deve alertar
explicitamente sobre risco de overfitting. Nao declarar o melhor
conjunto como 'melhor estrategia'. Classificar como: melhor resultado
historico dentro do espaco pesquisado." -- este modulo nunca retorna
um "best_strategy", so um "best_result_in_search_space", com o aviso
sempre presente no payload (nao como observacao separada opcional).
"""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backtest.history_fetcher import HistoryFetcher
from strategy_dsl.errors import StrategyDslError
from strategy_dsl.executor import run_generic_backtest

_OVERFITTING_WARNING = (
    "Este e o MELHOR RESULTADO HISTORICO DENTRO DO ESPACO PESQUISADO, nao a 'melhor estrategia' -- "
    "buscar em muitas combinacoes de parametros sobre o mesmo periodo aumenta o risco de overfitting "
    "(Documento 1, secao 17). Validar o resultado escolhido em periodo out-of-sample antes de qualquer uso real."
)


def _set_by_path(schema: dict, path: str, value: Any) -> None:
    """path tipo 'indicators.0.period' ou 'exit.take_profit.value' -- navega dicts/listas por indice numerico."""
    parts = path.split(".")
    node = schema
    for part in parts[:-1]:
        node = node[int(part)] if part.isdigit() else node[part]
    last = parts[-1]
    if last.isdigit():
        node[int(last)] = value
    else:
        node[last] = value


@dataclass(frozen=True, slots=True)
class SweepResult:
    params: dict[str, Any]
    trades_count: int
    performance: dict | None
    error: str | None = None

    def to_dict(self) -> dict:
        return {"params": self.params, "trades_count": self.trades_count, "performance": self.performance, "error": self.error}


@dataclass(frozen=True, slots=True)
class ParameterSweepReport:
    results: list[SweepResult]
    best_result_in_search_space: SweepResult | None
    rank_by: str
    overfitting_warning: str = _OVERFITTING_WARNING

    def to_dict(self) -> dict:
        return {
            "results": [r.to_dict() for r in self.results],
            "best_result_in_search_space": self.best_result_in_search_space.to_dict() if self.best_result_in_search_space else None,
            "rank_by": self.rank_by,
            "overfitting_warning": self.overfitting_warning,
        }


def run_parameter_sweep(
    base_schema: dict,
    param_grid: dict[str, list[Any]],
    history_fetcher: HistoryFetcher,
    start: datetime,
    end: datetime | None,
    rank_by: str = "expectancy_r",
    min_candles: int = 30,
    max_combinations: int = 60,
) -> ParameterSweepReport:
    """
    Args:
        base_schema: schema base (Documento 1, secao 2) -- cada
            combinacao parte de uma copia profunda dele.
        param_grid: dict caminho -> lista de valores (ex.:
            {"indicators.0.period": [10, 20, 30], "exit.take_profit.value": [2, 3, 4]}).
        rank_by: chave de performance usada para ranquear (ex.:
            "expectancy_r", "profit_factor") -- maior e melhor.
        max_combinations: teto de seguranca (evita sweep acidental de
            milhares de combinacoes numa chamada so).

    Raises:
        ValueError: param_grid geraria mais de max_combinations combinacoes.
    """
    keys = list(param_grid.keys())
    value_lists = [param_grid[k] for k in keys]
    combinations = list(itertools.product(*value_lists))

    if len(combinations) > max_combinations:
        raise ValueError(
            f"param_grid geraria {len(combinations)} combinacoes, acima do teto de {max_combinations} "
            "(reduza o grid ou aumente max_combinations explicitamente)."
        )

    results: list[SweepResult] = []
    for combo in combinations:
        params = dict(zip(keys, combo))
        schema = copy.deepcopy(base_schema)
        for path, value in params.items():
            _set_by_path(schema, path, value)

        try:
            report = run_generic_backtest(schema, history_fetcher, start, end, min_candles)
        except StrategyDslError as exc:
            results.append(SweepResult(params, 0, None, error=exc.to_dict().get("message", str(exc))))
            continue

        results.append(SweepResult(params, report["trades_count"], report["performance"]))

    rankable = [r for r in results if r.performance and r.performance.get(rank_by) is not None]
    best = max(rankable, key=lambda r: r.performance[rank_by]) if rankable else None

    return ParameterSweepReport(results=results, best_result_in_search_space=best, rank_by=rank_by)
