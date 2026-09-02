"""
snapshot/timeframe_snapshot.py
=================================

Consolida TODA a análise disponível para um único (symbol, timeframe)
em uma única estrutura: indicadores clássicos e estendidos, estrutura
de mercado, Smart Money Concepts, Volume Profile, Order Flow
(Delta/CVD) e estatística.

Esta é a unidade básica que o `market_snapshot.py` replica para cada
timeframe (15m, 1H, 4H, 1D, ...) antes de combinar tudo no snapshot
multi-timeframe final.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

import indicators as ind
from analysis.liquidity import find_liquidity_zones
from analysis.score import calculate_score
from analysis.support_resistance import find_support_resistance
from analysis.trend import determine_trend
from order_flow.delta import build_order_flow
from reconciliation.cross_exchange import CrossExchangeReconciliationEngine, NoExchangeAvailableError
from reconciliation.structure_consensus import StructureConsensusEngine
from smc.equal_highs_lows import find_equal_highs_lows
from smc.fair_value_gaps import find_fair_value_gaps
from smc.liquidity_sweeps import find_liquidity_sweeps
from smc.order_blocks import find_order_blocks
from smc.premium_discount import premium_discount_from_swings
from statistics_.volatility import build_volatility_stats
from structure.market_structure import analyze_market_structure
from structure.swings import get_swing_points
from volume_profile.profile import build_volume_profile


class InsufficientDataError(Exception):
    """Levantada quando não há candles suficientes para uma análise confiável."""


@dataclass(frozen=True, slots=True)
class TimeframeSnapshot:
    """Snapshot completo de um único timeframe, pronto para serialização."""

    symbol: str
    timeframe: str
    price: float
    candles_used: int
    generated_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "price": self.price,
            "meta": {
                "candles_used": self.candles_used,
                "generated_at": self.generated_at.isoformat(),
                "source": "binance_public_api",
            },
            **self.payload,
        }


def build_timeframe_snapshot(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    current_price: float,
    min_candles: int = 200,
    price_consensus_engine: CrossExchangeReconciliationEngine | None = None,
    structure_consensus_engine: StructureConsensusEngine | None = None,
    execution_venue: str | None = None,
    price_consensus_limit: int = 50,
    structure_consensus_limit: int = 300,
) -> TimeframeSnapshot:
    """
    Constrói o snapshot completo de análise para um único timeframe.

    Args:
        df: DataFrame OHLCV já buscado para o timeframe em questão
            (sempre da fonte principal do `ProviderRouter` -- a
            EXECUTION VIEW / análise "clássica" deste módulo não muda).
        symbol: par de negociação, ex.: "ETHUSDT".
        timeframe: timeframe amigável, ex.: "4H".
        current_price: preço atual do ativo (mesmo para todos os timeframes).
        min_candles: quantidade mínima de candles para uma análise confiável.
        price_consensus_engine: quando informado, roda o
            `CrossExchangeReconciliationEngine` (consenso de preço/wick
            entre exchanges -- Documento 4) e adiciona o resultado em
            `payload["cross_exchange"]["price"]`. `None` = MARKET VIEW
            desligada para este snapshot (comportamento antigo, single-source).
        structure_consensus_engine: quando informado, roda o
            `StructureConsensusEngine` (BOS/CHOCH/sweep/FVG/OB por
            exchange + consenso) e adiciona em
            `payload["cross_exchange"]["structure"]`.
        execution_venue: exchange usada como EXECUTION VIEW (Documento
            4, seção 9) -- repassada aos dois engines acima, nunca
            usada para substituir o consenso de mercado.

    Returns:
        `TimeframeSnapshot` com indicadores, estrutura, SMC, volume
        profile, estatística e (quando os engines forem passados)
        consenso multi-exchange -- tudo consolidado.

    Note:
        Uma falha nos engines de cross-exchange (ex.: as 4 exchanges
        fora do ar, ou símbolo não suportado por nenhuma delas) NUNCA
        derruba o snapshot inteiro -- fica registrada como
        `{"available": False, "reason": ...}` dentro de `cross_exchange`,
        e o restante da análise (fonte única) segue normalmente. Isso
        segue a filosofia do sistema: preferir dizer "sem confirmação
        cruzada" a quebrar a análise inteira por causa de uma camada
        adicional de evidência.
    """
    if len(df) < min_candles:
        raise InsufficientDataError(
            f"Candles insuficientes para {symbol} ({timeframe}): "
            f"{len(df)} recebidos, mínimo recomendado é {min_candles}."
        )

    # ------------------------------------------------------------------
    # INDICADORES CLÁSSICOS
    # ------------------------------------------------------------------
    emas = ind.calculate_all_emas(df)
    rsi = ind.calculate_rsi(df["close"])
    atr = ind.calculate_atr(df)
    macd_result = ind.calculate_macd(df["close"])
    volume_avg = ind.calculate_volume_average(df)

    # ------------------------------------------------------------------
    # INDICADORES ESTENDIDOS
    # ------------------------------------------------------------------
    adx_result = ind.calculate_adx(df)
    cci = ind.calculate_cci(df)
    mfi = ind.calculate_mfi(df)
    roc = ind.calculate_roc(df["close"])
    stoch = ind.calculate_stochastic(df)
    williams_r = ind.calculate_williams_r(df)
    obv = ind.calculate_obv(df)
    cmf = ind.calculate_cmf(df)
    bollinger = ind.calculate_bollinger_bands(df)
    donchian = ind.calculate_donchian_channels(df)
    keltner = ind.calculate_keltner_channels(df)
    supertrend = ind.calculate_supertrend(df)
    parabolic_sar = ind.calculate_parabolic_sar(df)
    ichimoku = ind.calculate_ichimoku(df)
    session_vwap = ind.calculate_session_vwap(df) if df.index.tz is not None else ind.calculate_vwap(df)

    # ------------------------------------------------------------------
    # ESTRUTURA DE MERCADO + SMC
    # ------------------------------------------------------------------
    structure_result = analyze_market_structure(df)
    swings = get_swing_points(df)

    order_blocks = find_order_blocks(df)
    fvgs = find_fair_value_gaps(df)
    equal_highs, equal_lows = find_equal_highs_lows(df)
    liquidity_sweeps = find_liquidity_sweeps(df)
    premium_discount = premium_discount_from_swings(
        swing_high=structure_result.swing_high,
        swing_low=structure_result.swing_low,
        current_price=current_price,
    )

    # ------------------------------------------------------------------
    # ANÁLISE (tendência final, S/R, liquidez, score)
    # ------------------------------------------------------------------
    ema20 = float(emas["ema20"].iloc[-1])
    ema50 = float(emas["ema50"].iloc[-1])
    ema100 = float(emas["ema100"].iloc[-1])
    ema200 = float(emas["ema200"].iloc[-1])

    trend = determine_trend(ema20, ema50, ema100, ema200, structure_result.trend)
    support, resistance = find_support_resistance(df, swings, current_price)
    liquidity = find_liquidity_zones(swings)

    macd_histogram = float(macd_result.histogram.iloc[-1])
    volume_above_average = bool(df["volume"].iloc[-1] > volume_avg.iloc[-1])

    score = calculate_score(
        trend=trend,
        rsi=float(rsi.iloc[-1]),
        macd_histogram=macd_histogram,
        bos=structure_result.bos,
        choch=structure_result.choch,
        volume_above_average=volume_above_average,
    )

    # ------------------------------------------------------------------
    # VOLUME PROFILE + ESTATÍSTICA
    # ------------------------------------------------------------------
    vol_profile = build_volume_profile(df)
    vol_stats = build_volatility_stats(df, timeframe=timeframe)

    # order_flow depende de `taker_buy_volume`, que só a Binance expõe
    # nos klines públicos. Providers TradFi/Bybit não têm esse campo
    # (ver models/candle.py) — em vez de fabricar delta/CVD a partir de
    # um valor inexistente, o campo fica marcado como indisponível.
    has_order_flow_data = "taker_buy_volume" in df.columns and df["taker_buy_volume"].notna().all()
    if has_order_flow_data:
        order_flow_payload = {"available": True, **build_order_flow(df).to_dict()}
    else:
        order_flow_payload = {
            "available": False,
            "reason": (
                "taker_buy_volume não fornecido pelo provider de dados usado "
                "para este símbolo — Delta/CVD não pode ser calculado sem "
                "estimar dado, o que este sistema não faz."
            ),
        }

    # ------------------------------------------------------------------
    # CROSS-EXCHANGE (MARKET VIEW / STRUCTURE VIEW -- opcional)
    # ------------------------------------------------------------------
    cross_exchange_payload: dict[str, Any] = {}

    if price_consensus_engine is not None:
        try:
            price_consensus = price_consensus_engine.get_consensus(
                symbol, timeframe, limit=price_consensus_limit, execution_venue=execution_venue
            )
            cross_exchange_payload["price"] = {"available": True, **price_consensus.to_dict()}
        except NoExchangeAvailableError as exc:
            cross_exchange_payload["price"] = {"available": False, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - consenso é evidência ADICIONAL, nunca pode derrubar o snapshot.
            cross_exchange_payload["price"] = {"available": False, "reason": f"Falha inesperada no consenso de preço: {exc}"}

    if structure_consensus_engine is not None:
        try:
            structure_consensus = structure_consensus_engine.get_consensus(
                symbol, timeframe, limit=structure_consensus_limit, execution_venue=execution_venue
            )
            cross_exchange_payload["structure"] = {"available": True, **structure_consensus.to_dict()}
        except NoExchangeAvailableError as exc:
            cross_exchange_payload["structure"] = {"available": False, "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - mesma lógica: nunca derruba o snapshot inteiro.
            cross_exchange_payload["structure"] = {"available": False, "reason": f"Falha inesperada no consenso de estrutura: {exc}"}

    # ------------------------------------------------------------------
    # MONTAGEM DO PAYLOAD FINAL
    # ------------------------------------------------------------------
    payload: dict[str, Any] = {
        "trend": trend,
        "score": score,
        "indicators": {
            "ema20": round(ema20, 6),
            "ema50": round(ema50, 6),
            "ema100": round(ema100, 6),
            "ema200": round(ema200, 6),
            "rsi": round(float(rsi.iloc[-1]), 2),
            "atr": round(float(atr.iloc[-1]), 6),
            "macd": round(float(macd_result.macd_line.iloc[-1]), 6),
            "macd_signal": round(float(macd_result.signal_line.iloc[-1]), 6),
            "macd_histogram": round(macd_histogram, 6),
            "volume_avg": round(float(volume_avg.iloc[-1]), 6),
            "volume_above_average": volume_above_average,
            "adx": round(float(adx_result.adx.iloc[-1]), 2) if pd.notna(adx_result.adx.iloc[-1]) else None,
            "plus_di": round(float(adx_result.plus_di.iloc[-1]), 2) if pd.notna(adx_result.plus_di.iloc[-1]) else None,
            "minus_di": round(float(adx_result.minus_di.iloc[-1]), 2) if pd.notna(adx_result.minus_di.iloc[-1]) else None,
            "cci": round(float(cci.iloc[-1]), 2) if pd.notna(cci.iloc[-1]) else None,
            "mfi": round(float(mfi.iloc[-1]), 2) if pd.notna(mfi.iloc[-1]) else None,
            "roc": round(float(roc.iloc[-1]), 4) if pd.notna(roc.iloc[-1]) else None,
            "stochastic_k": round(float(stoch.percent_k.iloc[-1]), 2) if pd.notna(stoch.percent_k.iloc[-1]) else None,
            "stochastic_d": round(float(stoch.percent_d.iloc[-1]), 2) if pd.notna(stoch.percent_d.iloc[-1]) else None,
            "williams_r": round(float(williams_r.iloc[-1]), 2) if pd.notna(williams_r.iloc[-1]) else None,
            "obv": round(float(obv.iloc[-1]), 2),
            "cmf": round(float(cmf.iloc[-1]), 4) if pd.notna(cmf.iloc[-1]) else None,
            "bollinger": {
                "upper": round(float(bollinger.upper.iloc[-1]), 6) if pd.notna(bollinger.upper.iloc[-1]) else None,
                "middle": round(float(bollinger.middle.iloc[-1]), 6) if pd.notna(bollinger.middle.iloc[-1]) else None,
                "lower": round(float(bollinger.lower.iloc[-1]), 6) if pd.notna(bollinger.lower.iloc[-1]) else None,
            },
            "donchian": {
                "upper": round(float(donchian.upper.iloc[-1]), 6) if pd.notna(donchian.upper.iloc[-1]) else None,
                "lower": round(float(donchian.lower.iloc[-1]), 6) if pd.notna(donchian.lower.iloc[-1]) else None,
            },
            "keltner": {
                "upper": round(float(keltner.upper.iloc[-1]), 6) if pd.notna(keltner.upper.iloc[-1]) else None,
                "lower": round(float(keltner.lower.iloc[-1]), 6) if pd.notna(keltner.lower.iloc[-1]) else None,
            },
            "supertrend": {
                "value": round(float(supertrend.supertrend.iloc[-1]), 6) if pd.notna(supertrend.supertrend.iloc[-1]) else None,
                "direction": "bullish" if supertrend.direction.iloc[-1] == 1 else "bearish",
            },
            "parabolic_sar": round(float(parabolic_sar.iloc[-1]), 6) if pd.notna(parabolic_sar.iloc[-1]) else None,
            "ichimoku": {
                "tenkan_sen": round(float(ichimoku.tenkan_sen.iloc[-1]), 6) if pd.notna(ichimoku.tenkan_sen.iloc[-1]) else None,
                "kijun_sen": round(float(ichimoku.kijun_sen.iloc[-1]), 6) if pd.notna(ichimoku.kijun_sen.iloc[-1]) else None,
                "senkou_span_a": round(float(ichimoku.senkou_span_a.iloc[-1]), 6) if pd.notna(ichimoku.senkou_span_a.iloc[-1]) else None,
                "senkou_span_b": round(float(ichimoku.senkou_span_b.iloc[-1]), 6) if pd.notna(ichimoku.senkou_span_b.iloc[-1]) else None,
            },
            "vwap": round(float(session_vwap.iloc[-1]), 6) if pd.notna(session_vwap.iloc[-1]) else None,
        },
        "structure": {
            "HH": structure_result.hh,
            "HL": structure_result.hl,
            "LH": structure_result.lh,
            "LL": structure_result.ll,
            "BOS": structure_result.bos,
            "CHOCH": structure_result.choch,
            "swing_high": structure_result.swing_high,
            "swing_low": structure_result.swing_low,
        },
        "smc": {
            "order_blocks": [ob.to_dict() for ob in order_blocks],
            "fair_value_gaps": [fvg.to_dict() for fvg in fvgs],
            "equal_highs": [eh.to_dict() for eh in equal_highs],
            "equal_lows": [el.to_dict() for el in equal_lows],
            "liquidity_sweeps": [sweep.to_dict() for sweep in liquidity_sweeps],
            "premium_discount": premium_discount.to_dict() if premium_discount else None,
        },
        "support_resistance": {
            "support": support,
            "resistance": resistance,
        },
        "liquidity": {
            "buy_side": liquidity.buy_side,
            "sell_side": liquidity.sell_side,
        },
        "volume_profile": vol_profile.to_dict(),
        "order_flow": order_flow_payload,
        **({"cross_exchange": cross_exchange_payload} if cross_exchange_payload else {}),
        "statistics": {
            "std_dev": round(vol_stats.std_dev, 6),
            "z_score": round(vol_stats.z_score, 4),
            "historical_volatility_pct": (
                round(vol_stats.historical_volatility_pct, 2)
                if vol_stats.historical_volatility_pct is not None
                else None
            ),
            "realized_volatility_pct": round(vol_stats.realized_volatility_pct, 4),
            "percentile_rank": round(vol_stats.percentile_rank, 2),
        },
    }

    return TimeframeSnapshot(
        symbol=symbol.upper(),
        timeframe=timeframe,
        price=current_price,
        candles_used=len(df),
        generated_at=datetime.now(timezone.utc),
        payload=payload,
    )
