"""
snapshot/market_snapshot.py
=============================

Orquestrador final: busca múltiplos timeframes (padrão: 15m, 1H, 4H,
1D), monta o `TimeframeSnapshot` de cada um, agrega os dados de
derivativos (uma vez por símbolo) e calcula a confluência
multi-timeframe — produzindo o "Market Snapshot" completo que
substitui os prints de gráfico.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from api.market_data import MarketData
from config import (
    CROSS_EXCHANGE_PRICE_LIMIT,
    CROSS_EXCHANGE_STRUCTURE_LIMIT,
    DEFAULT_EXECUTION_VENUE,
    DEFAULT_SYMBOL,
    ENABLE_CROSS_EXCHANGE,
)
from derivatives.binance_futures_client import BinanceFuturesClient
from derivatives.snapshot import DerivativesSnapshot, build_derivatives_snapshot
from providers import MarketDataProvider, build_reconciliation_providers
from reconciliation.cross_exchange import CrossExchangeReconciliationEngine
from reconciliation.structure_consensus import StructureConsensusEngine
from snapshot.confluence import calculate_confluence
from snapshot.timeframe_snapshot import InsufficientDataError, TimeframeSnapshot, build_timeframe_snapshot
from symbols.mapper import SymbolMapper

DEFAULT_TIMEFRAMES: tuple[str, ...] = ("15m", "1H", "4H", "1D")

# Candles buscados por timeframe: timeframes menores usam mais candles
# para cobrir um histórico comparável em tempo real ao dos maiores.
_CANDLES_PER_TIMEFRAME: dict[str, int] = {
    "15m": 500,
    "30m": 500,
    "1H": 500,
    "4H": 500,
    "1D": 500,
}


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Snapshot de mercado multi-timeframe completo, pronto para o GPT consumir."""

    symbol: str
    price: float
    generated_at: datetime
    timeframes: dict[str, TimeframeSnapshot]
    derivatives: dict[str, Any]
    confluence: dict[str, Any]
    errors: dict[str, str]
    data_sources: dict[str, str] = field(default_factory=dict)
    execution_venue: str | None = None

    def to_dict(self) -> dict[str, Any]:
        # `source`: string única resumida, para compatibilidade com instruções
        # que ainda leem um único provider (ex.: arquivo 16 v11, que assumia
        # "sempre Binance"). Preferir `data_sources` (por timeframe) sempre
        # que precisar de precisão -- `source` vira "mixed" quando os
        # timeframes usaram providers diferentes (crypto com fallback
        # Binance no meio do caminho, por exemplo).
        distinct_providers = set(self.data_sources.values())
        if len(distinct_providers) == 1:
            summarized_source = next(iter(distinct_providers))
        elif len(distinct_providers) > 1:
            summarized_source = "mixed"
        else:
            summarized_source = "unknown"

        return {
            "symbol": self.symbol,
            "price": self.price,
            "meta": {
                "generated_at": self.generated_at.isoformat(),
                "source": summarized_source,
                "data_sources": self.data_sources,
                "timeframes_analyzed": list(self.timeframes.keys()),
                "execution_venue": self.execution_venue,
            },
            "timeframes": {tf: snap.to_dict() for tf, snap in self.timeframes.items()},
            "derivatives": self.derivatives,
            "confluence": self.confluence,
            **({"errors": self.errors} if self.errors else {}),
        }


def build_market_snapshot(
    symbol: str = DEFAULT_SYMBOL,
    timeframes: tuple[str, ...] = DEFAULT_TIMEFRAMES,
    market_data: MarketData | None = None,
    futures_client: BinanceFuturesClient | None = None,
    execution_venue: str | None = DEFAULT_EXECUTION_VENUE,
    enable_cross_exchange: bool = ENABLE_CROSS_EXCHANGE,
    reconciliation_providers: list[MarketDataProvider] | None = None,
) -> MarketSnapshot:
    """
    Constrói o Market Snapshot completo para um símbolo, cobrindo
    todos os timeframes informados + derivativos + confluência.

    Args:
        symbol: par de negociação, ex.: "ETHUSDT".
        timeframes: timeframes a analisar (padrão: 15m, 1H, 4H, 1D).
        market_data: instância opcional de `MarketData` (injeção de
            dependência, útil em testes).
        futures_client: instância opcional de `BinanceFuturesClient`.
        execution_venue: exchange usada como EXECUTION VIEW (Documento
            4, seção 9) nos dois engines de consenso abaixo. Padrão:
            `config.DEFAULT_EXECUTION_VENUE` ("bitget").
        enable_cross_exchange: liga/desliga o consenso multi-exchange
            (preço + estrutura). Desligado, o snapshot volta ao
            comportamento single-source de antes (`ProviderRouter`
            apenas) -- útil em testes/CI que não têm rede, ou se o
            custo/latência de consultar 4 exchanges não compensar num
            contexto específico.
        reconciliation_providers: lista opcional de providers para os
            engines de consenso (injeção de dependência -- testes
            passam providers mockados em vez da factory de rede real).
            Ignorado se `enable_cross_exchange=False`.

    Returns:
        `MarketSnapshot` com todos os timeframes, derivativos, a
        confluência multi-timeframe e (quando habilitado) o consenso
        multi-exchange de preço e estrutura por timeframe.

    Note:
        Se um timeframe específico falhar (ex.: histórico insuficiente
        para um par novo), ele é omitido do resultado e o motivo fica
        registrado em `errors` — a análise dos demais timeframes
        continua normalmente. O mesmo vale, independentemente, para o
        consenso multi-exchange: uma falha ali nunca derruba a análise
        single-source (ver `snapshot.timeframe_snapshot`).
    """
    md = market_data or MarketData()

    price_engine: CrossExchangeReconciliationEngine | None = None
    structure_engine: StructureConsensusEngine | None = None
    if enable_cross_exchange:
        providers = reconciliation_providers if reconciliation_providers is not None else build_reconciliation_providers()
        price_engine = CrossExchangeReconciliationEngine(providers=providers)
        structure_engine = StructureConsensusEngine(providers=providers)

    # Resolve o símbolo uma única vez (mesma normalização usada pelo
    # ProviderRouter internamente) para usar de forma consistente em
    # candles, preço e derivativos — e para decidir se derivativos
    # sequer fazem sentido para esse ativo (só cripto tem).
    canonical = SymbolMapper().resolve(symbol)
    symbol = canonical.canonical_symbol

    current_price = md.get_current_price(symbol)

    timeframe_snapshots: dict[str, TimeframeSnapshot] = {}
    errors: dict[str, str] = {}
    data_sources: dict[str, str] = {}

    try:
        for timeframe in timeframes:
            try:
                limit = _CANDLES_PER_TIMEFRAME.get(timeframe, 500)
                df = md.get_ohlcv_dataframe(symbol=symbol, timeframe=timeframe, limit=limit)
                if md.last_result is not None:
                    data_sources[timeframe] = md.last_result.provider
                timeframe_snapshots[timeframe] = build_timeframe_snapshot(
                    df=df,
                    symbol=symbol,
                    timeframe=timeframe,
                    current_price=current_price,
                    price_consensus_engine=price_engine,
                    structure_consensus_engine=structure_engine,
                    execution_venue=execution_venue,
                    price_consensus_limit=CROSS_EXCHANGE_PRICE_LIMIT,
                    structure_consensus_limit=CROSS_EXCHANGE_STRUCTURE_LIMIT,
                )
            except InsufficientDataError as exc:
                errors[timeframe] = str(exc)
            except Exception as exc:  # noqa: BLE001 - isola falha de 1 timeframe do restante.
                errors[timeframe] = f"Falha ao analisar {timeframe}: {exc}"
    finally:
        # Fecha as sessões HTTP dos providers de reconciliação -- não deixar
        # conexões penduradas mesmo se algum timeframe tiver levantado.
        if price_engine is not None:
            price_engine.close()

    if canonical.asset_class.value == "crypto":
        derivatives_snapshot = build_derivatives_snapshot(symbol, client=futures_client)
    else:
        # Open Interest / Funding / L-S Ratio são conceitos de derivativos
        # cripto (Binance Futures) — não existem para forex/metal/index.
        # Marcado como indisponível de forma explícita, sem tentar a rede à toa.
        derivatives_snapshot = DerivativesSnapshot(
            available=False,
            unavailable_reason=f"Derivativos não aplicáveis para asset_class={canonical.asset_class.value}.",
        )

    trend_by_timeframe = {tf: snap.payload["trend"] for tf, snap in timeframe_snapshots.items()}
    score_by_timeframe = {tf: snap.payload["score"] for tf, snap in timeframe_snapshots.items()}

    if trend_by_timeframe:
        confluence_result = calculate_confluence(trend_by_timeframe, score_by_timeframe).to_dict()
    else:
        confluence_result = {"error": "Nenhum timeframe pôde ser analisado com sucesso."}

    return MarketSnapshot(
        symbol=symbol.upper(),
        price=current_price,
        generated_at=datetime.now(timezone.utc),
        timeframes=timeframe_snapshots,
        derivatives=derivatives_snapshot.to_dict(),
        confluence=confluence_result,
        errors=errors,
        data_sources=data_sources,
        execution_venue=execution_venue,
    )
