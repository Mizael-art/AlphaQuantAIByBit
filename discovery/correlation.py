"""
discovery/correlation.py
===========================

Correlated Exposure Engine (Documento 2, seção 15/20; Documento Master,
seção 15). Separado do ranking (Documento Master seção 20: "Primeiro
RANKING, depois CORRELATION FILTER") -- este módulo só decide quais
oportunidades já rankeadas são redundantes entre si, nunca participa
do cálculo do score individual.
"""

from __future__ import annotations

import pandas as pd


def compute_return_correlation(returns_by_symbol: dict[str, pd.Series]) -> pd.DataFrame:
    """Matriz de correlação de Pearson entre os retornos período-a-período de cada símbolo (mesmo índice/timeframe)."""
    return pd.DataFrame(returns_by_symbol).corr()


def flag_correlated_duplicates(
    ranked_symbols: list[str], correlation_matrix: pd.DataFrame, threshold: float = 0.85
) -> dict[str, str | None]:
    """
    Args:
        ranked_symbols: símbolos já ordenados por score (melhor primeiro)
            -- a ordem importa: o de score mais alto de cada cluster
            correlacionado é sempre o que "sobrevive" sem penalidade.
        correlation_matrix: saída de `compute_return_correlation`.
        threshold: correlação acima da qual dois ativos são tratados
            como "a mesma aposta" (Documento Master, seção 15, exemplo:
            BTC/ETH/SOL/LINK short simultâneos).

    Returns:
        dict símbolo -> símbolo de score mais alto com quem está
        correlacionado (`None` se o símbolo não é redundante com nada
        de rank melhor -- ou seja, "sobrevive" sem penalidade).
    """
    kept: list[str] = []
    correlated_with: dict[str, str | None] = {}

    for symbol in ranked_symbols:
        redundant_with = None
        for kept_symbol in kept:
            if symbol in correlation_matrix.index and kept_symbol in correlation_matrix.columns:
                corr = correlation_matrix.loc[symbol, kept_symbol]
                if pd.notna(corr) and abs(corr) >= threshold:
                    redundant_with = kept_symbol
                    break
        correlated_with[symbol] = redundant_with
        if redundant_with is None:
            kept.append(symbol)

    return correlated_with
