"""
discovery/engine.py
======================

Orquestração do Discovery/Ranking Engine (Documento 2, seções 4-12, 20;
Documento Master, seções 4-14). Reaproveita `app.run_analysis` (mesmo
pipeline usado por `/snapshot` e `/scan`) para trend/estrutura/score, e
busca candles brutos uma vez a mais por símbolo (via `MarketData`) só
para as métricas que `run_analysis` não expõe (percentil de
volatilidade, largura de Bollinger, retorno para força relativa).

Fluxo por símbolo: regime -> força relativa vs. BTC -> contexto BTC ->
filtro regime-first do Playbook (pula o símbolo se nada for
compatível -- nunca força um match) -> estimativa de entrada/stop/TP a
partir das zonas já calculadas -> Multi-Score. Depois de processar
todos os símbolos: Correlated Exposure Engine sobre os candidatos
rankeados, re-score dos penalizados, corte no `top_n`.

Nota (mesma convenção do `scanner/screener.py` já existente no repo):
esta função de orquestração faz chamadas de rede reais (via
`MarketData`/`run_analysis`) e não é coberta por teste de unidade --
os testes cobrem as peças puras (`regime/`, `scoring/`, `playbook/`,
`discovery/correlation.py`).

LIMITAÇÃO declarada: a estimativa de entrada/stop/TP aqui é um
primeiro corte a partir das zonas de suporte/resistência já calculadas
-- não é o "Trade Plan Generator" completo do Documento Master (seção
17), que fica para uma fase futura. Suficiente para RANQUEAR
oportunidades, não para ser tomado como plano de execução definitivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from api.market_data import MarketData
from app import InsufficientDataError, run_analysis
from indicators.atr import calculate_atr
from indicators.bands_channels import calculate_bollinger_bands
from statistics_.volatility import calculate_percentile_rank
from regime.btc_filter import classify_btc_context
from regime.detector import RegimeResult, detect_regime
from regime.relative_strength import classify_relative_strength
from playbook.library import PlaybookEntry, compatible_playbooks
from scanner.screener import _nearest_zone
from scoring.engine import OpportunityScore, compute_opportunity_score
from discovery.correlation import compute_return_correlation, flag_correlated_duplicates

_RETURN_LOOKBACK_CANDLES = 20
_REGIME_LOOKBACK_PERIOD = 100


@dataclass(frozen=True, slots=True)
class OpportunityResult:
    symbol: str
    direction: str
    playbook: str
    style: str
    regime: str
    btc_context: str | None
    price: float
    entry_zone: tuple[float, float] | None
    stop: float | None
    target: float | None
    rr: float | None
    distance_to_zone_pct: float | None
    score: OpportunityScore
    correlated_with: str | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "playbook": self.playbook,
            "style": self.style,
            "regime": self.regime,
            "btc_context": self.btc_context,
            "price": self.price,
            "entry_zone": {"low": self.entry_zone[0], "high": self.entry_zone[1]} if self.entry_zone else None,
            "stop": self.stop,
            "target": self.target,
            "rr": self.rr,
            "distance_to_zone_pct": self.distance_to_zone_pct,
            "correlated_with": self.correlated_with,
            **self.score.to_dict(),
            "notes": self.notes,
        }


def _asset_regime_and_context(symbol: str, timeframe: str, market_data: MarketData) -> tuple[Any, RegimeResult, float, Any]:
    """Retorna (run_analysis result, RegimeResult, retorno % no lookback, DataFrame OHLCV) para um símbolo/timeframe."""
    result = run_analysis(symbol=symbol, timeframe=timeframe, market_data=market_data)
    df = market_data.get_ohlcv_dataframe(symbol=symbol, timeframe=timeframe)

    lookback = min(_REGIME_LOOKBACK_PERIOD, len(df))
    atr_series = calculate_atr(df, 14)
    vol_percentile = calculate_percentile_rank(atr_series, period=lookback).iloc[-1]

    bb = calculate_bollinger_bands(df, period=20, std_dev=2.0)
    bb_width = (bb.upper - bb.lower) / bb.middle
    bb_width_percentile = calculate_percentile_rank(bb_width, period=lookback).iloc[-1]

    price_percentile = calculate_percentile_rank(df["close"], period=lookback).iloc[-1]

    regime_result = detect_regime(
        trend=result.trend,
        bos=result.structure.bos,
        choch=result.structure.choch,
        volatility_percentile=float(vol_percentile) if vol_percentile == vol_percentile else 50.0,  # NaN-safe
        bb_width_percentile=float(bb_width_percentile) if bb_width_percentile == bb_width_percentile else 50.0,
        price_percentile_in_range=float(price_percentile) if price_percentile == price_percentile else 50.0,
    )

    n = min(_RETURN_LOOKBACK_CANDLES, len(df) - 1)
    return_pct = float((df["close"].iloc[-1] / df["close"].iloc[-1 - n] - 1) * 100) if n > 0 else 0.0

    return result, regime_result, return_pct, df


def _estimate_trade_levels(
    direction: str, price: float, support: list[float], resistance: list[float]
) -> tuple[tuple[float, float] | None, float | None, float | None, float | None]:
    """Estimativa de primeiro corte (ver limitação no docstring do módulo). Retorna (entry_zone, stop, target, distance_to_zone_pct)."""
    nearest_price, nearest_type, distance_pct = _nearest_zone(price, support, resistance)
    if nearest_price is None:
        return None, None, None, None

    zone_width = abs(price * 0.002)  # zona estreita em torno do nível -- estimativa conservadora, não uma otimização.
    entry_zone = (round(nearest_price - zone_width, 6), round(nearest_price + zone_width, 6))

    if direction == "long":
        stop_candidates = [s for s in support if s < nearest_price]
        target_candidates = sorted([r for r in resistance if r > nearest_price])
    else:
        stop_candidates = [s for s in resistance if s > nearest_price]
        target_candidates = sorted([r for r in support if r < nearest_price], reverse=True)

    stop = (min(stop_candidates) if direction == "long" else max(stop_candidates)) if stop_candidates else None
    target = target_candidates[0] if target_candidates else None

    return entry_zone, stop, target, distance_pct


def scan_opportunities(
    symbols: list[str],
    btc_symbol: str = "BTCUSDT",
    direction: str | None = None,
    style: str | None = None,
    timeframe: str = "1H",
    top_n: int = 5,
    market_data: MarketData | None = None,
) -> dict[str, Any]:
    """
    Args:
        symbols: universo de ativos a varrer (não inclui `btc_symbol`
            automaticamente -- some se quiser BTC no resultado também).
        direction: "long" | "short" | None (None = considera as duas).
        style: filtra o Playbook por estilo (`playbook.library.DAY_TRADE`
            etc.) -- None considera qualquer estilo.
        timeframe: timeframe usado tanto para a análise quanto para o
            cálculo de regime/retorno (Documento Master, seção 19 --
            multi-timeframe de verdade fica para uma fase futura).
        top_n: quantas oportunidades retornar no máximo (Documento
            Master, seção 21 -- "não mostrar 20 trades, quero seleção").

    Returns:
        dict com `opportunities` (lista rankeada) e `no_edge` (símbolos
        sem estratégia compatível no regime atual, com o motivo --
        nunca escondido, Documento Master seção 40).
    """
    md = market_data or MarketData()
    directions_to_try = [direction] if direction else ["long", "short"]

    btc_result, btc_regime, btc_return_pct, _btc_df = _asset_regime_and_context(btc_symbol, timeframe, md)

    candidates: list[OpportunityResult] = []
    no_edge: list[dict] = []
    returns_by_symbol: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for symbol in symbols:
        symbol = symbol.strip().upper()
        try:
            result, regime_result, return_pct, df = _asset_regime_and_context(symbol, timeframe, md)
        except InsufficientDataError as exc:
            errors[symbol] = str(exc)
            continue

        returns_by_symbol[symbol] = df["close"].pct_change().dropna().reset_index(drop=True)
        rel_strength = classify_relative_strength(return_pct, btc_return_pct)

        found_for_symbol = False
        for candidate_direction in directions_to_try:
            btc_context = (
                None
                if symbol == btc_symbol
                else classify_btc_context(btc_regime.regime, rel_strength.label, candidate_direction)
            )

            playbooks = compatible_playbooks(regime_result.regime, candidate_direction, style)
            if not playbooks:
                continue
            playbook: PlaybookEntry = playbooks[0]
            found_for_symbol = True

            entry_zone, stop, target, distance_pct = _estimate_trade_levels(
                candidate_direction, result.price, result.support, result.resistance
            )
            rr = None
            if stop is not None and target is not None and stop != result.price:
                risk = abs(result.price - stop)
                reward = abs(target - result.price)
                rr = round(reward / risk, 2) if risk > 0 else None

            score = compute_opportunity_score(
                trend=result.trend,
                bos=result.structure.bos,
                choch=result.structure.choch,
                regime_compatible=True,
                rr=rr,
                distance_to_zone_pct=distance_pct,
                volatility_bucket=regime_result.volatility_bucket,
                btc_context=btc_context,
                correlation_penalty=False,
                playbook_stats=None,
            )

            candidates.append(
                OpportunityResult(
                    symbol=symbol,
                    direction=candidate_direction,
                    playbook=playbook.name,
                    style=playbook.style,
                    regime=regime_result.regime,
                    btc_context=btc_context,
                    price=result.price,
                    entry_zone=entry_zone,
                    stop=stop,
                    target=target,
                    rr=rr,
                    distance_to_zone_pct=distance_pct,
                    score=score,
                    correlated_with=None,
                    notes=[*regime_result.notes, *(["RR não estimável -- sem zona oposta clara."] if rr is None else [])],
                )
            )

        if not found_for_symbol:
            no_edge.append(
                {
                    "symbol": symbol,
                    "regime": regime_result.regime,
                    "reason": f"Nenhuma estratégia do Playbook é compatível com o regime {regime_result.regime}"
                    + (f" para direção '{direction}'" if direction else "")
                    + (f" e estilo '{style}'" if style else "")
                    + ".",
                }
            )

    candidates.sort(key=lambda c: c.score.overall, reverse=True)

    if len(candidates) > 1 and len(returns_by_symbol) > 1:
        ranked_symbols_in_order = list(dict.fromkeys(c.symbol for c in candidates))
        try:
            correlation_matrix = compute_return_correlation(returns_by_symbol)
            correlation_flags = flag_correlated_duplicates(ranked_symbols_in_order, correlation_matrix, threshold=0.85)
        except Exception:  # noqa: BLE001 - correlação é um refinamento, nunca deve derrubar o ranking inteiro.
            correlation_flags = {}

        rescored: list[OpportunityResult] = []
        for c in candidates:
            correlated_with = correlation_flags.get(c.symbol)
            if correlated_with is None:
                rescored.append(c)
                continue
            new_score = compute_opportunity_score(
                trend="Bullish" if c.direction == "long" else "Bearish",  # já refletido no score original -- aqui só re-penaliza risk/overall
                bos=True,
                choch=False,
                regime_compatible=True,
                rr=c.rr,
                distance_to_zone_pct=c.distance_to_zone_pct,
                volatility_bucket="NORMAL",
                btc_context=c.btc_context,
                correlation_penalty=True,
                playbook_stats=None,
            )
            rescored.append(replace(c, correlated_with=correlated_with, score=new_score))
        candidates = sorted(rescored, key=lambda c: c.score.overall, reverse=True)

    return {
        "timeframe": timeframe,
        "btc_regime": btc_regime.to_dict(),
        "opportunities": [c.to_dict() for c in candidates[:top_n]],
        "no_edge": no_edge,
        "errors": errors,
        "disclaimer": (
            "Ranking pontual (momento da chamada), não monitoramento contínuo. Scores refletem "
            "critérios técnicos atuais, não são probabilidade de lucro. Entry/stop/target são "
            "uma estimativa de primeiro corte a partir de zonas de suporte/resistência -- validar "
            "antes de qualquer execução real."
        ),
    }
