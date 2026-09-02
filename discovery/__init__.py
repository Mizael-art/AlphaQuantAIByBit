"""
discovery
=========

Discovery/Ranking Engine (Fase 3 do Plano de Evolução). Orquestra
`regime/`, `playbook/` e `scoring/` sobre dados reais (`api.market_data`
+ `app.run_analysis`) para produzir um ranking de oportunidades.

`correlation.py` é puro e testado por unidade; `engine.py` é a camada
de integração com rede (mesma convenção de `scanner/screener.py`, não
coberta por teste de unidade -- ver docstring do módulo).
"""

from discovery.correlation import compute_return_correlation, flag_correlated_duplicates
from discovery.engine import OpportunityResult, scan_opportunities

__all__ = ["OpportunityResult", "scan_opportunities", "compute_return_correlation", "flag_correlated_duplicates"]
