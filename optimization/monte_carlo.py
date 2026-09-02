"""
optimization/monte_carlo.py
==============================

Monte Carlo por bootstrap (Documento 2, seção 14; Documento Master,
seção 32). Função pura -- recebe a lista de PnL % por trade de um
backtest JÁ RODADO (`strategy_dsl`, Fase 1) e reamostra com reposição
`num_simulations` vezes para estimar a DISTRIBUIÇÃO de capital final e
drawdown máximo -- não só o caminho único que o backtest histórico
percorreu.

LIMITAÇÃO declarada: bootstrap por reamostragem assume que os trades
são intercambiáveis (i.i.d.) -- não preserva a ordem cronológica real
nem eventuais correlações seriais (sequências de losses após losses,
mudança de regime no meio da amostra). É uma ferramenta de robustez
("o resultado histórico depende muito da ordem em que os trades
aconteceram?"), não uma previsão do futuro.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    num_simulations: int
    starting_capital: float
    final_capital_percentiles: dict[str, float]
    max_drawdown_pct_percentiles: dict[str, float]
    probability_of_loss: float
    assumptions_note: str

    def to_dict(self) -> dict:
        return {
            "num_simulations": self.num_simulations,
            "starting_capital": round(self.starting_capital, 2),
            "final_capital_percentiles": {k: round(v, 2) for k, v in self.final_capital_percentiles.items()},
            "max_drawdown_pct_percentiles": {k: round(v, 2) for k, v in self.max_drawdown_pct_percentiles.items()},
            "probability_of_loss_pct": round(self.probability_of_loss * 100, 1),
            "assumptions_note": self.assumptions_note,
        }


_ASSUMPTIONS_NOTE = (
    "Bootstrap por reamostragem com reposição -- assume trades intercambiáveis (i.i.d.), "
    "não preserva sequência cronológica real nem correlação serial entre perdas. "
    "Ferramenta de robustez, não previsão do futuro."
)

_PERCENTILES = (5, 25, 50, 75, 95)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def run_monte_carlo(
    trade_pnl_pct: list[float], starting_capital: float, num_simulations: int = 1000, seed: int | None = None
) -> MonteCarloResult:
    """
    Args:
        trade_pnl_pct: PnL de cada trade como % do capital NO MOMENTO
            do trade (ex.: 2.0 = +2%, -1.5 = -1.5%) -- tipicamente
            `net_pnl / capital_at_entry * 100` de cada linha do trade
            log de um backtest (`strategy_dsl`, Fase 1).
        starting_capital: capital inicial para simular a curva de
            equity de cada caminho reamostrado.
        num_simulations: quantos caminhos reamostrados gerar.
        seed: opcional, para reprodutibilidade em testes.

    Raises:
        ValueError: `trade_pnl_pct` vazio (nada para reamostrar) ou
            `num_simulations` <= 0.
    """
    if not trade_pnl_pct:
        raise ValueError("trade_pnl_pct vazio -- nada para reamostrar (rode o backtest primeiro).")
    if num_simulations <= 0:
        raise ValueError("num_simulations precisa ser positivo.")

    rng = random.Random(seed)
    n = len(trade_pnl_pct)

    final_capitals: list[float] = []
    max_drawdowns_pct: list[float] = []
    losses = 0

    for _ in range(num_simulations):
        equity = starting_capital
        peak = starting_capital
        max_dd = 0.0
        for _ in range(n):
            pnl_pct = trade_pnl_pct[rng.randrange(n)]
            equity *= 1 + pnl_pct / 100
            peak = max(peak, equity)
            drawdown_pct = ((peak - equity) / peak * 100) if peak > 0 else 0.0
            max_dd = max(max_dd, drawdown_pct)

        final_capitals.append(equity)
        max_drawdowns_pct.append(max_dd)
        if equity < starting_capital:
            losses += 1

    final_capitals.sort()
    max_drawdowns_pct.sort()

    return MonteCarloResult(
        num_simulations=num_simulations,
        starting_capital=starting_capital,
        final_capital_percentiles={f"p{p}": _percentile(final_capitals, p) for p in _PERCENTILES},
        max_drawdown_pct_percentiles={f"p{p}": _percentile(max_drawdowns_pct, p) for p in _PERCENTILES},
        probability_of_loss=losses / num_simulations,
        assumptions_note=_ASSUMPTIONS_NOTE,
    )
