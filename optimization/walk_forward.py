"""
optimization/walk_forward.py
===============================

Walk-Forward (Documento 1, seção 16; Documento Master, seção 31).
Reaproveita `strategy_dsl.executor.run_generic_backtest` (Fase 1) --
não recalcula simulação, só orquestra múltiplas janelas e agrega.

Mesma convenção já estabelecida no projeto para módulos de
integração com rede (`discovery/engine.py`, `learning/reconstruction.py`):
não coberto por teste de unidade além de smoke test com provider fake;
a agregação de métricas em si é testável isoladamente
(`_aggregate_metric`, testada via o smoke test).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backtest.history_fetcher import HistoryFetcher
from strategy_dsl.errors import StrategyDslError
from strategy_dsl.executor import run_generic_backtest


@dataclass(frozen=True, slots=True)
class WindowResult:
    start: datetime
    end: datetime
    trades_count: int
    performance: dict | None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "trades_count": self.trades_count,
            "performance": self.performance,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    windows: list[WindowResult]
    stability: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"windows": [w.to_dict() for w in self.windows], "stability": self.stability}


def _aggregate_metric(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "stdev": None, "min": None, "max": None}
    return {
        "mean": round(statistics.mean(values), 4),
        "median": round(statistics.median(values), 4),
        "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def run_walk_forward(
    schema: dict,
    windows: list[tuple[datetime, datetime]],
    history_fetcher: HistoryFetcher,
    min_candles: int = 30,
) -> WalkForwardResult:
    """
    Args:
        schema: schema da estratégia genérica (Documento 1, seção 2) --
            o MESMO schema roda em todas as janelas (walk-forward aqui
            valida ESTABILIDADE de uma estratégia já definida; escolher
            parâmetros diferentes por janela seria parameter sweep, não
            walk-forward -- Documento 1, seção 15, "nunca otimizar
            usando o período out-of-sample").
        windows: lista de (start, end) -- cada uma é uma janela de
            teste independente. Definir as janelas (tamanho, se rolante
            ou expansível) é responsabilidade de quem chama; este
            módulo só executa e agrega.

    Returns:
        `WalkForwardResult` com o resultado de cada janela +
        estabilidade (média/mediana/desvio padrão de expectancy_r,
        profit_factor e win_rate entre as janelas que tiveram trades).
    """
    results: list[WindowResult] = []

    for start, end in windows:
        try:
            report = run_generic_backtest(schema, history_fetcher, start, end, min_candles)
        except StrategyDslError as exc:
            results.append(WindowResult(start, end, 0, None, error=exc.to_dict().get("message", str(exc))))
            continue

        results.append(WindowResult(start, end, report["trades_count"], report["performance"]))

    expectancies = [w.performance["expectancy_r"] for w in results if w.performance]
    profit_factors = [w.performance["profit_factor"] for w in results if w.performance and w.performance["profit_factor"] is not None]
    win_rates = [w.performance["win_rate"] for w in results if w.performance]

    stability = {
        "windows_with_trades": len(expectancies),
        "windows_total": len(results),
        "expectancy_r": _aggregate_metric(expectancies),
        "profit_factor": _aggregate_metric(profit_factors),
        "win_rate": _aggregate_metric(win_rates),
        "note": (
            "Estabilidade entre janelas -- desvio padrão alto relativo à média indica que o "
            "resultado depende muito do período escolhido, não é uma estratégia robusta a "
            "diferentes condições de mercado."
        ),
    }

    return WalkForwardResult(windows=results, stability=stability)
