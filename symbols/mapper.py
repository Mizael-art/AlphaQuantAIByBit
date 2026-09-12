"""
symbols/mapper.py
==================

Módulo central de normalização de símbolos.

Todo símbolo que entra no sistema (vindo do usuário, do TradingView,
de um scan em lote) passa por aqui ANTES de qualquer chamada a um
provider. A responsabilidade deste módulo é puramente de mapeamento —
não faz nenhuma chamada de rede.

Conceitos:
    canonical_symbol: identidade única do ativo dentro do AlphaQuant,
        independente de provider (ex.: "XAUUSD", "BTCUSDT", "NAS100").
    asset_class: classe do ativo (CRYPTO, FOREX, METAL, INDEX). Decide
        quais providers são elegíveis no ProviderRouter.
    provider_symbol: como aquele canonical_symbol é escrito no
        provider específico (ex.: Bybit TradFi pode usar "XAUUSD+").

Se um provider precisar de um símbolo diferente do canonical, isso é
resolvido por `SymbolMapper.to_provider_symbol()` — nunca "adivinhado"
nas camadas de cima.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssetClass(str, Enum):
    """Classe do ativo. Decide quais providers podem atendê-lo."""

    CRYPTO = "crypto"
    FOREX = "forex"
    METAL = "metal"
    INDEX = "index"
    UNKNOWN = "unknown"


class SymbolNotRecognizedError(Exception):
    """Levantada quando um símbolo não pode ser mapeado para nenhuma asset class conhecida."""


@dataclass(frozen=True, slots=True)
class CanonicalSymbol:
    """Identidade normalizada de um ativo dentro do AlphaQuant."""

    canonical_symbol: str
    asset_class: AssetClass

    def to_dict(self) -> dict[str, str]:
        return {"canonical_symbol": self.canonical_symbol, "asset_class": self.asset_class.value}


# ----------------------------------------------------------------------
# TABELA DE ALIASES -> CANONICAL SYMBOL
# ----------------------------------------------------------------------
# Cada entrada mapeia variações conhecidas (sufixos de corretora, formatos
# com barra, etc.) para o canonical_symbol. Adicionar um novo alias aqui
# NUNCA requer tocar em nenhum outro módulo.
#
# IMPORTANTE: esta tabela cobre os aliases que temos evidência real de
# existirem (ex.: sufixo "+" usado pela Bybit TradFi em metais/índices,
# conforme documentação pública). Não inventamos sufixos de corretoras
# que não pesquisamos.
_ALIASES: dict[str, str] = {
    # Metais
    "XAUUSD": "XAUUSD", "XAUUSD+": "XAUUSD", "XAUUSD.S": "XAUUSD", "XAUUSDT": "XAUUSD",
    "XAGUSD": "XAGUSD", "XAGUSD+": "XAGUSD", "XAGUSD.S": "XAGUSD",
    # Índices
    "NAS100": "NAS100", "NAS100+": "NAS100", "USTEC": "NAS100", "USTEC.S": "NAS100",
    "US30": "US30", "US30+": "US30",
    "SPX500": "SPX500", "SPX500+": "SPX500", "US500": "SPX500", "US500+": "SPX500",
    # Forex majors (lista mínima; expandir sob demanda, não por antecipação)
    "EURUSD": "EURUSD", "EURUSD+": "EURUSD", "EURUSD.S": "EURUSD",
    "GBPUSD": "GBPUSD", "GBPUSD+": "GBPUSD", "GBPUSD.S": "GBPUSD",
    "USDJPY": "USDJPY", "USDJPY+": "USDJPY", "USDJPY.S": "USDJPY",
}

# canonical_symbol -> asset_class
_ASSET_CLASS_BY_CANONICAL: dict[str, AssetClass] = {
    "XAUUSD": AssetClass.METAL,
    "XAGUSD": AssetClass.METAL,
    "NAS100": AssetClass.INDEX,
    "US30": AssetClass.INDEX,
    "SPX500": AssetClass.INDEX,
    "EURUSD": AssetClass.FOREX,
    "GBPUSD": AssetClass.FOREX,
    "USDJPY": AssetClass.FOREX,
}

# Sufixos de moeda de cotação que caracterizam um par cripto contra
# stablecoin/BTC quando o símbolo não está na tabela de aliases acima.
_CRYPTO_QUOTE_SUFFIXES: tuple[str, ...] = ("USDT", "USDC", "BUSD", "BTC", "ETH", "FDUSD")


def _strip_slash(raw: str) -> str:
    """Remove separadores tipo 'BTC/USDT' -> 'BTCUSDT'."""
    return raw.replace("/", "").replace("-", "").replace("_", "")


# Sufixos de notação do TradingView que indicam o TIPO de contrato, não
# um ativo diferente. Na API real das exchanges (ex.: Bybit V5), essa
# distinção é feita por parâmetro (`category=linear` vs. `category=spot`),
# nunca por sufixo no símbolo -- "CLUSDT.P" no gráfico do TradingView e
# "CLUSDT" na API da Bybit (category=linear) são o MESMO ativo. Remover
# aqui evita que qualquer símbolo colado direto de um gráfico do
# TradingView (o fluxo mais comum de uso real) seja rejeitado como
# "não reconhecido".
_TRADINGVIEW_CONTRACT_SUFFIXES: tuple[str, ...] = (".P",)


def _normalize_raw(raw_symbol: str) -> str:
    """
    Normaliza um símbolo bruto (usuário, TradingView, webhook) antes de
    resolvê-lo: maiúsculas, sem espaços, sem prefixo de exchange
    ('BYBIT:CLUSDT.P' -> 'CLUSDT.P'), sem separadores ('BTC/USDT' ->
    'BTCUSDT') e sem sufixo de tipo de contrato do TradingView
    ('CLUSDT.P' -> 'CLUSDT').
    """
    text = raw_symbol.strip().upper()

    # Prefixo de exchange no formato TradingView: "BYBIT:CLUSDT.P".
    if ":" in text:
        text = text.split(":", 1)[1]

    text = _strip_slash(text)

    for suffix in _TRADINGVIEW_CONTRACT_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break

    return text


class SymbolMapper:
    """
    Normaliza símbolos vindos de qualquer origem (usuário, webhook,
    scan) para um `CanonicalSymbol` (canonical_symbol + asset_class).

    Não faz nenhuma chamada de rede. Puramente determinístico e testável.
    """

    def resolve(self, raw_symbol: str) -> CanonicalSymbol:
        """
        Resolve um símbolo bruto para sua forma canônica.

        Raises:
            SymbolNotRecognizedError: se o símbolo não corresponder a
                nenhum alias conhecido nem ao padrão de par cripto
                (BASE + sufixo de quote conhecido).
        """
        if not raw_symbol or not raw_symbol.strip():
            raise SymbolNotRecognizedError("Símbolo vazio.")

        cleaned = _normalize_raw(raw_symbol)

        # 1) Alias explícito (TradFi principalmente).
        if cleaned in _ALIASES:
            canonical = _ALIASES[cleaned]
            asset_class = _ASSET_CLASS_BY_CANONICAL.get(canonical, AssetClass.UNKNOWN)
            return CanonicalSymbol(canonical_symbol=canonical, asset_class=asset_class)

        # 2) Padrão de par cripto: termina com um quote asset conhecido
        #    e tem uma base não vazia antes dele (ex.: BTCUSDT, SOLUSDT).
        for quote in _CRYPTO_QUOTE_SUFFIXES:
            if cleaned.endswith(quote) and len(cleaned) > len(quote):
                return CanonicalSymbol(canonical_symbol=cleaned, asset_class=AssetClass.CRYPTO)

        raise SymbolNotRecognizedError(
            f"Símbolo '{raw_symbol}' não reconhecido. Não é um par cripto conhecido "
            f"(sufixos aceitos: {_CRYPTO_QUOTE_SUFFIXES}) nem está na tabela de aliases "
            f"TradFi. Adicione o alias em symbols/mapper.py se for um ativo válido."
        )

    def to_provider_symbol(self, canonical_symbol: str, provider_name: str) -> str:
        """
        Traduz um canonical_symbol para o formato esperado por um
        provider específico.

        Por padrão, o provider_symbol é igual ao canonical_symbol —
        overrides específicos (ex.: Bybit TradFi usando "XAUUSD+")
        entram aqui de forma explícita, nunca por adivinhação em tempo
        de execução.
        """
        overrides: dict[tuple[str, str], str] = {
            # Exemplo de override real, documentado pela Bybit (símbolos
            # de metais TradFi usam sufixo "+"). Ajustar/expandir aqui
            # somente após confirmação com a API real.
            ("XAUUSD", "bybit_tradfi"): "XAUUSD+",
            ("XAGUSD", "bybit_tradfi"): "XAGUSD+",
        }
        return overrides.get((canonical_symbol, provider_name), canonical_symbol)
