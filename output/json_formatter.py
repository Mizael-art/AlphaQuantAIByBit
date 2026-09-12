"""
output/json_formatter.py
===========================

Serializa `AnalysisResult` (ver `models.analysis_result`) para uma
string JSON padronizada -- usado pelo CLI (`app.py`) e disponível para
qualquer outro consumidor que precise do mesmo formato fora do
`/analyze` HTTP.
"""

from __future__ import annotations

import json

from models.analysis_result import AnalysisResult


def to_json_string(result: AnalysisResult, *, indent: int = 2) -> str:
    """
    Converte um `AnalysisResult` em JSON pronto para impressão/envio.

    Args:
        result: resultado da análise (`app.run_analysis`).
        indent: indentação do JSON (padrão: 2, legível no CLI).

    Returns:
        String JSON, UTF-8, sem escapar acentos (`ensure_ascii=False`).
    """
    return json.dumps(result.to_dict(), indent=indent, ensure_ascii=False)
