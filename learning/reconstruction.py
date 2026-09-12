"""
learning/reconstruction.py
=============================

Call Reverse Engineering (Documento 2, seção 31). Reconstrói o
contexto de mercado NO MOMENTO em que um sinal externo foi emitido --
busca candles históricos até `signal_time` (via `HistoryFetcher`, a
mesma infraestrutura da Fase 1) e calcula trend/estrutura/regime sobre
esse recorte, exatamente como se fosse "agora" naquele instante.

Honestidade epistêmica (Documento 2, seção 31, perguntas 1-2: "o que o
trader viu?", "qual era o contexto?"): só a segunda pergunta é
respondível objetivamente a partir dos dados -- a primeira (o que
esteve na cabeça de quem emitiu o sinal) não é. Por isso o resultado
separa:

    FACT       -- calculado diretamente dos candles (trend, BOS/CHOCH, regime).
    INFERENCE  -- decisões derivadas do FACT com uma regra explícita
                  (ex.: "regime compatível com algum Playbook" é uma
                  inferência sobre adequação, não um fato bruto).
    HYPOTHESIS -- qualquer leitura sobre a INTENÇÃO de quem emitiu o
                  sinal -- este módulo nunca gera isso (não é
                  conhecível a partir de candles); fica para quem lê o
                  resultado formular, se quiser, com a ressalva clara.

Mesma convenção de `discovery/engine.py`: função de integração com
rede, não coberta por teste de unidade (só smoke test com provider
fake) -- a lógica pura de classificação já está em
`learning/classification.py`, testada à parte.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from backtest.history_fetcher import HistoryFetcher
from indicators.ema import calculate_ema
from indicators.atr import calculate_atr
from indicators.bands_channels import calculate_bollinger_bands
from statistics_.volatility import calculate_percentile_rank
from analysis.trend import determine_trend
from structure.market_structure import analyze_market_structure
from playbook.library import compatible_playbooks
from regime.detector import detect_regime
from learning.classification import compute_quality_score

_LOOKBACK_CANDLES_BEFORE_SIGNAL = 250  # margem suficiente pra EMA200 + percentis de 100 candles.


@dataclass(frozen=True, slots=True)
class ReconstructedContext:
    facts: dict[str, Any]
    inferences: dict[str, Any]
    hypothesis_note: str

    def to_dict(self) -> dict:
        return {"facts": self.facts, "inferences": self.inferences, "hypothesis_note": self.hypothesis_note}


_HYPOTHESIS_NOTE = (
    "O que o emissor do sinal viu/pensou não é reconstruível a partir dos candles -- "
    "apenas o CONTEXTO OBJETIVO do mercado no momento é reportado aqui (seção FACTS). "
    "Qualquer leitura sobre a intenção ou raciocínio de quem emitiu o sinal é hipótese, "
    "não fato, e não é gerada automaticamente."
)


def _candle_interval(timeframe: str) -> timedelta:
    unit = timeframe[-1].lower()
    value = int(timeframe[:-1])
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    raise ValueError(f"Timeframe '{timeframe}' não reconhecido (esperado sufixo m/h/d).")


def reconstruct_context(
    asset: str, direction: str, timeframe: str, signal_time, history_fetcher: HistoryFetcher
) -> ReconstructedContext:
    """
    Args:
        signal_time: datetime (com timezone) do momento em que o sinal
            foi emitido -- busca candles ATÉ este instante, nunca depois
            (não-lookahead também se aplica a reconstrução histórica).
    """
    interval = _candle_interval(timeframe)
    start = signal_time - interval * (_LOOKBACK_CANDLES_BEFORE_SIGNAL + 10)

    history = history_fetcher.fetch(symbol=asset, timeframe=timeframe, start=start, end=signal_time, min_candles=60)

    import pandas as pd

    df = pd.DataFrame([c.to_dict() for c in history.candles])
    df["open_time"] = pd.to_datetime(df["open_time"])
    df = df.set_index("open_time", drop=False).sort_index()

    ema20 = calculate_ema(df["close"], 20).iloc[-1]
    ema50 = calculate_ema(df["close"], 50).iloc[-1]
    ema100 = calculate_ema(df["close"], 100).iloc[-1]
    ema200 = calculate_ema(df["close"], 200).iloc[-1] if len(df) >= 200 else None

    structure_result = analyze_market_structure(df)
    trend = (
        determine_trend(ema20, ema50, ema100, ema200, structure_result.trend)
        if ema200 is not None and all(v == v for v in (ema20, ema50, ema100, ema200))  # NaN-safe
        else structure_result.trend
    )

    lookback = min(100, len(df))
    atr_series = calculate_atr(df, 14)
    vol_percentile = calculate_percentile_rank(atr_series, period=lookback).iloc[-1]
    bb = calculate_bollinger_bands(df, period=20, std_dev=2.0)
    bb_width = (bb.upper - bb.lower) / bb.middle
    bb_width_percentile = calculate_percentile_rank(bb_width, period=lookback).iloc[-1]
    price_percentile = calculate_percentile_rank(df["close"], period=lookback).iloc[-1]

    regime_result = detect_regime(
        trend=trend,
        bos=structure_result.bos,
        choch=structure_result.choch,
        volatility_percentile=float(vol_percentile) if vol_percentile == vol_percentile else 50.0,
        bb_width_percentile=float(bb_width_percentile) if bb_width_percentile == bb_width_percentile else 50.0,
        price_percentile_in_range=float(price_percentile) if price_percentile == price_percentile else 50.0,
    )

    facts = {
        "price_at_signal": float(df["close"].iloc[-1]),
        "trend": trend,
        "bos": structure_result.bos,
        "choch": structure_result.choch,
        "regime": regime_result.regime,
        "volatility_bucket": regime_result.volatility_bucket,
        "candles_used": len(df),
    }

    playbooks = compatible_playbooks(regime_result.regime, direction)
    regime_compatible = len(playbooks) > 0
    quality_score = compute_quality_score(
        trend=trend, bos=structure_result.bos, choch=structure_result.choch,
        regime_compatible=regime_compatible, rr=None,
    )
    inferences = {
        "regime_compatible_with_playbook": regime_compatible,
        "matching_playbooks": [p.name for p in playbooks],
        "quality_score": round(quality_score, 1),
    }

    return ReconstructedContext(facts=facts, inferences=inferences, hypothesis_note=_HYPOTHESIS_NOTE)
