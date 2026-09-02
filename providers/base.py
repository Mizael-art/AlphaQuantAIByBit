"""
providers/base.py
==================

Interface comum que todo provider de Market Data deve implementar, e
as exceções do Market Data Layer.

Nenhum módulo acima deste (ProviderRouter, MarketData, indicators,
structure, etc.) deve importar um provider concreto diretamente — só
esta interface. Isso é o que garante que o restante do AlphaQuant não
sabe se o dado veio da Bybit, da Binance ou de qualquer outro lugar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from models.candle import Candle


class MarketDataError(Exception):
    """Erro genérico de um provider individual (rede, símbolo, resposta inesperada)."""


class DataUnavailableError(Exception):
    """
    Levantada pelo ProviderRouter quando NENHUM provider elegível
    conseguiu fornecer dados para o símbolo/timeframe solicitado.

    Esta é a exceção que deve propagar até a camada de decisão —
    nunca um preço estimado, candle inventado ou dado stale silencioso.
    """

    def __init__(self, symbol: str, timeframe: str, tried: list[str], reason: str = "") -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.tried = tried
        self.reason = reason
        detail = f" ({reason})" if reason else ""
        super().__init__(
            f"DATA_UNAVAILABLE para {symbol} ({timeframe}). "
            f"Providers tentados: {tried}{detail}."
        )


@dataclass(frozen=True, slots=True)
class Quote:
    """Preço atual normalizado (last/bid/ask/spread quando disponíveis)."""

    canonical_symbol: str
    provider: str
    last_price: float
    bid: float | None
    ask: float | None
    spread: float | None

    def to_dict(self) -> dict:
        return {
            "canonical_symbol": self.canonical_symbol,
            "provider": self.provider,
            "last_price": self.last_price,
            "bid": self.bid,
            "ask": self.ask,
            "spread": self.spread,
        }


class MarketDataProvider(ABC):
    """
    Interface que todo provider concreto (Bybit, Binance, futuros MT5,
    etc.) deve implementar.

    Um provider é propositalmente "burro": busca dados brutos do seu
    endpoint e devolve estruturas já normalizadas (`Candle`, `Quote`).
    Ele NÃO decide fallback, NÃO decide qual provider usar para qual
    ativo — isso é responsabilidade do `ProviderRouter`.
    """

    #: Nome curto e estável do provider, usado em logs, testes e no
    #: campo `data_source` do resultado final (ex.: "bybit_crypto").
    name: str

    @abstractmethod
    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        """Retorna True se este provider pode, em tese, atender esse ativo."""

    @abstractmethod
    def get_candles(
        self,
        canonical_symbol: str,
        timeframe: str,
        limit: int,
        end_time: "datetime | None" = None,
    ) -> list[Candle]:
        """
        Busca candles OHLCV e retorna já como `Candle` normalizado.

        Args:
            end_time: quando informado, busca candles com open_time
                anterior (ou igual) a este timestamp — usado para
                paginar histórico profundo (ver `backtest.history_fetcher`).
                Quando `None` (padrão), busca os candles mais recentes.
        """

    @abstractmethod
    def get_quote(self, canonical_symbol: str) -> Quote:
        """Busca o preço atual (e bid/ask/spread quando o provider oferecer)."""

    def close(self) -> None:  # pragma: no cover - default no-op
        """Encerra recursos de rede do provider (sessão HTTP etc.)."""
