"""
providers/binance_provider.py
================================

Adapter: envolve o `BinanceClient` já existente (`api/binance_client.py`)
na interface comum `MarketDataProvider`, sem duplicar nenhuma lógica de
requisição HTTP. A Binance passa a ser só mais um provider — usado como
FALLBACK de cripto (a Bybit é o provider primário, conforme pedido no
Documento 1: "priorizar Bybit quando o ativo estiver disponível nela").
"""

from __future__ import annotations

from datetime import datetime

from api.binance_client import BinanceAPIError, BinanceClient
from models.candle import Candle
from providers.base import MarketDataError, MarketDataProvider, Quote


class BinanceProvider(MarketDataProvider):
    """Cripto via Binance Spot pública. Só atende `asset_class == "crypto"`."""

    name = "binance"

    def __init__(self, client: BinanceClient | None = None) -> None:
        self._client = client or BinanceClient()

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class == "crypto"

    def get_candles(
        self, canonical_symbol: str, timeframe: str, limit: int, end_time: datetime | None = None
    ) -> list[Candle]:
        end_ms = int(end_time.timestamp() * 1000) if end_time is not None else None
        try:
            raw = self._client.get_klines(
                symbol=canonical_symbol, timeframe=timeframe, limit=limit, end_time=end_ms
            )
        except BinanceAPIError as exc:
            raise MarketDataError(
                f"[{self.name}] falha ao buscar candles de {canonical_symbol} ({timeframe}): {exc}"
            ) from exc
        return [Candle.from_binance_raw(row) for row in raw]

    def get_quote(self, canonical_symbol: str) -> Quote:
        try:
            last_price = self._client.get_price(canonical_symbol)
        except BinanceAPIError as exc:
            raise MarketDataError(
                f"[{self.name}] falha ao buscar quote de {canonical_symbol}: {exc}"
            ) from exc
        # /ticker/price não expõe bid/ask/spread; /depth exigiria uma
        # segunda chamada — mantido fora daqui de propósito (ver
        # api/market_data.py::get_order_book para quem precisa do book).
        return Quote(
            canonical_symbol=canonical_symbol,
            provider=self.name,
            last_price=last_price,
            bid=None,
            ask=None,
            spread=None,
        )

    def close(self) -> None:
        self._client.close()
