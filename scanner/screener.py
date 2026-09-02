"""
scanner/screener.py
====================

Implementação da varredura multi-símbolo, em dois modos:

- `scan_market`: varre uma lista explícita de símbolos (watchlist fixa
  ou lista passada pelo usuário).
- `scan_universe`: varre TODOS os perpétuos USDT negociáveis na Bybit,
  em duas etapas -- filtro rápido de liquidez/atividade sem candles
  (Stage 1, `scanner/fast_filter.py`) seguido de análise completa só
  nos melhores candidatos (Stage 2). É o modo usado por
  `/scan?universe=all_bybit`.

Para cada símbolo, ambos os modos rodam `app.run_analysis` em DOIS
timeframes:

- `htf` (higher timeframe, padrão "4H"): dá o contexto/tendência,
  igual ao topo da hierarquia multi-timeframe (1D -> 4H -> 1H -> 15M)
  já usada no `/snapshot`.
- `ltf` (lower timeframe, padrão "1H"): mede a distância do preço
  atual até a zona de suporte/resistência mais próxima, e serve de
  timeframe de "gatilho" (execução).

Isso reaproveita 100% do pipeline já existente (indicadores,
estrutura, score) — não duplica lógica de análise, só orquestra em
lote e adiciona a métrica de "distância até a zona".

Performance: cada símbolo faz 2 requisições HTTP (klines HTF + klines
LTF; o ticker é buscado uma única vez para o mercado inteiro em
`scan_universe`, e não é mais buscado à toa dentro de `run_analysis`
-- ver `providers.router.ProviderRouter.get_market_data(fetch_quote=...)`).
Um único `ProviderRouter` (com sessão HTTP/pool de conexões
reaproveitado) é compartilhado por todas as threads do
`ThreadPoolExecutor` (`config.SCAN_CONCURRENCY`), em vez de cada
símbolo abrir sua própria conexão do zero.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from api.market_data import MarketData
from app import InsufficientDataError, run_analysis
from config import (
    SCAN_CONCURRENCY,
    SCAN_ENTRY_ZONE_PCT,
    SCAN_KLINES_LIMIT,
    SCAN_MIN_REWARD_RISK_RATIO,
    SCAN_MIN_REWARD_RUNWAY_PCT,
    SCAN_MIN_SCORE_ENTRY,
    SCAN_MIN_SCORE_WATCH,
    SCAN_STAGE1_MIN_TURNOVER_USDT,
    SCAN_STAGE1_TOP_N,
    SCAN_WATCH_ZONE_PCT,
)
from providers import DataUnavailableError, ProviderRouter, build_default_router
from providers.bybit_universe import (
    UniverseUnavailableError,
    get_all_bybit_usdt_perpetuals,
    get_bulk_ticker_snapshot,
)
from scanner.fast_filter import FastFilterEntry, rank_candidates


@dataclass(frozen=True, slots=True)
class ScanEntry:
    """Resultado condensado de um símbolo dentro do scan."""

    symbol: str
    status: str  # "zona_de_entrada" | "observar" | "fora_de_zona"
    price: float
    trend_htf: str
    trend_ltf: str
    trend_conflict: bool
    score_htf: int
    score_ltf: int
    nearest_zone_price: float | None
    nearest_zone_type: str | None  # "support" | "resistance"
    distance_to_zone_pct: float | None
    reward_zone_price: float | None
    reward_zone_type: str | None  # "support" | "resistance" -- do lado OPOSTO ao nearest_zone
    reward_distance_pct: float | None
    reward_risk_ratio: float | None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "price": self.price,
            "trend_htf": self.trend_htf,
            "trend_ltf": self.trend_ltf,
            "trend_conflict": self.trend_conflict,
            "score_htf": self.score_htf,
            "score_ltf": self.score_ltf,
            "nearest_zone_price": self.nearest_zone_price,
            "nearest_zone_type": self.nearest_zone_type,
            "distance_to_zone_pct": self.distance_to_zone_pct,
            "reward_zone_price": self.reward_zone_price,
            "reward_zone_type": self.reward_zone_type,
            "reward_distance_pct": self.reward_distance_pct,
            "reward_risk_ratio": self.reward_risk_ratio,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Resultado completo da varredura."""

    htf: str
    ltf: str
    symbols_requested: int
    symbols_analyzed: int
    errors: dict[str, str] = field(default_factory=dict)
    entry_zone: list[ScanEntry] = field(default_factory=list)
    watch: list[ScanEntry] = field(default_factory=list)
    out_of_zone: list[ScanEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "htf": self.htf,
            "ltf": self.ltf,
            "symbols_requested": self.symbols_requested,
            "symbols_analyzed": self.symbols_analyzed,
            "errors": self.errors,
            "entry_zone": [e.to_dict() for e in self.entry_zone],
            "watch": [e.to_dict() for e in self.watch],
            "out_of_zone": [e.to_dict() for e in self.out_of_zone],
            "disclaimer": (
                "Varredura pontual (snapshot no momento da chamada), não é "
                "monitoramento contínuo/push. Para atualizar, chame o scan "
                "novamente. 'zona_de_entrada' já exige espaço mínimo até a "
                "zona oposta (ver reward_distance_pct/reward_risk_ratio) -- "
                "mas nenhum item aqui é recomendação de entrada; aplique o "
                "Quality Filter e a gestão de risco normalmente."
            ),
        }


def _nearest_zone(
    price: float, support: list[float], resistance: list[float]
) -> tuple[float | None, str | None, float | None]:
    """Encontra o nível de suporte/resistência mais próximo do preço atual."""
    candidates: list[tuple[float, str]] = [(lvl, "support") for lvl in support]
    candidates += [(lvl, "resistance") for lvl in resistance]

    if not candidates or price <= 0:
        return None, None, None

    nearest_price, nearest_type = min(candidates, key=lambda item: abs(item[0] - price))
    distance_pct = round(abs(nearest_price - price) / price * 100, 3)
    return nearest_price, nearest_type, distance_pct


def _reward_zone(
    price: float,
    nearest_type: str | None,
    support: list[float],
    resistance: list[float],
) -> tuple[float | None, str | None, float | None]:
    """
    Encontra a zona OPOSTA mais próxima na direção do trade implícito por
    `nearest_type` -- ou seja, o alvo potencial, não o gatilho de entrada.

    Isso existe porque `_nearest_zone` sozinho responde só "o preço está
    perto de uma zona?", nunca "existe espaço até a próxima zona do lado
    oposto?". Um símbolo pode estar bem em cima de um suporte com uma
    resistência colada logo acima -- tecnicamente "na zona", mas sem
    nenhum espaço de sobra pra um trade valer a pena. Essa função é o que
    permite ao `_classify` rejeitar esse caso (ver `SCAN_MIN_REWARD_*`
    em `config.py`).

    Se `nearest_type == "support"`: viés é comprado, o alvo é a
    resistência mais próxima ACIMA do preço atual.
    Se `nearest_type == "resistance"`: viés é vendido, o alvo é o
    suporte mais próximo ABAIXO do preço atual.
    """
    if price <= 0 or nearest_type not in ("support", "resistance"):
        return None, None, None

    if nearest_type == "support":
        candidates = [lvl for lvl in resistance if lvl > price]
        if not candidates:
            return None, None, None
        target = min(candidates)
        distance_pct = round((target - price) / price * 100, 3)
        return target, "resistance", distance_pct

    candidates = [lvl for lvl in support if lvl < price]
    if not candidates:
        return None, None, None
    target = max(candidates)
    distance_pct = round((price - target) / price * 100, 3)
    return target, "support", distance_pct


def _classify(
    score_htf: int,
    score_ltf: int,
    distance_pct: float | None,
    trend_conflict: bool,
    reward_distance_pct: float | None,
) -> str:
    """Classifica o símbolo em zona_de_entrada / observar / fora_de_zona."""
    combined_score = round((score_htf + score_ltf) / 2)

    # Espaço até o alvo (zona oposta) tem que existir e ser
    # significativo -- caso contrário, mesmo com score alto e preço
    # bem posicionado, o trade não tem "para onde ir" (ver docstring
    # de `_reward_zone`). Isso objetiva a pergunta "existe espaço
    # suficiente até o alvo?" que antes só existia como texto solto nas
    # instruções do GPT, sem nenhum número por trás.
    has_reward_runway = (
        reward_distance_pct is not None and reward_distance_pct >= SCAN_MIN_REWARD_RUNWAY_PCT
    )
    reward_risk_ok = (
        has_reward_runway
        and distance_pct is not None
        and distance_pct > 0
        and (reward_distance_pct / distance_pct) >= SCAN_MIN_REWARD_RISK_RATIO
    )

    if (
        distance_pct is not None
        and distance_pct <= SCAN_ENTRY_ZONE_PCT
        and combined_score >= SCAN_MIN_SCORE_ENTRY
        and not trend_conflict
        and reward_risk_ok
    ):
        return "zona_de_entrada"

    if (distance_pct is not None and distance_pct <= SCAN_WATCH_ZONE_PCT) or (
        combined_score >= SCAN_MIN_SCORE_WATCH
    ):
        return "observar"

    return "fora_de_zona"


def _scan_one(
    symbol: str,
    htf: str,
    ltf: str,
    router: ProviderRouter,
    current_price: float | None = None,
) -> ScanEntry:
    symbol = symbol.strip().upper()

    # `router` (com as sessões HTTP dos providers) é compartilhado entre
    # todas as threads do scan -- ver `scan_market`/`scan_universe` --,
    # mas cada chamada usa seu PRÓPRIO `MarketData` (leve, não abre
    # conexão nova nenhuma). Isso é proposital: `MarketData.last_result`
    # é mutável, e `run_analysis` lê esse atributo depois de calcular os
    # indicadores. Se o `MarketData` fosse compartilhado entre threads,
    # uma thread poderia ler a proveniência (`data_source`) referente ao
    # símbolo de OUTRA thread que terminou no meio -- corrida de dados
    # silenciosa. Compartilhar o `router` já entrega o ganho real (reuso
    # de conexão TCP/TLS), sem esse risco.
    market_data = MarketData(router=router)

    # `current_price`, quando informado (Stage 2 do `scan_universe`, vindo
    # do snapshot de tickers em lote já buscado na Stage 1), evita mais
    # uma requisição de ticker por timeframe -- ver docstring de
    # `app.run_analysis`.
    result_htf = run_analysis(
        symbol=symbol, timeframe=htf, limit=SCAN_KLINES_LIMIT,
        market_data=market_data, current_price=current_price,
    )
    result_ltf = run_analysis(
        symbol=symbol, timeframe=ltf, limit=SCAN_KLINES_LIMIT,
        market_data=market_data, current_price=current_price,
    )

    price = result_ltf.price
    nearest_price, nearest_type, distance_pct = _nearest_zone(
        price, result_ltf.support + result_htf.support, result_ltf.resistance + result_htf.resistance
    )
    reward_price, reward_type, reward_distance_pct = _reward_zone(
        price, nearest_type,
        result_ltf.support + result_htf.support, result_ltf.resistance + result_htf.resistance,
    )
    reward_risk_ratio = (
        round(reward_distance_pct / distance_pct, 2)
        if reward_distance_pct is not None and distance_pct not in (None, 0)
        else None
    )

    trend_conflict = (
        result_htf.trend != "Ranging"
        and result_ltf.trend != "Ranging"
        and result_htf.trend != result_ltf.trend
    )

    status = _classify(result_htf.score, result_ltf.score, distance_pct, trend_conflict, reward_distance_pct)

    note = ""
    if trend_conflict:
        note = f"Conflito de tendência: {htf}={result_htf.trend} vs {ltf}={result_ltf.trend}."
    elif reward_distance_pct is not None and reward_risk_ratio is not None and reward_risk_ratio < SCAN_MIN_REWARD_RISK_RATIO:
        note = (
            f"Pouco espaço até o alvo oposto ({reward_distance_pct}%, "
            f"R:R~{reward_risk_ratio}) -- risco de trade sem espaço pra correr."
        )

    return ScanEntry(
        symbol=symbol,
        status=status,
        price=price,
        trend_htf=result_htf.trend,
        trend_ltf=result_ltf.trend,
        trend_conflict=trend_conflict,
        score_htf=result_htf.score,
        score_ltf=result_ltf.score,
        nearest_zone_price=nearest_price,
        nearest_zone_type=nearest_type,
        distance_to_zone_pct=distance_pct,
        reward_zone_price=reward_price,
        reward_zone_type=reward_type,
        reward_distance_pct=reward_distance_pct,
        reward_risk_ratio=reward_risk_ratio,
        note=note,
    )


def scan_market(
    symbols: list[str],
    htf: str = "4H",
    ltf: str = "1H",
    include_out_of_zone: bool = False,
) -> ScanResult:
    """
    Executa a varredura para uma lista de símbolos.

    Args:
        symbols: lista de pares, ex. ["BTCUSDT", "ETHUSDT", ...].
        htf: timeframe de contexto/tendência (padrão "4H").
        ltf: timeframe de gatilho/execução (padrão "1H").
        include_out_of_zone: se True, inclui também os símbolos sem
            setup (status "fora_de_zona") no retorno — por padrão eles
            ficam de fora para manter o JSON enxuto.

    Returns:
        `ScanResult` com os símbolos separados por status.
    """
    entries: list[ScanEntry] = []
    errors: dict[str, str] = {}

    # Um único router (e portanto uma única sessão HTTP por provider,
    # com pool de conexões dimensionado em `providers/bybit_client.py`)
    # para o scan inteiro -- antes, cada símbolo abria seu próprio
    # `ProviderRouter`/`BybitClient`/`BinanceClient` do zero via
    # `run_analysis(market_data=None)`, pagando handshake TCP/TLS novo a
    # cada chamada em vez de reaproveitar conexões keep-alive.
    router = build_default_router()
    try:
        with ThreadPoolExecutor(max_workers=SCAN_CONCURRENCY) as executor:
            futures = {
                executor.submit(_scan_one, symbol, htf, ltf, router): symbol for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    entries.append(future.result())
                except InsufficientDataError as exc:
                    errors[symbol] = str(exc)
                except Exception as exc:  # noqa: BLE001 - erro por símbolo não deve derrubar o scan inteiro.
                    errors[symbol] = f"Falha ao analisar {symbol}: {exc}"
    finally:
        router.close()

    entry_zone = sorted(
        (e for e in entries if e.status == "zona_de_entrada"),
        key=lambda e: (e.score_htf + e.score_ltf),
        reverse=True,
    )
    watch = sorted(
        (e for e in entries if e.status == "observar"),
        key=lambda e: (e.distance_to_zone_pct if e.distance_to_zone_pct is not None else 999),
    )
    out_of_zone = [e for e in entries if e.status == "fora_de_zona"] if include_out_of_zone else []

    return ScanResult(
        htf=htf,
        ltf=ltf,
        symbols_requested=len(symbols),
        symbols_analyzed=len(entries),
        errors=errors,
        entry_zone=entry_zone,
        watch=watch,
        out_of_zone=out_of_zone,
    )


@dataclass(frozen=True, slots=True)
class UniverseScanResult(ScanResult):
    """`ScanResult` + metadados de como o universo foi reduzido em duas etapas (transparência do funil, não é uma caixa-preta)."""

    universe_size: int = 0
    stage1_candidates: int = 0
    stage1_min_turnover_usdt: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        # Nota: `ScanResult.to_dict(self)` explícito, não `super().to_dict()`
        # -- com `@dataclass(slots=True)` em ambas as classes, o decorator
        # recria a classe (slots exige isso), o que invalida a célula
        # `__class__` usada pelo `super()` sem argumentos e quebra em
        # tempo de execução (`TypeError: super(type, obj): obj must be an
        # instance or subtype of type`). Chamar o método do pai
        # explicitamente evita esse problema conhecido de
        # dataclass+slots+herança.
        payload = ScanResult.to_dict(self)
        payload["universe_size"] = self.universe_size
        payload["stage1_candidates"] = self.stage1_candidates
        payload["stage1_min_turnover_usdt"] = self.stage1_min_turnover_usdt
        payload["disclaimer"] = (
            f"Varredura em duas etapas: {self.universe_size} pares USDT perpétuos "
            f"listados na Bybit -> {self.stage1_candidates} candidatos após filtro de "
            f"liquidez/atividade (Stage 1, sem candles) -> análise técnica completa "
            f"apenas nesses candidatos (Stage 2). Pontual (snapshot no momento da "
            f"chamada), não é monitoramento contínuo/push. Nenhum item aqui é "
            f"recomendação de entrada -- aplique o Quality Filter e a gestão de risco "
            f"normalmente."
        )
        return payload


def scan_universe(
    htf: str = "4H",
    ltf: str = "1H",
    top_n: int = SCAN_STAGE1_TOP_N,
    min_turnover_usdt: float = SCAN_STAGE1_MIN_TURNOVER_USDT,
    include_out_of_zone: bool = False,
) -> UniverseScanResult:
    """
    Varredura de DUAS ETAPAS sobre TODO o universo de perpétuos USDT da
    Bybit, em vez de uma watchlist fixa (`config.DEFAULT_SCAN_SYMBOLS`).

    Stage 1 (barata): busca a lista completa de símbolos negociáveis
    (cacheada, ver `providers.bybit_universe`) e o ticker de TODO o
    mercado em uma única chamada HTTP; usa só isso -- sem nenhum candle
    -- para descartar ativos ilíquidos e ficar com os `top_n` mais
    "ativos" (`scanner/fast_filter.py`).

    Stage 2 (cara): roda o pipeline completo de análise (mesmo
    `_scan_one`/`_classify` de `scan_market`) apenas nesses `top_n`
    candidatos, reaproveitando o preço já obtido na Stage 1 (evita
    buscar o ticker de novo por símbolo/timeframe).

    Args:
        htf, ltf, include_out_of_zone: mesmo significado de `scan_market`.
        top_n: quantos candidatos da Stage 1 recebem análise completa.
        min_turnover_usdt: piso de liquidez (turnover 24h) da Stage 1.

    Raises:
        UniverseUnavailableError: não foi possível obter a lista de
            instrumentos da Bybit (rede fora e sem cache anterior).
    """
    universe = get_all_bybit_usdt_perpetuals()
    tickers = get_bulk_ticker_snapshot()

    stage1_candidates: list[FastFilterEntry] = rank_candidates(
        tickers=tickers, universe=universe, top_n=top_n, min_turnover_usdt=min_turnover_usdt
    )
    price_by_symbol = {c.symbol: c.last_price for c in stage1_candidates}
    shortlist = list(price_by_symbol.keys())

    entries: list[ScanEntry] = []
    errors: dict[str, str] = {}

    router = build_default_router()
    try:
        with ThreadPoolExecutor(max_workers=SCAN_CONCURRENCY) as executor:
            futures = {
                executor.submit(
                    _scan_one, symbol, htf, ltf, router, price_by_symbol[symbol]
                ): symbol
                for symbol in shortlist
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    entries.append(future.result())
                except (InsufficientDataError, DataUnavailableError) as exc:
                    errors[symbol] = str(exc)
                except Exception as exc:  # noqa: BLE001 - erro por símbolo não deve derrubar o scan inteiro.
                    errors[symbol] = f"Falha ao analisar {symbol}: {exc}"
    finally:
        router.close()

    entry_zone = sorted(
        (e for e in entries if e.status == "zona_de_entrada"),
        key=lambda e: (e.score_htf + e.score_ltf),
        reverse=True,
    )
    watch = sorted(
        (e for e in entries if e.status == "observar"),
        key=lambda e: (e.distance_to_zone_pct if e.distance_to_zone_pct is not None else 999),
    )
    out_of_zone = [e for e in entries if e.status == "fora_de_zona"] if include_out_of_zone else []

    return UniverseScanResult(
        htf=htf,
        ltf=ltf,
        symbols_requested=len(shortlist),
        symbols_analyzed=len(entries),
        errors=errors,
        entry_zone=entry_zone,
        watch=watch,
        out_of_zone=out_of_zone,
        universe_size=len(universe),
        stage1_candidates=len(shortlist),
        stage1_min_turnover_usdt=min_turnover_usdt,
    )
