"""
tests/test_symbol_mapper.py
=============================

Testes do `SymbolMapper` — puramente determinístico, sem rede.
"""

from __future__ import annotations

import pytest

from symbols.mapper import AssetClass, SymbolMapper, SymbolNotRecognizedError


@pytest.fixture
def mapper() -> SymbolMapper:
    return SymbolMapper()


def test_crypto_pair_resolves_by_quote_suffix(mapper: SymbolMapper) -> None:
    result = mapper.resolve("BTCUSDT")
    assert result.canonical_symbol == "BTCUSDT"
    assert result.asset_class == AssetClass.CRYPTO


def test_crypto_pair_with_slash_format_normalizes(mapper: SymbolMapper) -> None:
    result = mapper.resolve("BTC/USDT")
    assert result.canonical_symbol == "BTCUSDT"
    assert result.asset_class == AssetClass.CRYPTO


def test_xauusd_resolves_as_metal(mapper: SymbolMapper) -> None:
    result = mapper.resolve("XAUUSD")
    assert result.canonical_symbol == "XAUUSD"
    assert result.asset_class == AssetClass.METAL


@pytest.mark.parametrize("alias", ["XAUUSD+", "XAUUSD.s", "xauusd", "  xauusd  "])
def test_xauusd_aliases_all_map_to_same_canonical(mapper: SymbolMapper, alias: str) -> None:
    result = mapper.resolve(alias)
    assert result.canonical_symbol == "XAUUSD"
    assert result.asset_class == AssetClass.METAL


def test_nas100_resolves_as_index(mapper: SymbolMapper) -> None:
    result = mapper.resolve("NAS100")
    assert result.canonical_symbol == "NAS100"
    assert result.asset_class == AssetClass.INDEX


@pytest.mark.parametrize("alias", ["NAS100+", "USTEC", "ustec.s"])
def test_nas100_aliases_all_map_to_same_canonical(mapper: SymbolMapper, alias: str) -> None:
    result = mapper.resolve(alias)
    assert result.canonical_symbol == "NAS100"


def test_eurusd_resolves_as_forex(mapper: SymbolMapper) -> None:
    result = mapper.resolve("EURUSD")
    assert result.asset_class == AssetClass.FOREX


def test_unrecognized_symbol_raises(mapper: SymbolMapper) -> None:
    with pytest.raises(SymbolNotRecognizedError):
        mapper.resolve("NOTASYMBOL123")


def test_empty_symbol_raises(mapper: SymbolMapper) -> None:
    with pytest.raises(SymbolNotRecognizedError):
        mapper.resolve("   ")


def test_to_provider_symbol_uses_override_for_bybit_tradfi(mapper: SymbolMapper) -> None:
    assert mapper.to_provider_symbol("XAUUSD", "bybit_tradfi") == "XAUUSD+"


def test_to_provider_symbol_defaults_to_canonical_when_no_override(mapper: SymbolMapper) -> None:
    assert mapper.to_provider_symbol("BTCUSDT", "bybit_crypto") == "BTCUSDT"
    assert mapper.to_provider_symbol("NAS100", "bybit_tradfi") == "NAS100"


# ----------------------------------------------------------------------
# Regressão: sufixo ".P" do TradingView (contrato perpétuo) e prefixo
# de exchange ("BYBIT:") -- bug relatado pelo usuário com CLUSDT.P.
#
# Na API real (Bybit V5), "CLUSDT.P" no gráfico do TradingView e
# "CLUSDT" via `category=linear` são o MESMO ativo -- o ".P" é só a
# notação do TradingView para "isto é o perpétuo", não faz parte do
# símbolo de nenhuma exchange.
# ----------------------------------------------------------------------
def test_tradingview_perpetual_suffix_is_stripped(mapper: SymbolMapper) -> None:
    result = mapper.resolve("CLUSDT.P")
    assert result.canonical_symbol == "CLUSDT"
    assert result.asset_class == AssetClass.CRYPTO


def test_tradingview_exchange_prefix_is_stripped(mapper: SymbolMapper) -> None:
    result = mapper.resolve("BYBIT:CLUSDT.P")
    assert result.canonical_symbol == "CLUSDT"
    assert result.asset_class == AssetClass.CRYPTO


def test_tradingview_prefix_and_suffix_case_insensitive(mapper: SymbolMapper) -> None:
    result = mapper.resolve("bybit:clusdt.p")
    assert result.canonical_symbol == "CLUSDT"


@pytest.mark.parametrize(
    "raw,expected_canonical",
    [
        ("BTCUSDT.P", "BTCUSDT"),
        ("ETHUSDT.P", "ETHUSDT"),
        ("BINANCE:SOLUSDT.P", "SOLUSDT"),
    ],
)
def test_various_perpetual_symbols_resolve(mapper: SymbolMapper, raw: str, expected_canonical: str) -> None:
    result = mapper.resolve(raw)
    assert result.canonical_symbol == expected_canonical
    assert result.asset_class == AssetClass.CRYPTO


def test_tradfi_alias_with_perpetual_suffix_still_resolves(mapper: SymbolMapper) -> None:
    """Ex.: 'NAS100.P' no TradingView -- deve cair no mesmo alias que 'NAS100'."""
    result = mapper.resolve("NAS100.P")
    assert result.canonical_symbol == "NAS100"
    assert result.asset_class == AssetClass.INDEX
