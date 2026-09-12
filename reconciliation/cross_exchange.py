"""
reconciliation/cross_exchange.py
===================================

Cross-Exchange Reconciliation Engine.

Consulta VÁRIAS exchanges EM PARALELO (não em fallback/cascata — isso
é o `ProviderRouter`, um componente diferente, com um propósito
diferente) para o mesmo símbolo/timeframe, e produz:

- `consensus_price`: mediana dos últimos closes entre exchanges
  (nunca média simples — ver Documento 4, seção 12).
- `execution_price`: preço na exchange de execução, quando informada
  (nunca confundido com o consenso).
- `price_spread` / `price_spread_pct`: dispersão de preço entre exchanges.
- detecção de WICK ISOLADO: quando o high/low mais recente de uma
  exchange diverge significativamente das demais, que concordam entre
  si — não trata isso automaticamente como sweep confirmado.
- `confidence`: quantas exchanges confirmaram e com que consistência.

Princípios seguidos (Documento 4):
- Nunca usa média simples como preço "verdadeiro" (usa mediana).
- Nunca trata uma exchange como verdade universal.
- Se uma exchange falhar, marca UNAVAILABLE e segue com as demais —
  nunca quebra o sistema inteiro por causa de uma fonte fora do ar.
- Nunca preenche dado ausente por inferência.
"""

from __future__ import annotations

import logging
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Literal

from providers.base import MarketDataError, MarketDataProvider
from symbols.mapper import SymbolMapper

logger = logging.getLogger("alphaquant.reconciliation.cross_exchange")

Confidence = Literal["HIGH", "MODERATE", "LOW", "INSUFFICIENT"]

# Tolerância para considerar que duas exchanges "concordam" sobre um
# high/low (em % do preço) -- acima disso, é discrepância. Valor
# inicial conservador, ajustável com dado real (ver Documento 4,
# seção 57 -- teste de divergência com TRX/USDT).
WICK_AGREEMENT_TOLERANCE_PCT = 0.15


@dataclass(frozen=True, slots=True)
class ExchangeView:
    """O que uma exchange específica está mostrando para o último candle fechado."""

    exchange: str
    available: bool
    last_close: float | None = None
    last_high: float | None = None
    last_low: float | None = None
    candles_count: int = 0
    unavailable_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange,
            "available": self.available,
            "last_close": self.last_close,
            "last_high": self.last_high,
            "last_low": self.last_low,
            "candles_count": self.candles_count,
            **({"unavailable_reason": self.unavailable_reason} if not self.available else {}),
        }


@dataclass(frozen=True, slots=True)
class ConsensusResult:
    canonical_symbol: str
    asset_class: str
    timeframe: str
    consensus_price: float
    execution_price: float | None
    execution_venue: str | None
    price_spread: float
    price_spread_pct: float
    wick_high_consensus_score: float
    wick_low_consensus_score: float
    isolated_wick_exchanges: list[str]
    confidence: Confidence
    exchanges: list[ExchangeView] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "canonical_symbol": self.canonical_symbol,
            "asset_class": self.asset_class,
            "timeframe": self.timeframe,
            "consensus_price": round(self.consensus_price, 8),
            "execution_price": self.execution_price,
            "execution_venue": self.execution_venue,
            "price_spread": round(self.price_spread, 8),
            "price_spread_pct": round(self.price_spread_pct, 4),
            "wick_high_consensus_score": round(self.wick_high_consensus_score, 1),
            "wick_low_consensus_score": round(self.wick_low_consensus_score, 1),
            "isolated_wick_exchanges": self.isolated_wick_exchanges,
            "confidence": self.confidence,
            "exchanges": [e.to_dict() for e in self.exchanges],
        }


class NoExchangeAvailableError(Exception):
    """Nenhuma das exchanges consultadas conseguiu responder -- não fabricamos consenso de zero fontes."""


class CrossExchangeReconciliationEngine:
    """
    Exemplo:
        engine = CrossExchangeReconciliationEngine(
            providers=[BinanceProvider(), BybitCryptoProvider(), OKXProvider(), BitgetProvider()]
        )
        result = engine.get_consensus("TRXUSDT", "15m", execution_venue="bitget")
    """

    def __init__(self, providers: list[MarketDataProvider], mapper: SymbolMapper | None = None, max_workers: int = 4) -> None:
        self._providers = providers
        self._mapper = mapper or SymbolMapper()
        self._max_workers = max_workers

    def get_consensus(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 50,
        execution_venue: str | None = None,
    ) -> ConsensusResult:
        canonical = self._mapper.resolve(symbol)
        eligible = [p for p in self._providers if p.supports(canonical.canonical_symbol, canonical.asset_class.value)]

        if not eligible:
            raise NoExchangeAvailableError(
                f"Nenhuma exchange registrada suporta asset_class={canonical.asset_class.value} "
                f"para {canonical.canonical_symbol}."
            )

        views: list[ExchangeView] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._fetch_view, provider, canonical.canonical_symbol, timeframe, limit): provider
                for provider in eligible
            }
            for future in as_completed(futures):
                views.append(future.result())

        # Ordem estável (não depende da ordem de conclusão das threads) --
        # importante pra reprodutibilidade/auditoria (Documento 4, seção 44/49).
        order = {p.name: i for i, p in enumerate(eligible)}
        views.sort(key=lambda v: order.get(v.exchange, 999))

        available_views = [v for v in views if v.available]
        if not available_views:
            raise NoExchangeAvailableError(
                f"Todas as {len(eligible)} exchanges consultadas falharam para "
                f"{canonical.canonical_symbol} ({timeframe})."
            )

        closes = [v.last_close for v in available_views if v.last_close is not None]
        consensus_price = statistics.median(closes)
        price_spread = max(closes) - min(closes)
        price_spread_pct = (price_spread / consensus_price * 100) if consensus_price else 0.0

        wick_high_score, isolated_high = self._wick_consensus(available_views, side="high")
        wick_low_score, isolated_low = self._wick_consensus(available_views, side="low")
        isolated = sorted(set(isolated_high) | set(isolated_low))

        execution_price = None
        if execution_venue is not None:
            match = next((v for v in available_views if v.exchange == execution_venue), None)
            execution_price = match.last_close if match else None

        confidence = self._confidence(len(available_views), len(eligible), price_spread_pct)

        return ConsensusResult(
            canonical_symbol=canonical.canonical_symbol,
            asset_class=canonical.asset_class.value,
            timeframe=timeframe,
            consensus_price=consensus_price,
            execution_price=execution_price,
            execution_venue=execution_venue,
            price_spread=price_spread,
            price_spread_pct=price_spread_pct,
            wick_high_consensus_score=wick_high_score,
            wick_low_consensus_score=wick_low_score,
            isolated_wick_exchanges=isolated,
            confidence=confidence,
            exchanges=views,
        )

    def _fetch_view(self, provider: MarketDataProvider, canonical_symbol: str, timeframe: str, limit: int) -> ExchangeView:
        try:
            candles = provider.get_candles(canonical_symbol, timeframe, limit)
        except (MarketDataError, ValueError) as exc:
            logger.warning("Exchange %s indisponível para %s (%s): %s", provider.name, canonical_symbol, timeframe, exc)
            return ExchangeView(exchange=provider.name, available=False, unavailable_reason=str(exc))

        if not candles:
            return ExchangeView(exchange=provider.name, available=False, unavailable_reason="Nenhum candle retornado.")

        last = candles[-1]
        return ExchangeView(
            exchange=provider.name, available=True,
            last_close=last.close, last_high=last.high, last_low=last.low,
            candles_count=len(candles),
        )

    def _wick_consensus(self, views: list[ExchangeView], side: str) -> tuple[float, list[str]]:
        """
        Score 0-100: % de exchanges cujo high/low mais recente está
        dentro da tolerância em relação à MEDIANA das demais.
        Retorna também a lista de exchanges "isoladas" (fora da
        tolerância) -- método transparente e auditável, conforme
        exigido no Documento 4, seção 12/14.
        """
        values = [(getattr(v, f"last_{side}"), v.exchange) for v in views if getattr(v, f"last_{side}") is not None]
        if len(values) < 2:
            return 100.0, []  # uma única fonte -- nada pra comparar, não penaliza, mas ver `confidence` geral.

        prices = [p for p, _ in values]
        median_value = statistics.median(prices)
        if median_value == 0:
            return 100.0, []

        agreeing = []
        isolated = []
        for price, exchange in values:
            deviation_pct = abs(price - median_value) / median_value * 100
            if deviation_pct <= WICK_AGREEMENT_TOLERANCE_PCT:
                agreeing.append(exchange)
            else:
                isolated.append(exchange)

        score = (len(agreeing) / len(values)) * 100
        return score, isolated

    def _confidence(self, n_available: int, n_total: int, price_spread_pct: float) -> Confidence:
        if n_available == 0:
            return "INSUFFICIENT"
        if n_available == 1:
            return "LOW"  # fonte única -- sem confirmação cruzada, por definição.
        agreement_ratio = n_available / n_total
        if agreement_ratio >= 0.75 and price_spread_pct <= WICK_AGREEMENT_TOLERANCE_PCT:
            return "HIGH"
        if agreement_ratio >= 0.5:
            return "MODERATE"
        return "LOW"

    def close(self) -> None:
        for provider in self._providers:
            provider.close()
