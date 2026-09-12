"""
derivatives/snapshot.py
=========================

Agrega os dados de derivativos (Open Interest, Funding Rate, Long/Short
Ratio) em uma única estrutura, pronta para entrar no Market Snapshot
final.

Como nem todo par tem contrato futuro na Binance, esta camada trata a
ausência de dados de forma graciosa: se o símbolo não existir em
Futures, retorna um snapshot com `available=False` em vez de quebrar
toda a análise (afinal, derivativos são um complemento, não um
requisito da análise Spot).
"""

from __future__ import annotations

from dataclasses import dataclass

from api.binance_client import BinanceAPIError
from derivatives.binance_futures_client import BinanceFuturesClient


@dataclass(frozen=True, slots=True)
class DerivativesSnapshot:
    """Snapshot dos principais dados de derivativos de um símbolo."""

    available: bool
    open_interest: float | None = None
    open_interest_notional_estimate: float | None = None  # OI * mark_price (aprox.)
    funding_rate_pct: float | None = None
    mark_price: float | None = None
    index_price: float | None = None
    global_long_short_ratio: float | None = None   # >1 = mais contas long do que short
    top_trader_long_short_ratio: float | None = None
    unavailable_reason: str | None = None

    def to_dict(self) -> dict:
        if not self.available:
            return {"available": False, "reason": self.unavailable_reason}

        return {
            "available": True,
            "open_interest": self.open_interest,
            "open_interest_notional_estimate": (
                round(self.open_interest_notional_estimate, 2)
                if self.open_interest_notional_estimate is not None
                else None
            ),
            "funding_rate_pct": round(self.funding_rate_pct, 6) if self.funding_rate_pct is not None else None,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "global_long_short_ratio": self.global_long_short_ratio,
            "top_trader_long_short_ratio": self.top_trader_long_short_ratio,
        }


def build_derivatives_snapshot(
    symbol: str, client: BinanceFuturesClient | None = None
) -> DerivativesSnapshot:
    """
    Monta o snapshot completo de derivativos para um símbolo, usando os
    endpoints públicos da Binance Futures.

    Args:
        symbol: par de negociação, ex.: "ETHUSDT". Deve existir como
            contrato perpétuo USDT-M na Binance Futures.
        client: instância opcional de `BinanceFuturesClient` (injeção
            de dependência, útil em testes).

    Returns:
        `DerivativesSnapshot`. Se o símbolo não tiver contrato futuro
        (ou a Binance Futures estiver indisponível), retorna um
        snapshot com `available=False`.
    """
    futures_client = client or BinanceFuturesClient()

    try:
        open_interest_data = futures_client.get_open_interest(symbol)
        premium_index_data = futures_client.get_premium_index(symbol)
        global_ratio_data = futures_client.get_global_long_short_ratio(symbol, period="1h", limit=1)
        top_ratio_data = futures_client.get_top_long_short_position_ratio(symbol, period="1h", limit=1)
    except BinanceAPIError as exc:
        return DerivativesSnapshot(available=False, unavailable_reason=str(exc))

    open_interest = float(open_interest_data.get("openInterest", 0.0))
    mark_price = float(premium_index_data.get("markPrice", 0.0))
    index_price = float(premium_index_data.get("indexPrice", 0.0))
    funding_rate_pct = float(premium_index_data.get("lastFundingRate", 0.0)) * 100

    global_ratio = float(global_ratio_data[0]["longShortRatio"]) if global_ratio_data else None
    top_ratio = float(top_ratio_data[0]["longShortRatio"]) if top_ratio_data else None

    return DerivativesSnapshot(
        available=True,
        open_interest=open_interest,
        open_interest_notional_estimate=open_interest * mark_price if mark_price else None,
        funding_rate_pct=funding_rate_pct,
        mark_price=mark_price,
        index_price=index_price,
        global_long_short_ratio=global_ratio,
        top_trader_long_short_ratio=top_ratio,
    )
