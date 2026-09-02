"""
output
======

Formatação final de `AnalysisResult` (single-timeframe, `app.py`)
para JSON. O `MarketSnapshot` multi-timeframe (`snapshot/`) tem seu
próprio `to_dict()` e não passa por este pacote -- `output/` existe
para manter compatibilidade com o endpoint `/analyze` legado.
"""

from output.json_formatter import to_json_string

__all__ = ["to_json_string"]
