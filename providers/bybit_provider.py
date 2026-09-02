"""
providers/bybit_provider.py
=============================

Providers Bybit, implementando a interface `MarketDataProvider`.

Duas classes, deliberadamente separadas (Documento 1 pediu para não
assumir que todos os ativos da Bybit usam a mesma API/endpoint):

- `BybitCryptoProvider`: cripto Spot/Linear via `category=spot|linear`
  da API V5. **Confirmado** pela documentação oficial.
- `BybitTradFiProvider`: XAUUSD/NAS100/etc. **EXPERIMENTAL** — a Bybit
  V5 não documenta oficialmente um `category` para TradFi. Este
  provider tenta `category="linear"` com o símbolo mapeado (ex.:
  "XAUUSD+"), que é o comportamento relatado por SDKs não-oficiais,
  mas isso NÃO foi validado contra a API real neste ambiente (sem
  acesso de rede a api.bybit.com no sandbox de desenvolvimento).

  Antes de usar este provider em produção: rode
  `BybitTradFiProvider(...).supports("XAUUSD", "metal")` manualmente
  com sua conta/API e confirme que retorna True. Se retornar False (ou
  lançar erro), o ProviderRouter simplesmente pula este provider e cai
  no próximo — o sistema nunca finge que funcionou.
"""

from __future__ import annotations

from datetime import datetime

from models.candle import Candle
from providers.base import MarketDataError, MarketDataProvider, Quote
from providers.bybit_client import BYBIT_INTERVAL_MAP, BybitAPIError, BybitClient
from symbols.mapper import SymbolMapper

_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1H": 3_600_000, "2H": 7_200_000, "4H": 14_400_000, "6H": 21_600_000, "12H": 43_200_000,
    "1D": 86_400_000, "1W": 604_800_000, "1M": 2_592_000_000,
}


class _BybitProviderBase(MarketDataProvider):
    """Compartilha lógica comum de conversão candle/quote entre as duas variantes Bybit."""

    category: str

    def __init__(self, client: BybitClient | None = None, mapper: SymbolMapper | None = None) -> None:
        self._client = client or BybitClient()
        self._mapper = mapper or SymbolMapper()

    def _provider_symbol(self, canonical_symbol: str) -> str:
        return self._mapper.to_provider_symbol(canonical_symbol, self.name)

    def get_candles(
        self, canonical_symbol: str, timeframe: str, limit: int, end_time: datetime | None = None
    ) -> list[Candle]:
        if timeframe not in BYBIT_INTERVAL_MAP:
            raise ValueError(
                f"Timeframe '{timeframe}' não suportado pela Bybit. "
                f"Valores aceitos: {list(BYBIT_INTERVAL_MAP.keys())}"
            )

        provider_symbol = self._provider_symbol(canonical_symbol)
        interval = BYBIT_INTERVAL_MAP[timeframe]
        end_ms = int(end_time.timestamp() * 1000) if end_time is not None else None

        try:
            raw = self._client.get_kline(
                category=self.category, symbol=provider_symbol, interval=interval,
                limit=limit, end=end_ms,
            )
        except BybitAPIError as exc:
            raise MarketDataError(
                f"[{self.name}] falha ao buscar candles de {provider_symbol} ({timeframe}): {exc}"
            ) from exc

        interval_ms = _INTERVAL_MS.get(timeframe, 0)
        candles = [Candle.from_bybit_raw(row, interval_ms) for row in raw]
        # Bybit retorna do mais recente para o mais antigo — inverte para ordem cronológica.
        candles.reverse()
        return candles

    def get_quote(self, canonical_symbol: str) -> Quote:
        provider_symbol = self._provider_symbol(canonical_symbol)
        try:
            ticker = self._client.get_tickers(category=self.category, symbol=provider_symbol)
        except BybitAPIError as exc:
            raise MarketDataError(
                f"[{self.name}] falha ao buscar quote de {provider_symbol}: {exc}"
            ) from exc

        last_price = float(ticker["lastPrice"])
        bid = float(ticker["bid1Price"]) if ticker.get("bid1Price") not in (None, "") else None
        ask = float(ticker["ask1Price"]) if ticker.get("ask1Price") not in (None, "") else None
        spread = (ask - bid) if (bid is not None and ask is not None) else None

        return Quote(
            canonical_symbol=canonical_symbol,
            provider=self.name,
            last_price=last_price,
            bid=bid,
            ask=ask,
            spread=spread,
        )

    def close(self) -> None:
        self._client.close()


class BybitCryptoProvider(_BybitProviderBase):
    """
    Cripto via Bybit V5 (`category=linear`, contratos perpétuos
    USDT-M — mesma cobertura de pares que a Binance Futures, e o
    mercado mais líquido da Bybit). Confirmado pela documentação
    oficial V5.
    """

    name = "bybit_crypto"
    category = "linear"

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class == "crypto"


class BybitTradFiProvider(_BybitProviderBase):
    """
    XAUUSD/NAS100/EURUSD/etc. via Bybit — EXPERIMENTAL, ver docstring
    do módulo. `category="linear"` é uma tentativa, não uma garantia.
    """

    name = "bybit_tradfi"
    category = "linear"

    def supports(self, canonical_symbol: str, asset_class: str) -> bool:
        return asset_class in ("forex", "metal", "index")
