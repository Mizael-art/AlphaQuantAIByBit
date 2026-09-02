"""
tests/test_json_contract.py
==============================

Testes de regressão do CONTRATO JSON entre o AlphaQuant Engine e as
instruções do GPT (AlphaQuant X) — sem rede, testando só a lógica de
serialização (`to_dict`).

Por que este arquivo existe: as instruções do GPT (arquivo 16, "Data
Acquisition Engine") leem campos específicos do JSON (`meta.source`,
`order_flow.available`, etc.). Uma mudança de shape aqui quebra o
contrato silenciosamente do lado do GPT, sem nenhum teste do lado
Python acusar nada — por isso vale a pena fixar esse contrato aqui.
"""

from __future__ import annotations

from datetime import datetime, timezone

from snapshot.market_snapshot import MarketSnapshot


def _empty_snapshot(data_sources: dict[str, str]) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="XAUUSD",
        price=2400.0,
        generated_at=datetime.now(timezone.utc),
        timeframes={},
        derivatives={"available": False},
        confluence={},
        errors={},
        data_sources=data_sources,
    )


def test_meta_has_both_source_and_data_sources_fields() -> None:
    """`meta.source` precisa continuar existindo (compat com instruções
    antigas) ao lado de `meta.data_sources` (granularidade nova)."""
    snap = _empty_snapshot({"15m": "bybit_tradfi", "1H": "bybit_tradfi"})
    result = snap.to_dict()

    assert "source" in result["meta"]
    assert "data_sources" in result["meta"]


def test_meta_source_is_single_provider_when_all_timeframes_agree() -> None:
    snap = _empty_snapshot({"15m": "bybit_crypto", "1H": "bybit_crypto", "4H": "bybit_crypto"})
    result = snap.to_dict()

    assert result["meta"]["source"] == "bybit_crypto"


def test_meta_source_is_mixed_when_timeframes_used_different_providers() -> None:
    """Ex.: fallback no meio do caminho -- 1H usou Bybit, 4H caiu pro fallback Binance."""
    snap = _empty_snapshot({"1H": "bybit_crypto", "4H": "binance"})
    result = snap.to_dict()

    assert result["meta"]["source"] == "mixed"


def test_meta_source_is_unknown_when_no_timeframe_succeeded() -> None:
    snap = _empty_snapshot({})
    result = snap.to_dict()

    assert result["meta"]["source"] == "unknown"
