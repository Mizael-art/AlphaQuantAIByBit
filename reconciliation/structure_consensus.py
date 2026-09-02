"""
reconciliation/structure_consensus.py
========================================

Structure Consensus Engine (Documento 4, seções 5-9 e 15-17; Documento
6, itens 3-4).

Diferente do `CrossExchangeReconciliationEngine` (que compara só
preço/candle bruto), este motor roda a análise de ESTRUTURA e SMC de
forma TOTALMENTE INDEPENDENTE em cada exchange -- cada exchange busca
seus próprios candles e roda `analyze_market_structure`, liquidity
sweeps, FVGs, Order Blocks e Equal Highs/Lows sobre a SUA série -- e só
depois compara os resultados.

Perguntas que este motor responde (Documento 4, seção 5-8):
    "BOS = TRUE em quantas exchanges?"
    "Esse liquidity sweep foi confirmado pelo mercado ou é isolado?"
    "Essa FVG/Order Block é uma zona universal ou específica de uma exchange?"

Princípios (Documento 6, seção 8) -- todos aplicados aqui:
    - não inventar dados
    - não esconder conflitos (resultado por exchange SEMPRE preservado)
    - não misturar instrumentos diferentes
    - não tratar uma exchange como verdade universal
    - não transformar evento isolado em confirmação forte
    - preservar auditabilidade
    - reduzir confidence quando os dados forem insuficientes
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from models.candle import Candle
from providers.base import MarketDataError, MarketDataProvider
from reconciliation.cross_exchange import NoExchangeAvailableError
from smc.equal_highs_lows import EqualLevel, find_equal_highs_lows
from smc.fair_value_gaps import FVGZone, find_fair_value_gaps
from smc.liquidity_sweeps import LiquiditySweep, find_liquidity_sweeps
from smc.order_blocks import OrderBlock, find_order_blocks
from structure.market_structure import MarketStructureResult, analyze_market_structure
from symbols.mapper import SymbolMapper
from validation.data_quality import DataQualityError, validate_candles

logger = logging.getLogger("alphaquant.reconciliation.structure_consensus")

Confidence = Literal["HIGH", "MODERATE", "LOW", "INSUFFICIENT"]

# Quantos candles mais recentes contam como "janela de evento recente"
# ao comparar sweeps entre exchanges. Exchanges não fecham candle no
# mesmo milissegundo exato -- comparar só o ÚLTIMO candle seria frágil
# demais (ver Documento 4, seção 22, teste TRX). Uma janela pequena
# ainda distingue "aconteceu agora" de "aconteceu há muito tempo".
RECENT_EVENT_WINDOW = 3

# Tolerância de sobreposição de preço (%) para considerar que uma zona
# (FVG ou Order Block) vista em exchanges diferentes é "a mesma zona".
# Mesma lógica/ordem de grandeza da tolerância de wick do
# CrossExchangeReconciliationEngine (Documento 4, seção 12).
ZONE_OVERLAP_TOLERANCE_PCT = 0.25

MIN_CANDLES_FOR_STRUCTURE = 200

# Reaproveita a MESMA exceção do CrossExchangeReconciliationEngine --
# "nenhuma exchange disponível" é o mesmo tipo de falha nos dois
# motores, e quem consome os dois (ex.: `snapshot/`) só precisa
# capturar um tipo.


def _candles_to_dataframe(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame([c.to_dict() for c in candles])
    df["open_time"] = pd.to_datetime(df["open_time"])
    df["close_time"] = pd.to_datetime(df["close_time"])
    return df.set_index("open_time").sort_index()


def _data_quality_score(candles: list[Candle], symbol: str, timeframe: str) -> float:
    """
    Score 0-100 pragmático: reaproveita o `validation.data_quality`
    já usado pelo ProviderRouter em vez de inventar uma segunda régua
    de qualidade. Nunca finge que um dado com problema é perfeito --
    só reduz o score de forma auditável.
    """
    try:
        validate_candles(candles, symbol, timeframe, min_candles=MIN_CANDLES_FOR_STRUCTURE, check_freshness=True)
        return 100.0
    except DataQualityError:
        pass
    try:
        validate_candles(candles, symbol, timeframe, min_candles=MIN_CANDLES_FOR_STRUCTURE, check_freshness=False)
        return 70.0  # passou em tudo, só não está fresh (ex.: mercado com candle atrasado).
    except DataQualityError as exc:
        logger.warning("Data quality reduzida para %s (%s): %s", symbol, timeframe, exc)
        return 40.0  # tem problema real, mas ainda tentamos extrair estrutura -- nunca descartado em silêncio.


@dataclass(frozen=True, slots=True)
class ExchangeStructureView:
    """
    Estrutura/SMC calculados de forma independente para UMA exchange.

    Este objeto NUNCA é descartado depois de calculado o consenso --
    fica sempre disponível em `StructureConsensusResult.exchanges` para
    auditoria (Documento 4, seção 16/17: "de onde veio, qual exchange
    confirmou, qual não confirmou").
    """

    exchange: str
    available: bool
    unavailable_reason: str = ""
    candles_count: int = 0
    data_quality_score: float | None = None
    trend: str | None = None
    hh: bool = False
    hl: bool = False
    lh: bool = False
    ll: bool = False
    bos: bool = False
    choch: bool = False
    recent_sweep_high: bool = False
    recent_sweep_low: bool = False
    fvgs: list[FVGZone] = field(default_factory=list)
    order_blocks: list[OrderBlock] = field(default_factory=list)
    equal_highs: list[EqualLevel] = field(default_factory=list)
    equal_lows: list[EqualLevel] = field(default_factory=list)

    def to_dict(self) -> dict:
        if not self.available:
            return {
                "exchange": self.exchange,
                "available": False,
                "unavailable_reason": self.unavailable_reason,
            }
        return {
            "exchange": self.exchange,
            "available": True,
            "candles_count": self.candles_count,
            "data_quality_score": self.data_quality_score,
            "trend": self.trend,
            "structure": {
                "HH": self.hh, "HL": self.hl, "LH": self.lh, "LL": self.ll,
                "BOS": self.bos, "CHOCH": self.choch,
            },
            "liquidity": {
                "recent_sweep_high": self.recent_sweep_high,
                "recent_sweep_low": self.recent_sweep_low,
            },
            "fair_value_gaps": [z.to_dict() for z in self.fvgs],
            "order_blocks": [ob.to_dict() for ob in self.order_blocks],
            "equal_highs": [e.to_dict() for e in self.equal_highs],
            "equal_lows": [e.to_dict() for e in self.equal_lows],
        }


@dataclass(frozen=True, slots=True)
class BooleanConsensus:
    """Consenso de um atributo booleano de estrutura (ex.: BOS) entre exchanges."""

    agree: int
    total: int
    confidence: Confidence
    agreeing_exchanges: list[str]

    def to_dict(self) -> dict:
        return {
            "agree": self.agree,
            "total": self.total,
            "ratio": round(self.agree / self.total, 4) if self.total else 0.0,
            "confidence": self.confidence,
            "agreeing_exchanges": self.agreeing_exchanges,
        }


@dataclass(frozen=True, slots=True)
class StructureConsensusResult:
    canonical_symbol: str
    asset_class: str
    timeframe: str
    execution_venue: str | None
    exchanges: list[ExchangeStructureView]
    structure_consensus: dict[str, BooleanConsensus]      # HH/HL/LH/LL/BOS/CHOCH
    liquidity_consensus: dict[str, BooleanConsensus]       # sweep_high/sweep_low
    cross_exchange_fvgs: list[dict]
    exchange_specific_fvgs: list[dict]
    cross_exchange_order_blocks: list[dict]
    exchange_specific_order_blocks: list[dict]
    data_quality_avg: float | None
    confidence: Confidence

    def to_dict(self) -> dict:
        return {
            "canonical_symbol": self.canonical_symbol,
            "asset_class": self.asset_class,
            "timeframe": self.timeframe,
            "execution_venue": self.execution_venue,
            "exchanges": [v.to_dict() for v in self.exchanges],
            "structure_consensus": {k: v.to_dict() for k, v in self.structure_consensus.items()},
            "liquidity_consensus": {k: v.to_dict() for k, v in self.liquidity_consensus.items()},
            "fair_value_gaps": {
                "cross_exchange": self.cross_exchange_fvgs,
                "exchange_specific": self.exchange_specific_fvgs,
            },
            "order_blocks": {
                "cross_exchange": self.cross_exchange_order_blocks,
                "exchange_specific": self.exchange_specific_order_blocks,
            },
            "data_quality_avg": round(self.data_quality_avg, 1) if self.data_quality_avg is not None else None,
            "confidence": self.confidence,
        }


class StructureConsensusEngine:
    """
    Exemplo:
        engine = StructureConsensusEngine(
            providers=[BinanceProvider(), BybitCryptoProvider(), OKXProvider(), BitgetProvider()]
        )
        result = engine.get_consensus("TRXUSDT", "15m", execution_venue="bitget")
        result.structure_consensus["BOS"].to_dict()
        # -> {"agree": 3, "total": 4, "confidence": "MODERATE", "agreeing_exchanges": [...]}
    """

    def __init__(self, providers: list[MarketDataProvider], mapper: SymbolMapper | None = None, max_workers: int = 4) -> None:
        self._providers = providers
        self._mapper = mapper or SymbolMapper()
        self._max_workers = max_workers

    def get_consensus(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 300,
        execution_venue: str | None = None,
        min_candles: int = MIN_CANDLES_FOR_STRUCTURE,
    ) -> StructureConsensusResult:
        canonical = self._mapper.resolve(symbol)
        eligible = [p for p in self._providers if p.supports(canonical.canonical_symbol, canonical.asset_class.value)]

        if not eligible:
            raise NoExchangeAvailableError(
                f"Nenhuma exchange registrada suporta asset_class={canonical.asset_class.value} "
                f"para {canonical.canonical_symbol}."
            )

        views: list[ExchangeStructureView] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(
                    self._fetch_view, provider, canonical.canonical_symbol, timeframe, limit, min_candles
                ): provider
                for provider in eligible
            }
            for future in as_completed(futures):
                views.append(future.result())

        # Ordem estável (independente de qual thread terminou primeiro) --
        # importante para reprodutibilidade/auditoria.
        order = {p.name: i for i, p in enumerate(eligible)}
        views.sort(key=lambda v: order.get(v.exchange, 999))

        available_views = [v for v in views if v.available]
        if not available_views:
            raise NoExchangeAvailableError(
                f"Todas as {len(eligible)} exchanges consultadas falharam para "
                f"{canonical.canonical_symbol} ({timeframe}) -- nenhuma estrutura pôde ser calculada."
            )

        structure_consensus = {
            key: self._bool_consensus(available_views, key, len(eligible))
            for key in ("hh", "hl", "lh", "ll", "bos", "choch")
        }
        liquidity_consensus = {
            key: self._bool_consensus(available_views, key, len(eligible))
            for key in ("recent_sweep_high", "recent_sweep_low")
        }

        cross_fvgs, specific_fvgs = self._classify_zones(
            {v.exchange: v.fvgs for v in available_views}
        )
        cross_obs, specific_obs = self._classify_zones(
            {v.exchange: v.order_blocks for v in available_views}
        )

        quality_scores = [v.data_quality_score for v in available_views if v.data_quality_score is not None]
        data_quality_avg = sum(quality_scores) / len(quality_scores) if quality_scores else None

        confidence = self._overall_confidence(
            n_available=len(available_views),
            n_total=len(eligible),
            structure_consensus=structure_consensus,
            data_quality_avg=data_quality_avg,
        )

        return StructureConsensusResult(
            canonical_symbol=canonical.canonical_symbol,
            asset_class=canonical.asset_class.value,
            timeframe=timeframe,
            execution_venue=execution_venue,
            exchanges=views,
            structure_consensus=structure_consensus,
            liquidity_consensus=liquidity_consensus,
            cross_exchange_fvgs=cross_fvgs,
            exchange_specific_fvgs=specific_fvgs,
            cross_exchange_order_blocks=cross_obs,
            exchange_specific_order_blocks=specific_obs,
            data_quality_avg=data_quality_avg,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # POR EXCHANGE
    # ------------------------------------------------------------------
    def _fetch_view(
        self, provider: MarketDataProvider, canonical_symbol: str, timeframe: str, limit: int, min_candles: int
    ) -> ExchangeStructureView:
        try:
            candles = provider.get_candles(canonical_symbol, timeframe, limit)
        except (MarketDataError, ValueError) as exc:
            logger.warning("Exchange %s indisponível para %s (%s): %s", provider.name, canonical_symbol, timeframe, exc)
            return ExchangeStructureView(exchange=provider.name, available=False, unavailable_reason=str(exc))

        if len(candles) < min_candles:
            return ExchangeStructureView(
                exchange=provider.name, available=False,
                unavailable_reason=(
                    f"Candles insuficientes para estrutura confiável: {len(candles)} "
                    f"recebidos, mínimo {min_candles}."
                ),
            )

        quality_score = _data_quality_score(candles, canonical_symbol, timeframe)

        try:
            df = _candles_to_dataframe(candles)
            structure = analyze_market_structure(df)
            sweeps = find_liquidity_sweeps(df)
            fvgs = [z for z in find_fair_value_gaps(df) if not z.mitigated]
            order_blocks = [ob for ob in find_order_blocks(df) if not ob.mitigated]
            equal_highs, equal_lows = find_equal_highs_lows(df)
        except Exception as exc:  # noqa: BLE001 - falha de análise de UMA exchange não pode derrubar as demais.
            logger.warning("Falha ao analisar estrutura de %s para %s (%s): %s", provider.name, canonical_symbol, timeframe, exc)
            return ExchangeStructureView(
                exchange=provider.name, available=False,
                unavailable_reason=f"Falha ao calcular estrutura: {exc}",
            )

        recent_cutoff = df.index[-RECENT_EVENT_WINDOW] if len(df) >= RECENT_EVENT_WINDOW else df.index[0]
        recent_sweep_high = any(s.direction == "sweep_high" and s.candle_time >= recent_cutoff for s in sweeps)
        recent_sweep_low = any(s.direction == "sweep_low" and s.candle_time >= recent_cutoff for s in sweeps)

        return ExchangeStructureView(
            exchange=provider.name,
            available=True,
            candles_count=len(candles),
            data_quality_score=quality_score,
            trend=structure.trend,
            hh=structure.hh, hl=structure.hl, lh=structure.lh, ll=structure.ll,
            bos=structure.bos, choch=structure.choch,
            recent_sweep_high=recent_sweep_high,
            recent_sweep_low=recent_sweep_low,
            fvgs=fvgs[:5],
            order_blocks=order_blocks[:5],
            equal_highs=equal_highs,
            equal_lows=equal_lows,
        )

    # ------------------------------------------------------------------
    # CONSENSO BOOLEANO (BOS, CHOCH, HH/HL/LH/LL, sweeps)
    # ------------------------------------------------------------------
    @staticmethod
    def _bool_consensus(views: list[ExchangeStructureView], attr: str, n_total: int) -> BooleanConsensus:
        agreeing = [v.exchange for v in views if getattr(v, attr)]
        agree = len(agreeing)
        n_available = len(views)

        if n_available == 0:
            confidence: Confidence = "INSUFFICIENT"
        elif n_available == 1:
            # Fonte única -- mesmo que TRUE, é uma leitura não confirmada
            # (Documento 4, seção 5-6: "não transformar evento isolado em confirmação forte").
            confidence = "LOW"
        else:
            ratio = agree / n_available
            if ratio in (0.0, 1.0) and n_available / n_total >= 0.75:
                confidence = "HIGH"
            elif ratio >= 0.5 or (1 - ratio) >= 0.5:
                confidence = "MODERATE"
            else:
                confidence = "LOW"

        return BooleanConsensus(agree=agree, total=n_available, confidence=confidence, agreeing_exchanges=sorted(agreeing))

    # ------------------------------------------------------------------
    # ZONAS (FVG / ORDER BLOCK): cross-exchange vs exchange-specific
    # ------------------------------------------------------------------
    @staticmethod
    def _zones_overlap(a: FVGZone | OrderBlock, b: FVGZone | OrderBlock) -> bool:
        if a.direction != b.direction:
            return False
        # Expande cada zona pela tolerância antes de checar interseção --
        # mesmo princípio de tolerância transparente/auditável do
        # CrossExchangeReconciliationEngine (Documento 4, seção 12).
        mid = (a.top + a.bottom) / 2 or 1.0
        pad = abs(mid) * (ZONE_OVERLAP_TOLERANCE_PCT / 100)
        a_low, a_high = a.bottom - pad, a.top + pad
        b_low, b_high = b.bottom - pad, b.top + pad
        return a_low <= b_high and b_low <= a_high

    @classmethod
    def _classify_zones(cls, zones_by_exchange: dict[str, list]) -> tuple[list[dict], list[dict]]:
        """
        Classifica cada zona (FVG ou Order Block) individual como
        `cross_exchange` (confirmada por >=2 exchanges, sobreposição de
        preço dentro da tolerância) ou `exchange_specific` (Documento 4,
        seção 8) -- SEM descartar nenhuma das duas categorias.
        """
        flat: list[tuple[str, object]] = [
            (exchange, zone) for exchange, zones in zones_by_exchange.items() for zone in zones
        ]

        cross: list[dict] = []
        specific: list[dict] = []

        for exchange_a, zone_a in flat:
            confirmed_by = {exchange_a}
            for exchange_b, zone_b in flat:
                if exchange_b == exchange_a:
                    continue
                if cls._zones_overlap(zone_a, zone_b):
                    confirmed_by.add(exchange_b)

            entry = {"exchange": exchange_a, **zone_a.to_dict(), "confirmed_by": sorted(confirmed_by)}
            (cross if len(confirmed_by) >= 2 else specific).append(entry)

        return cross, specific

    # ------------------------------------------------------------------
    # CONFIANÇA GERAL
    # ------------------------------------------------------------------
    @staticmethod
    def _overall_confidence(
        n_available: int,
        n_total: int,
        structure_consensus: dict[str, BooleanConsensus],
        data_quality_avg: float | None,
    ) -> Confidence:
        if n_available == 0:
            return "INSUFFICIENT"
        if n_available == 1:
            return "LOW"  # fonte única -- não há cruzamento possível, por definição (seção 5-6).

        availability_ratio = n_available / n_total
        # BOS é o evento mais decisivo pro Evidence & Scoring -- pesa mais
        # na confiança geral do que HH/HL/LH/LL isoladamente.
        bos_confidence = structure_consensus["bos"].confidence
        quality_ok = data_quality_avg is None or data_quality_avg >= 70.0

        if availability_ratio >= 0.75 and bos_confidence == "HIGH" and quality_ok:
            return "HIGH"
        if availability_ratio >= 0.5 and bos_confidence in ("HIGH", "MODERATE") and quality_ok:
            return "MODERATE"
        return "LOW"

    def close(self) -> None:
        for provider in self._providers:
            provider.close()
