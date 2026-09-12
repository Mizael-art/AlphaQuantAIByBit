"""
scanner/fast_filter.py
========================

Stage 1 do scan de universo completo (`scanner/screener.scan_universe`):
reduz ~300+ perpétuos USDT da Bybit para um punhado de candidatos ANTES
de rodar a análise completa (indicadores + estrutura + score) em
qualquer um deles.

Custo: ZERO requisições HTTP adicionais -- usa só o
`providers.bybit_universe.TickerSnapshot` já buscado em lote (1 única
chamada para o mercado inteiro). Isso é o que torna viável escanear
centenas de ativos em segundos: a Stage 2 (cara, com candles e
indicadores) só roda sobre os `top_n` símbolos que sobrarem daqui.

O que este filtro NÃO faz: não decide se um ativo "tem setup". Isso é
responsabilidade do pipeline completo (Stage 2) e do Quality Filter/
Playbook nas instruções do GPT. Aqui a única pergunta é: "este ativo
tem liquidez e atividade suficiente para valer a pena gastar uma
análise completa nele agora?" -- ativos ilíquidos ou completamente
mortos (sem volume, sem variação) são descartados antes, e ativos com
liquidez + atividade acima da mediana são priorizados.
"""

from __future__ import annotations

from dataclasses import dataclass

from providers.bybit_universe import TickerSnapshot


@dataclass(frozen=True, slots=True)
class FastFilterEntry:
    """Um candidato que passou no pré-filtro, com o motivo do ranking (transparência -- nunca uma caixa-preta)."""

    symbol: str
    last_price: float
    turnover_24h_usdt: float
    price_change_pct_24h: float
    range_pct_24h: float
    activity_score: float


def rank_candidates(
    tickers: dict[str, TickerSnapshot],
    universe: list[str] | None = None,
    top_n: int = 60,
    min_turnover_usdt: float = 3_000_000.0,
) -> list[FastFilterEntry]:
    """
    Filtra por liquidez mínima e rankeia por "atividade" (combinação de
    volatilidade 24h e força do movimento 24h), devolvendo os `top_n`
    símbolos mais promissores para a análise completa da Stage 2.

    Args:
        tickers: snapshot em lote (`get_bulk_ticker_snapshot`).
        universe: se informado, restringe o pré-filtro a este conjunto
            de símbolos (ex.: lista paginada de `instruments-info`).
            Se `None`, usa todos os símbolos presentes em `tickers`.
        top_n: quantos candidatos repassar para a Stage 2.
        min_turnover_usdt: piso de liquidez (turnover nas últimas 24h,
            em USDT) -- ativos abaixo disso são descartados por risco
            de execução (spread largo, slippage), mesmo que o score de
            atividade seja alto.

    Returns:
        Lista ordenada (mais promissor primeiro), já truncada em `top_n`.
    """
    symbols = universe if universe is not None else list(tickers.keys())

    candidates: list[FastFilterEntry] = []
    for symbol in symbols:
        ticker = tickers.get(symbol)
        if ticker is None:
            continue
        if ticker.turnover_24h_usdt < min_turnover_usdt:
            continue

        # Score de atividade: metade volatilidade (amplitude 24h em %),
        # metade força direcional (|variação 24h| em %). Um ativo que só
        # oscilou de lado (range alto, variação líquida baixa) ainda
        # entra -- pode estar em zona de acumulação/distribuição, que é
        # justamente o que setups de reversão/Wyckoff procuram. Um
        # ativo morto (range baixo E variação baixa) fica no fim da fila.
        activity_score = (ticker.range_pct_24h * 0.5) + (abs(ticker.price_change_pct_24h) * 0.5)

        candidates.append(
            FastFilterEntry(
                symbol=symbol,
                last_price=ticker.last_price,
                turnover_24h_usdt=ticker.turnover_24h_usdt,
                price_change_pct_24h=ticker.price_change_pct_24h,
                range_pct_24h=round(ticker.range_pct_24h, 3),
                activity_score=round(activity_score, 3),
            )
        )

    candidates.sort(key=lambda c: c.activity_score, reverse=True)
    return candidates[:top_n]
