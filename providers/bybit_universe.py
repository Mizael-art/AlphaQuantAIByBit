"""
providers/bybit_universe.py
=============================

Descoberta do universo completo de ativos negociáveis na Bybit
(perpétuos USDT, `category=linear`), com cache em memória.

Por que cache: a lista de instrumentos negociáveis muda poucas vezes
por dia (listagem/deslistagem de pares) -- refazer a paginação
completa de `instruments-info` a cada chamada de `/scan` seria
desperdício de tempo e de rate limit. O TTL é curto o suficiente para
pegar um novo par listado no mesmo dia, e longo o suficiente para não
pagar essa paginação em todo scan (`config.SCAN_UNIVERSE_CACHE_TTL_SECONDS`).

Este módulo NÃO decide filtro de liquidez/qualidade -- só "o que existe
para negociar". O filtro fica em `scanner/fast_filter.py`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from config import SCAN_UNIVERSE_CACHE_TTL_SECONDS
from providers.bybit_client import BybitAPIError, BybitClient

_lock = threading.Lock()
_cached_symbols: list[str] | None = None
_cached_at: float = 0.0


class UniverseUnavailableError(Exception):
    """Levantada quando não foi possível obter a lista de instrumentos da Bybit (e não há cache anterior utilizável)."""


def get_all_bybit_usdt_perpetuals(
    client: BybitClient | None = None, force_refresh: bool = False
) -> list[str]:
    """
    Retorna a lista cacheada de símbolos perpétuos USDT da Bybit.

    Args:
        client: instância opcional de `BybitClient` (injeção de
            dependência para testes). Se omitido, cria um cliente
            descartável só para esta chamada.
        force_refresh: ignora o cache e busca de novo, mesmo dentro do TTL.

    Raises:
        UniverseUnavailableError: a Bybit não respondeu E não há cache
            anterior para servir como fallback.
    """
    global _cached_symbols, _cached_at

    with _lock:
        is_fresh = _cached_symbols is not None and (time.time() - _cached_at) < SCAN_UNIVERSE_CACHE_TTL_SECONDS
        if is_fresh and not force_refresh:
            return list(_cached_symbols)  # type: ignore[arg-type]

        owns_client = client is None
        bybit_client = client or BybitClient()
        try:
            symbols = bybit_client.get_all_linear_usdt_symbols()
        except BybitAPIError as exc:
            if _cached_symbols is not None:
                # Degrada para o cache antigo em vez de derrubar o scan
                # inteiro por uma falha pontual de rede -- mesma filosofia
                # de "nunca inventar dado, mas também não travar por uma
                # instabilidade momentânea" já usada no ProviderRouter.
                return list(_cached_symbols)
            raise UniverseUnavailableError(
                f"Não foi possível obter a lista de símbolos da Bybit: {exc}"
            ) from exc
        finally:
            if owns_client:
                bybit_client.close()

        if not symbols:
            if _cached_symbols is not None:
                return list(_cached_symbols)
            raise UniverseUnavailableError("Bybit retornou uma lista vazia de instrumentos USDT perpétuos.")

        _cached_symbols = symbols
        _cached_at = time.time()
        return list(symbols)


@dataclass(frozen=True, slots=True)
class TickerSnapshot:
    """Campos do ticker relevantes para o pré-filtro rápido (Stage 1) e para reaproveitar como quote na Stage 2."""

    symbol: str
    last_price: float
    price_change_pct_24h: float
    high_24h: float
    low_24h: float
    turnover_24h_usdt: float
    volume_24h: float

    @property
    def range_pct_24h(self) -> float:
        """Amplitude 24h como % do preço atual -- proxy barato de volatilidade sem precisar de candles."""
        if self.last_price <= 0:
            return 0.0
        return (self.high_24h - self.low_24h) / self.last_price * 100


def get_bulk_ticker_snapshot(client: BybitClient | None = None) -> dict[str, TickerSnapshot]:
    """
    Busca o ticker de TODOS os perpétuos lineares em uma única chamada
    HTTP e devolve um dict `symbol -> TickerSnapshot`.

    Sem cache proposital (diferente do universo de símbolos): preço e
    volume mudam a cada segundo, então cada `/scan` deve pegar um
    snapshot fresco -- o ganho de performance aqui não vem de cachear,
    vem de ser 1 requisição para o mercado inteiro em vez de 1 por símbolo.
    """
    owns_client = client is None
    bybit_client = client or BybitClient()
    try:
        raw_tickers = bybit_client.get_all_tickers(category="linear")
    finally:
        if owns_client:
            bybit_client.close()

    snapshot: dict[str, TickerSnapshot] = {}
    for item in raw_tickers:
        symbol = item.get("symbol")
        if not symbol or not symbol.endswith("USDT"):
            continue
        try:
            last_price = float(item["lastPrice"])
            if last_price <= 0:
                continue
            snapshot[symbol] = TickerSnapshot(
                symbol=symbol,
                last_price=last_price,
                price_change_pct_24h=float(item.get("price24hPcnt") or 0.0) * 100,
                high_24h=float(item.get("highPrice24h") or last_price),
                low_24h=float(item.get("lowPrice24h") or last_price),
                turnover_24h_usdt=float(item.get("turnover24h") or 0.0),
                volume_24h=float(item.get("volume24h") or 0.0),
            )
        except (KeyError, ValueError, TypeError):
            continue  # ticker malformado para este símbolo -- ignora, não derruba o lote inteiro.

    return snapshot
