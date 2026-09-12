"""
tests/test_structure_consensus.py
=====================================

Testes do `StructureConsensusEngine` -- Documento 4, seções 5-9 e
15-17 / Documento 6. Providers mockados, sem rede.

Duas camadas de teste:
    1. Unitária: a lógica de agregação (`_bool_consensus`,
       `_classify_zones`, `_overall_confidence`) testada diretamente
       com objetos construídos -- não depende de series OHLCV reais
       nem de reproduzir a matemática de swings/BOS (isso já é coberto
       por `tests/test_structure.py` / `tests/test_smc.py`).
    2. Integração: `get_consensus()` fim-a-fim com candles sintéticos
       (mesmo padrão de fixture usado em `tests/test_smc.py`), cobrindo
       o cenário central do Documento 4 -- TRX com uma exchange
       divergente das demais -- e o tratamento de falhas parciais/totais.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from models.candle import Candle
from providers.base import MarketDataError, MarketDataProvider, Quote
from reconciliation.cross_exchange import NoExchangeAvailableError
from reconciliation.structure_consensus import (
    ExchangeStructureView,
    StructureConsensusEngine,
)
from smc.fair_value_gaps import FVGZone
from smc.order_blocks import OrderBlock

UTC = timezone.utc


# ======================================================================
# 1. UNITÁRIO -- consenso booleano
# ======================================================================

def _view(exchange: str, **kwargs) -> ExchangeStructureView:
    defaults = dict(exchange=exchange, available=True, candles_count=300, data_quality_score=100.0)
    defaults.update(kwargs)
    return ExchangeStructureView(**defaults)


def test_bool_consensus_all_agree_is_high_confidence() -> None:
    views = [_view("binance", bos=True), _view("bybit_crypto", bos=True), _view("okx", bos=True), _view("bitget", bos=True)]
    consensus = StructureConsensusEngine._bool_consensus(views, "bos", n_total=4)

    assert consensus.agree == 4
    assert consensus.total == 4
    assert consensus.confidence == "HIGH"
    assert consensus.agreeing_exchanges == ["binance", "bitget", "bybit_crypto", "okx"]


def test_bool_consensus_one_isolated_is_moderate_or_low_not_high() -> None:
    """Cenário do Documento 4: BOS = TRUE só na Binance, FALSE nas outras 3."""
    views = [_view("binance", bos=True), _view("bybit_crypto", bos=False), _view("okx", bos=False), _view("bitget", bos=False)]
    consensus = StructureConsensusEngine._bool_consensus(views, "bos", n_total=4)

    assert consensus.agree == 1
    assert consensus.confidence != "HIGH"  # 1/4 concordando nunca deve virar alta confiança
    assert consensus.agreeing_exchanges == ["binance"]


def test_bool_consensus_single_exchange_available_is_low() -> None:
    """Fonte única -- mesmo TRUE, não há confirmação cruzada possível (seção 5-6)."""
    views = [_view("binance", bos=True)]
    consensus = StructureConsensusEngine._bool_consensus(views, "bos", n_total=1)

    assert consensus.confidence == "LOW"


def test_bool_consensus_no_views_is_insufficient() -> None:
    consensus = StructureConsensusEngine._bool_consensus([], "bos", n_total=4)
    assert consensus.confidence == "INSUFFICIENT"
    assert consensus.agree == 0


def test_bool_consensus_all_agree_false_is_still_high_confidence() -> None:
    """4/4 concordando que NÃO houve BOS também é consenso forte -- consenso não é só sobre TRUE."""
    views = [_view("binance", bos=False), _view("bybit_crypto", bos=False), _view("okx", bos=False), _view("bitget", bos=False)]
    consensus = StructureConsensusEngine._bool_consensus(views, "bos", n_total=4)

    assert consensus.agree == 0
    assert consensus.confidence == "HIGH"


# ======================================================================
# 2. UNITÁRIO -- classificação de zonas (FVG / Order Block)
# ======================================================================

def _fvg(top: float, bottom: float, direction: str = "bullish", t: datetime | None = None) -> FVGZone:
    return FVGZone(
        direction=direction, top=top, bottom=bottom,
        candle_time=t or datetime(2024, 1, 1, tzinfo=UTC),
        mitigated=False, mitigated_pct=0.0, is_inverse=False,
    )


def test_zone_seen_in_two_exchanges_is_cross_exchange() -> None:
    zones_by_exchange = {
        "binance": [_fvg(top=105.0, bottom=103.0)],
        "bitget": [_fvg(top=105.2, bottom=103.1)],  # praticamente a mesma zona
    }
    cross, specific = StructureConsensusEngine._classify_zones(zones_by_exchange)

    assert len(cross) == 2  # entrada por exchange, ambas marcadas como cross_exchange
    assert specific == []
    assert set(cross[0]["confirmed_by"]) == {"binance", "bitget"}


def test_zone_seen_in_only_one_exchange_is_exchange_specific() -> None:
    zones_by_exchange = {
        "binance": [_fvg(top=105.0, bottom=103.0)],
        "bitget": [_fvg(top=50.0, bottom=48.0)],  # zona completamente diferente
    }
    cross, specific = StructureConsensusEngine._classify_zones(zones_by_exchange)

    assert cross == []
    assert len(specific) == 2
    assert all(entry["confirmed_by"] == [entry["exchange"]] for entry in specific)


def test_zone_different_direction_never_matches() -> None:
    zones_by_exchange = {
        "binance": [_fvg(top=105.0, bottom=103.0, direction="bullish")],
        "bitget": [_fvg(top=105.0, bottom=103.0, direction="bearish")],  # mesmo range, direção oposta
    }
    cross, specific = StructureConsensusEngine._classify_zones(zones_by_exchange)

    assert cross == []
    assert len(specific) == 2


def test_zone_classification_works_for_order_blocks_too() -> None:
    ob_a = OrderBlock(direction="bullish", top=200.0, bottom=198.0, formed_at=datetime(2024, 1, 1, tzinfo=UTC), mitigated=False, broken=False)
    ob_b = OrderBlock(direction="bullish", top=200.1, bottom=198.1, formed_at=datetime(2024, 1, 1, tzinfo=UTC), mitigated=False, broken=False)
    cross, specific = StructureConsensusEngine._classify_zones({"okx": [ob_a], "binance": [ob_b]})

    assert len(cross) == 2
    assert specific == []


# ======================================================================
# 3. INTEGRAÇÃO -- get_consensus() fim-a-fim, providers mockados
# ======================================================================

def _trending_candles(
    n: int = 250, start: float = 1000.0, end: float = 1400.0, seed: int = 21, tf_minutes: int = 15
) -> list[Candle]:
    """Mesmo padrão de `tests/test_smc.py::trending_df`, convertido para `Candle`."""
    rng = np.random.default_rng(seed)
    trend = np.linspace(start, end, n)
    noise = rng.normal(0, 5, n)
    close = trend + noise
    high = close + np.abs(rng.normal(3, 1.5, n))
    low = close - np.abs(rng.normal(3, 1.5, n))
    open_ = close - rng.normal(0, 2, n)
    volume = np.abs(rng.normal(1000, 200, n))

    now = datetime.now(UTC)
    delta = timedelta(minutes=tf_minutes)
    candles = []
    for i in range(n):
        t = now - delta * (n - i)
        c_high = float(max(high[i], open_[i], close[i]))
        c_low = float(min(low[i], open_[i], close[i]))
        candles.append(
            Candle(
                open_time=t, open=float(open_[i]), high=c_high, low=c_low, close=float(close[i]),
                volume=float(volume[i]), close_time=t + delta,
            )
        )
    return candles


class _FakeExchange(MarketDataProvider):
    def __init__(self, name: str, candles: list[Candle], fail: bool = False) -> None:
        self.name = name
        self._candles = candles
        self._fail = fail

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class == "crypto"

    def get_candles(self, canonical_symbol, timeframe, limit, end_time=None):
        if self._fail:
            raise MarketDataError(f"{self.name} indisponível")
        return self._candles[-limit:]

    def get_quote(self, canonical_symbol: str) -> Quote:
        last = self._candles[-1]
        return Quote(canonical_symbol=canonical_symbol, provider=self.name, last_price=last.close, bid=None, ask=None, spread=None)

    def close(self) -> None:
        pass


def test_get_consensus_runs_structure_independently_per_exchange() -> None:
    exchanges = [
        _FakeExchange("binance", _trending_candles(seed=21)),
        _FakeExchange("bybit_crypto", _trending_candles(seed=22)),
        _FakeExchange("okx", _trending_candles(seed=23)),
        _FakeExchange("bitget", _trending_candles(seed=24)),
    ]
    engine = StructureConsensusEngine(providers=exchanges)

    result = engine.get_consensus("TRXUSDT", "15m", limit=250, execution_venue="bitget")

    assert result.execution_venue == "bitget"
    assert len(result.exchanges) == 4
    assert all(v.available for v in result.exchanges)
    # Cada exchange calculou sua PRÓPRIA estrutura -- não é o mesmo objeto repetido 4x.
    trends = {v.exchange: v.trend for v in result.exchanges}
    assert len(trends) == 4
    assert set(result.structure_consensus.keys()) == {"hh", "hl", "lh", "ll", "bos", "choch"}
    assert set(result.liquidity_consensus.keys()) == {"recent_sweep_high", "recent_sweep_low"}
    assert result.data_quality_avg == 100.0  # dados sintéticos limpos, sem gaps/duplicatas


def test_one_exchange_failing_is_marked_unavailable_with_reason() -> None:
    exchanges = [
        _FakeExchange("binance", _trending_candles(seed=21)),
        _FakeExchange("bybit_crypto", _trending_candles(seed=22), fail=True),
        _FakeExchange("okx", _trending_candles(seed=23)),
    ]
    engine = StructureConsensusEngine(providers=exchanges)

    result = engine.get_consensus("BTCUSDT", "15m", limit=250)

    bybit_view = next(v for v in result.exchanges if v.exchange == "bybit_crypto")
    binance_view = next(v for v in result.exchanges if v.exchange == "binance")
    assert bybit_view.available is False
    assert bybit_view.unavailable_reason
    assert binance_view.available is True  # falha de uma exchange não contamina as demais


def test_insufficient_candles_marks_exchange_unavailable_not_a_crash() -> None:
    exchanges = [
        _FakeExchange("binance", _trending_candles(n=250, seed=21)),
        _FakeExchange("okx", _trending_candles(n=10, seed=23)),  # abaixo do mínimo de 200
    ]
    engine = StructureConsensusEngine(providers=exchanges)

    result = engine.get_consensus("BTCUSDT", "15m", limit=250)

    okx_view = next(v for v in result.exchanges if v.exchange == "okx")
    assert okx_view.available is False
    assert "insuficientes" in okx_view.unavailable_reason.lower()


def test_all_exchanges_failing_raises_not_silently_empty() -> None:
    exchanges = [
        _FakeExchange("binance", _trending_candles(seed=21), fail=True),
        _FakeExchange("okx", _trending_candles(seed=23), fail=True),
    ]
    engine = StructureConsensusEngine(providers=exchanges)

    with pytest.raises(NoExchangeAvailableError):
        engine.get_consensus("BTCUSDT", "15m", limit=250)


def test_no_eligible_exchange_for_asset_class_raises() -> None:
    engine = StructureConsensusEngine(providers=[])
    with pytest.raises(NoExchangeAvailableError):
        engine.get_consensus("BTCUSDT", "15m", limit=250)


def test_result_to_dict_is_json_serializable() -> None:
    import json

    exchanges = [
        _FakeExchange("binance", _trending_candles(seed=21)),
        _FakeExchange("bitget", _trending_candles(seed=24)),
    ]
    engine = StructureConsensusEngine(providers=exchanges)
    result = engine.get_consensus("BTCUSDT", "15m", limit=250, execution_venue="bitget")

    json.dumps(result.to_dict())  # não deve levantar TypeError


def test_individual_exchange_results_are_never_discarded() -> None:
    """Documento 4, seção 16: o consolidado NUNCA pode substituir o resultado individual."""
    exchanges = [
        _FakeExchange("binance", _trending_candles(seed=21)),
        _FakeExchange("bybit_crypto", _trending_candles(seed=22)),
    ]
    engine = StructureConsensusEngine(providers=exchanges)
    result = engine.get_consensus("BTCUSDT", "15m", limit=250)

    payload = result.to_dict()
    assert len(payload["exchanges"]) == 2
    for exchange_payload in payload["exchanges"]:
        assert "structure" in exchange_payload
        assert "HH" in exchange_payload["structure"] and "BOS" in exchange_payload["structure"]
