"""
optimization
============

Optimization + Robustness + Portfolio Intelligence (Fase 8 do Plano de
Evolucao -- Documento 1, secoes 15-17; Documento 2, secao 14/32;
Documento Master, secoes 31-32, 38).

- monte_carlo.py -- bootstrap sobre trades ja simulados (puro, testado).
- portfolio.py -- selecao gulosa da melhor combinacao de trades (puro, testado).
- walk_forward.py -- valida estabilidade de UMA estrategia entre janelas (rede real, smoke-tested).
- parameter_sweep.py -- busca de parametros com aviso de overfitting sempre presente (rede real, smoke-tested).
"""

from optimization.monte_carlo import MonteCarloResult, run_monte_carlo
from optimization.parameter_sweep import ParameterSweepReport, SweepResult, run_parameter_sweep
from optimization.portfolio import PortfolioSelection, select_best_combination
from optimization.walk_forward import WalkForwardResult, WindowResult, run_walk_forward

__all__ = [
    "run_monte_carlo", "MonteCarloResult",
    "select_best_combination", "PortfolioSelection",
    "run_walk_forward", "WalkForwardResult", "WindowResult",
    "run_parameter_sweep", "ParameterSweepReport", "SweepResult",
]
