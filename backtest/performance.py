"""
backtest/performance.py
==========================

Agrega uma lista de `Trade` (resultado do `BacktestSimulator`) em
métricas de performance — os mesmos conceitos definidos no arquivo
09+23 das instruções do GPT (Win Rate, Payoff, Profit Factor,
Expectância, MAE/MFE, Drawdown), agora calculados de verdade a partir
de simulação histórica, não de checklist.

Este módulo NÃO decide se a amostra é estatisticamente suficiente
(30/100/300 trades) — isso é responsabilidade de quem interpreta o
resultado (a instrução do GPT já faz essa checagem). Aqui só entra
número calculado corretamente; a interpretação de confiança fica a
cargo da camada que já existe pra isso.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from backtest.simulator import Trade


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    total_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    avg_r: float
    median_r: float
    expectancy_r: float
    profit_factor: float | None  # None quando não há perdas (divisão por zero evitada, não fabricada)
    payoff_ratio: float | None   # avg win / avg loss, None quando não há perdas
    max_drawdown_r: float
    avg_mae_r: float
    avg_mfe_r: float
    best_trade_r: float
    worst_trade_r: float
    exit_reason_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "breakeven": self.breakeven,
            "win_rate": round(self.win_rate, 4),
            "avg_r": round(self.avg_r, 4),
            "median_r": round(self.median_r, 4),
            "expectancy_r": round(self.expectancy_r, 4),
            "profit_factor": round(self.profit_factor, 4) if self.profit_factor is not None else None,
            "payoff_ratio": round(self.payoff_ratio, 4) if self.payoff_ratio is not None else None,
            "max_drawdown_r": round(self.max_drawdown_r, 4),
            "avg_mae_r": round(self.avg_mae_r, 4),
            "avg_mfe_r": round(self.avg_mfe_r, 4),
            "best_trade_r": round(self.best_trade_r, 4),
            "worst_trade_r": round(self.worst_trade_r, 4),
            "exit_reason_counts": self.exit_reason_counts,
        }


def calculate_performance(trades: list[Trade]) -> PerformanceReport:
    """
    Calcula o `PerformanceReport` a partir de uma lista de `Trade`.

    Raises:
        ValueError: lista vazia (não faz sentido "estatística de 0 trades" —
            forçar o chamador a tratar esse caso explicitamente, em vez
            de devolver zeros que parecem um resultado válido).
    """
    if not trades:
        raise ValueError("Nenhum trade para calcular performance — a estratégia não gerou nenhum sinal válido no período.")

    r_values = [t.r_multiple for t in trades]
    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r < 0]
    breakeven = [r for r in r_values if r == 0]

    win_rate = len(wins) / len(trades)
    avg_r = statistics.mean(r_values)
    median_r = statistics.median(r_values)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = abs(statistics.mean(losses)) if losses else 0.0
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else None

    # Expectância: valor esperado por trade, em R -- combina win rate e payoff.
    expectancy_r = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    max_drawdown_r = _max_drawdown_r(r_values)

    exit_reason_counts: dict[str, int] = {}
    for t in trades:
        exit_reason_counts[t.exit_reason] = exit_reason_counts.get(t.exit_reason, 0) + 1

    return PerformanceReport(
        total_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        breakeven=len(breakeven),
        win_rate=win_rate,
        avg_r=avg_r,
        median_r=median_r,
        expectancy_r=expectancy_r,
        profit_factor=profit_factor,
        payoff_ratio=payoff_ratio,
        max_drawdown_r=max_drawdown_r,
        avg_mae_r=statistics.mean(t.mae_r for t in trades),
        avg_mfe_r=statistics.mean(t.mfe_r for t in trades),
        best_trade_r=max(r_values),
        worst_trade_r=min(r_values),
        exit_reason_counts=exit_reason_counts,
    )


def _max_drawdown_r(r_values: list[float]) -> float:
    """
    Máximo drawdown da curva de capital acumulada, em unidades de R
    (assume risco fixo de 1R por trade — position sizing real é
    responsabilidade do Capital Allocation Engine, fora do escopo
    deste módulo).
    """
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in r_values:
        cumulative += r
        peak = max(peak, cumulative)
        drawdown = peak - cumulative
        max_dd = max(max_dd, drawdown)
    return max_dd
