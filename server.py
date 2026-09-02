"""
server.py
=========

API HTTP (FastAPI) do AlphaQuant Engine -- é isto que o AlphaQuant X
(GPT customizado / outro consumidor) chama via Action/HTTP.

Endpoints:
    GET /snapshot   -- Market Snapshot multi-timeframe completo
                        (indicadores + estrutura + SMC + volume
                        profile + estatística + derivativos +
                        confluência + consenso multi-exchange).
                        Este é o endpoint principal.
    GET /analyze    -- análise de um único timeframe (compat. Fase 1).
    GET /scan       -- varredura multi-símbolo (scanner/).
    GET /health     -- health check.
    GET /openapi.json -- schema OpenAPI (gerado automaticamente pelo
                        FastAPI), usado para configurar a Action do GPT.

Nota de reconstrução: este arquivo veio vazio (0 bytes) no zip
`AlphaQuantEngine_v2_6_structure_consensus`. Foi reconstruído a partir
do README (seção "Uso") e das assinaturas reais de
`snapshot.build_market_snapshot`, `app.run_analysis` e
`scanner.scan_market` -- ver CHANGELOG_v2.6_rebuild.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from app import InsufficientDataError, run_analysis
from backtest.costs import CostModel
from backtest.history_fetcher import HistoryFetcher, HistoryFetchError
from backtest.performance import calculate_performance
from backtest.registry import StrategyNotRegisteredError, available_strategies, build_strategy
from backtest.simulator import BacktestSimulator
from strategy_dsl.errors import StrategyDslError
from strategy_dsl.executor import run_generic_backtest, schema_capabilities
from persistence.db import session_scope
from setups.expiration import sweep_expired
from setups.lifecycle import InvalidTransitionError, UnknownStatusError
from setups.memory import upsert_setup
from setups.repository import get_changed_since, list_setups
from setups.schema import SetupCandidate
from discovery.engine import scan_opportunities
from risk.capital_allocation import classify_capital_priority
from risk.engine import ProposedTrade, evaluate_trade_risk
from risk.repository import (
    build_risk_limits,
    build_risk_state,
    close_position,
    get_or_create_account,
    list_open_positions,
    open_position,
)
from risk.ruin import estimate_risk_of_ruin
from learning.classification import classify_signal, compute_quality_score
from learning.hypotheses import build_hypotheses
from learning.reconstruction import reconstruct_context
from learning.repository import create_signal, get_signal, list_signals, update_signal_result
from learning.schema import ExternalSignalInput, SignalResultUpdate
from decision.engine import evaluate_decision
from decision.mentor_block import build_mentor_block
from scoring.engine import compute_opportunity_score
from monitoring.service import run_monitoring_cycle
from optimization.monte_carlo import run_monte_carlo
from optimization.parameter_sweep import run_parameter_sweep
from optimization.portfolio import select_best_combination
from optimization.walk_forward import run_walk_forward
from config import (
    DEFAULT_SCAN_HTF,
    DEFAULT_SCAN_LTF,
    DEFAULT_SCAN_SYMBOLS,
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
    SCAN_BACKGROUND_KEY,
    SCAN_MAX_SYMBOLS,
    SCAN_STAGE1_MIN_TURNOVER_USDT,
    SCAN_STAGE1_TOP_N,
)
from persistence.scan_snapshot import load_scan_snapshot
from providers import DataUnavailableError, build_default_router
from providers.bybit_universe import UniverseUnavailableError
from scanner.background_loop import start_background_loop
from scanner.screener import scan_market, scan_universe
from snapshot.market_snapshot import DEFAULT_TIMEFRAMES, build_market_snapshot


class FlexibleJSONResponse(Response):
    """
    Resposta JSON que não recorta o schema OpenAPI a um `response_model`
    fixo (`additionalProperties: true` implícito) -- o payload varia
    conforme timeframes/erros/consenso multi-exchange disponíveis, e
    engessar um schema aqui obrigaria a reimportar a Action do GPT a
    cada campo novo adicionado nos motores internos.
    """

    media_type = "application/json"

    def render(self, content) -> bytes:  # noqa: ANN001 - assinatura herdada do Starlette.
        return json.dumps(content, ensure_ascii=False, default=str).encode("utf-8")


# Endpoints que usam FlexibleJSONResponse não têm um shape fixo -- por
# isso não declaram `response_model`. Sem isso, o FastAPI não consegue
# inferir o schema OpenAPI da resposta e cai em `{"type": "string"}`
# (trata como corpo opaco). O validador de schema do ChatGPT Actions
# aceita objeto livre, mas exige a chave `properties` presente mesmo
# quando vazia -- só `additionalProperties: true` sozinho é rejeitado
# ("object schema missing properties"). Este override documenta
# corretamente "isto é um objeto JSON, com campos variáveis" nos 4
# endpoints de payload dinâmico.
_FREEFORM_JSON_OBJECT_RESPONSES: dict[int | str, dict] = {
    200: {
        "description": "Successful Response",
        "content": {
            "application/json": {
                "schema": {"type": "object", "properties": {}, "additionalProperties": True}
            }
        },
    }
}


class HealthResponse(BaseModel):
    status: str


class BacktestStrategiesResponse(BaseModel):
    strategies: list[str]


app = FastAPI(
    title="AlphaQuant Engine",
    description=(
        "Backend de dados de mercado (Spot + Futures + multi-exchange) "
        "para o AlphaQuant X: indicadores técnicos, estrutura de "
        "mercado, Smart Money Concepts, Volume Profile, estatística, "
        "derivativos e consenso multi-exchange (preço e estrutura), "
        "consumidos sem depender de prints de gráfico."
    ),
    version="2.6",
    servers=[{"url": "https://alphaquantaibybit.onrender.com", "description": "Produção (Render)"}],
)


@app.on_event("startup")
def _start_background_scan_loop() -> None:
    """
    Inicia o scan de universo completo em loop de fundo (ver
    `scanner/background_loop.py`). Roda uma vez por processo -- se o
    Render hibernar e um serviço de keep-alive (UptimeRobot ou
    similar) acordar o processo de novo, este startup event dispara
    de novo e reinicia o loop do zero.

    IMPORTANTE: pressupõe 1 único worker (ver aviso em
    `start_background_loop`). Se `RENDER` (ou qualquer variável que
    indique múltiplos workers) não estiver configurado para >1, isso é
    seguro por padrão.
    """
    start_background_loop()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check simples -- não toca em nenhuma API externa. Alvo do ping do serviço de keep-alive (UptimeRobot ou similar)."""
    return HealthResponse(status="ok")


@app.get("/scan/latest", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_scan_latest(
    scan_key: str = Query(
        default=SCAN_BACKGROUND_KEY,
        description="Chave do scan de fundo a ler (formato 'universe:htf:ltf'). Use o padrão a menos que múltiplos loops tenham sido configurados.",
    ),
) -> dict:
    """
    Lê o resultado mais recente do scan de universo completo, calculado
    por um loop de fundo contínuo -- NÃO dispara nenhum scan novo,
    responde em milissegundos a partir do que já está no banco.

    Prefira este endpoint a `/scan?universe=all_bybit` para qualquer
    busca ampla no mercado: o resultado pode ter alguns segundos/minutos
    de idade (`age_seconds` no retorno), mas nunca corre risco de
    timeout, e nunca faz o usuário esperar minutos pela resposta.

    Retorna 503 se o loop de fundo ainda não completou nenhum ciclo
    (processo acabou de subir) -- nesse caso, `/scan?universe=all_bybit`
    ainda funciona como fallback pontual (mais lento, mas não depende
    do loop já ter rodado).
    """
    snapshot = load_scan_snapshot(scan_key)
    if snapshot is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Nenhum scan de fundo completou ainda para esta scan_key "
                "(processo pode ter acabado de subir). Tente novamente em "
                "alguns segundos, ou use /scan?universe=all_bybit como "
                "fallback pontual enquanto isso."
            ),
        )
    return snapshot


@app.get("/snapshot", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_snapshot(
    symbol: str = Query(default=DEFAULT_SYMBOL, description="Par de negociação, ex.: ETHUSDT."),
    timeframes: str = Query(
        default=",".join(DEFAULT_TIMEFRAMES),
        description="Timeframes separados por vírgula, ex.: 15m,1H,4H,1D.",
    ),
) -> dict:
    """
    Market Snapshot completo: indicadores, estrutura, SMC, volume
    profile, estatística, derivativos, confluência multi-timeframe e
    (quando habilitado em `config.ENABLE_CROSS_EXCHANGE`) consenso
    multi-exchange de preço e estrutura. **Endpoint principal.**
    """
    tf_tuple = tuple(tf.strip() for tf in timeframes.split(",") if tf.strip())
    try:
        result = build_market_snapshot(symbol=symbol, timeframes=tf_tuple)
    except Exception as exc:  # noqa: BLE001 - erro de topo, reportado como HTTP 502.
        raise HTTPException(status_code=502, detail=f"Falha ao gerar snapshot: {exc}") from exc

    return result.to_dict()


@app.get("/analyze", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_analyze(
    symbol: str = Query(default=DEFAULT_SYMBOL, description="Par de negociação, ex.: ETHUSDT."),
    timeframe: str = Query(default=DEFAULT_TIMEFRAME, description="Timeframe único, ex.: 4H."),
) -> dict:
    """Análise de um único timeframe -- mantido por compatibilidade (escopo da Fase 1)."""
    try:
        result = run_analysis(symbol=symbol, timeframe=timeframe)
    except InsufficientDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Falha ao gerar análise: {exc}") from exc

    return result.to_dict()


@app.get("/scan", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_scan(
    symbols: str | None = Query(
        default=None,
        description=(
            f"Símbolos separados por vírgula (padrão: watchlist de {len(DEFAULT_SCAN_SYMBOLS)} "
            f"ativos). Ignorado se universe=all_bybit."
        ),
    ),
    universe: str = Query(
        default="watchlist",
        description=(
            "'watchlist': usa `symbols` ou a watchlist fixa. "
            "'all_bybit': varre TODOS os perpétuos USDT da Bybit em 2 "
            "etapas (filtro rápido de liquidez/atividade, depois "
            "análise completa só nos melhores candidatos via `top_n`)."
        ),
    ),
    top_n: int = Query(
        default=SCAN_STAGE1_TOP_N,
        ge=1,
        le=150,
        description="Com universe=all_bybit: quantos candidatos recebem análise completa após o filtro rápido.",
    ),
    min_turnover_usdt: float = Query(
        default=SCAN_STAGE1_MIN_TURNOVER_USDT,
        ge=0,
        description="Com universe=all_bybit: piso de liquidez (turnover 24h em USDT) para um ativo entrar no filtro rápido.",
    ),
    htf: str = Query(default=DEFAULT_SCAN_HTF, description="Timeframe de contexto/tendência."),
    ltf: str = Query(default=DEFAULT_SCAN_LTF, description="Timeframe de gatilho/execução."),
    include_out_of_zone: bool = Query(default=False, description="Inclui também símbolos sem setup no retorno."),
) -> dict:
    """Varredura multi-símbolo pontual -- ver `scanner/screener.py` para a lógica de classificação."""
    if universe == "all_bybit":
        try:
            result = scan_universe(
                htf=htf, ltf=ltf, top_n=top_n, min_turnover_usdt=min_turnover_usdt,
                include_out_of_zone=include_out_of_zone,
            )
        except UniverseUnavailableError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return result.to_dict()

    if universe != "watchlist":
        raise HTTPException(
            status_code=422, detail=f"universe inválido: '{universe}'. Use 'watchlist' ou 'all_bybit'."
        )

    symbol_list = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if symbols
        else DEFAULT_SCAN_SYMBOLS
    )
    if len(symbol_list) > SCAN_MAX_SYMBOLS:
        raise HTTPException(
            status_code=422,
            detail=f"Máximo de {SCAN_MAX_SYMBOLS} símbolos por chamada, {len(symbol_list)} recebidos.",
        )

    result = scan_market(symbol_list, htf=htf, ltf=ltf, include_out_of_zone=include_out_of_zone)
    return result.to_dict()


# ----------------------------------------------------------------------
# Backtest
# ----------------------------------------------------------------------
# O motor de backtest (backtest/) já existia completo (HistoryFetcher,
# BacktestSimulator, Strategy, calculate_performance) mas não tinha
# NENHUM endpoint HTTP -- por isso o GPT não conseguia rodar backtest:
# não havia como chamar isso via Action. Os dois endpoints abaixo
# fecham esse buraco.


class BacktestCostModelRequest(BaseModel):
    """Custos de execução (bps). Default é zero em cada campo -- ver `backtest/costs.py`: um backtest sem custo informado é reportado como resultado BRUTO, nunca com fricção "realista" inventada."""

    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0


class BacktestRequest(BaseModel):
    symbol: str = Field(description="Par de negociação, ex.: ETHUSDT. Aceita formato TradingView (ex.: 'BYBIT:ETHUSDT.P').")
    timeframe: str = Field(description="Timeframe dos candles do backtest, ex.: 1H, 4H, 1D.")
    start: datetime = Field(description="Início do range histórico (ISO 8601).")
    end: datetime | None = Field(default=None, description="Fim do range histórico (padrão: agora).")
    strategy: str = Field(default="sma_cross", description="Nome da estratégia registrada. Ver GET /backtest/strategies.")
    strategy_params: dict[str, Any] = Field(default_factory=dict, description="Parâmetros da estratégia (ex.: {\"fast_period\": 10}).")
    cost_model: BacktestCostModelRequest = Field(default_factory=BacktestCostModelRequest)
    min_candles: int = Field(default=50, description="Mínimo de candles exigido no range -- abaixo disso, erro em vez de rodar com amostra insuficiente.")

    @field_validator("start", "end")
    @classmethod
    def _assume_utc_when_naive(cls, value: datetime | None) -> datetime | None:
        """
        O GPT frequentemente envia datas sem offset (ex.: "2026-07-01T00:00:00",
        sem "Z" nem "+00:00"). Sem isso, essa data chega "naive" e quebra em
        `TypeError: can't compare offset-naive and offset-aware datetimes`
        assim que é comparada contra `Candle.open_time` (sempre UTC-aware) --
        um 500 genérico, não um 422 com motivo. Todo dado de candle deste
        projeto é UTC (ver `models/candle.py`), então assumir UTC para uma
        data sem timezone é o comportamento correto, não uma adivinhação.
        """
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


@app.get("/backtest/strategies", response_model=BacktestStrategiesResponse)
def get_backtest_strategies() -> BacktestStrategiesResponse:
    """Lista as estratégias registradas e utilizáveis no campo `strategy` de POST /backtest."""
    return BacktestStrategiesResponse(strategies=available_strategies())


@app.post("/backtest", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_backtest(request: BacktestRequest) -> dict:
    """Roda backtest bar-a-bar (sem lookahead) de uma estratégia registrada sobre histórico real. Retorna performance (win rate, R médio, profit factor, drawdown) e trades. Erros de dados voltam como HTTP 422 com o motivo, nunca resultado parcial."""
    try:
        strategy = build_strategy(request.strategy, request.strategy_params)
    except StrategyNotRegisteredError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    cost_model = CostModel(
        spread_bps=request.cost_model.spread_bps,
        slippage_bps=request.cost_model.slippage_bps,
        commission_bps=request.cost_model.commission_bps,
    )

    fetcher = HistoryFetcher(router=build_default_router())
    try:
        history = fetcher.fetch(
            symbol=request.symbol,
            timeframe=request.timeframe,
            start=request.start,
            end=request.end,
            min_candles=request.min_candles,
        )
    except (HistoryFetchError, DataUnavailableError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Falha ao buscar histórico: {exc}") from exc

    simulator = BacktestSimulator(strategy=strategy, cost_model=cost_model)
    try:
        trades = simulator.run(history.candles)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Falha ao simular estratégia: {exc}") from exc

    performance = calculate_performance(trades) if trades else None

    return {
        "meta": history.to_meta_dict(),
        "strategy": {"name": strategy.name, "params": request.strategy_params},
        "cost_model": {
            "is_zero_cost": cost_model.is_zero_cost,
            "spread_bps": cost_model.spread_bps,
            "slippage_bps": cost_model.slippage_bps,
            "commission_bps": cost_model.commission_bps,
        },
        "trades_count": len(trades),
        "rejected_signals_count": len(simulator.rejected_signals),
        "performance": performance.to_dict() if performance is not None else None,
        "performance_note": (
            None
            if performance is not None
            else "A estratégia não gerou nenhum trade válido no período -- sem base para métricas de performance."
        ),
        "trades": [t.to_dict() for t in trades],
    }


# ----------------------------------------------------------------------
# Backtest DSL genérico (Documento 1 -- Fase 1 do Plano de Evolução)
# ----------------------------------------------------------------------
# Aditivo: não altera o comportamento de /backtest acima. Aceita
# qualquer estratégia descrita por regras determinísticas (ver
# GET /schema_capabilities para o que é suportado hoje), em vez de
# depender de uma estratégia pré-registrada em backtest/registry.py.


class GenericBacktestRequest(BaseModel):
    strategy: dict[str, Any] = Field(description="Schema completo da estratégia genérica -- ver GET /schema_capabilities.")
    start: datetime = Field(description="Início do range histórico (ISO 8601).")
    end: datetime | None = Field(default=None, description="Fim do range histórico (padrão: agora).")
    min_candles: int = Field(default=50, description="Mínimo de candles exigido no range.")

    @field_validator("start", "end")
    @classmethod
    def _assume_utc_when_naive(cls, value: datetime | None) -> datetime | None:
        """Mesma regra do /backtest -- ver docstring de BacktestRequest."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


@app.get("/schema_capabilities", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_schema_capabilities_endpoint() -> dict:
    """Lista indicadores, funções, tipos de stop/TP/sizing suportados pelo backtest genérico -- e o que NÃO é suportado ainda (Documento 1, seção 20). Consultar antes de montar um schema de estratégia."""
    return schema_capabilities()


@app.post("/backtest/generic", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_backtest_generic(request: GenericBacktestRequest) -> dict:
    """Backtest sem lookahead para estratégia por regras, sem pré-registro. Valida schema e indicadores; nunca retorna execução parcial. Retorna performance, trade log com position sizing, equity curve e sample_quality. Erros são HTTP 422; regras/indicadores sem suporte não são aproximados."""
    fetcher = HistoryFetcher(router=build_default_router())
    try:
        return run_generic_backtest(
            raw_schema=request.strategy,
            history_fetcher=fetcher,
            start=request.start,
            end=request.end,
            min_candles=request.min_candles,
        )
    except StrategyDslError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    except (HistoryFetchError, DataUnavailableError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Falha ao buscar histórico: {exc}") from exc


# ----------------------------------------------------------------------
# Setup Lifecycle + Setup Memory (Fase 2 do Plano de Evolução)
# ----------------------------------------------------------------------
# Persistência real (Postgres em produção via DATABASE_URL, SQLite
# local -- ver persistence/db.py). Aditivo: nenhum endpoint anterior
# foi alterado. O Discovery/Ranking Engine (Fase 3) ainda não existe --
# por enquanto quem registra um setup aqui é o GPT (ou qualquer outro
# chamador) identificando um setup numa análise; a infraestrutura de
# lifecycle/memory/expiração já fica pronta para a Fase 3 plugar nela.


@app.post("/setups", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_setup(candidate: SetupCandidate) -> dict:
    """Registra candidato no Setup Lifecycle/Memory. Havendo setup aberto para asset+direction+strategy, atualiza-o sem duplicar; caso contrário cria outro. Retorna o persistido e change_type. Partindo de COMPLETED, INVALIDATED, EXPIRED ou CANCELLED, cria sempre novo setup, sem reabrir o anterior."""
    with session_scope() as session:
        try:
            result = upsert_setup(session, candidate)
        except (InvalidTransitionError, UnknownStatusError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"created": result.created, "change_type": result.change_type, "setup": result.record.to_dict()}


@app.get("/setups/{symbol}", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_setups_for_symbol(symbol: str, include_terminal: bool = False) -> dict:
    """Setups conhecidos para um símbolo (status atual, entrada, trigger, invalidação, última atualização). Por padrão só os não-terminais (em aberto); include_terminal=true também traz COMPLETED/INVALIDATED/EXPIRED/CANCELLED."""
    with session_scope() as session:
        records = list_setups(session, asset=symbol, exclude_terminal=not include_terminal)
        return {"symbol": symbol, "count": len(records), "setups": [r.to_dict() for r in records]}


@app.get("/opportunities", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_opportunities(status: str | None = None, since: datetime | None = None) -> dict:
    """Lista todos os setups abertos (não terminais), base dos futuros TOP TRADES do Discovery/Ranking Engine. `status` filtra um estado; `since` (ISO 8601) retorna apenas alterações desde o momento informado, evitando reprocessamento integral."""
    with session_scope() as session:
        if since is not None:
            since_utc = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
            records = [r for r in get_changed_since(session, since_utc) if status is None or r.status == status]
        else:
            records = list_setups(session, status_in=[status] if status else None, exclude_terminal=status is None)
        return {"count": len(records), "opportunities": [r.to_dict() for r in records]}


@app.post("/setups/sweep-expired", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_sweep_expired() -> dict:
    """Marca como EXPIRED todo setup em aberto cujo `expiration` já passou. Pensado para ser chamado periodicamente por um scheduler (Render Cron -- infraestrutura de agendamento automático é Fase 7; este endpoint já funciona sob demanda hoje)."""
    with session_scope() as session:
        changed_ids = sweep_expired(session)
        return {"expired_count": len(changed_ids), "expired_ids": changed_ids}


# ----------------------------------------------------------------------
# Discovery / Ranking Engine (Fase 3 do Plano de Evolução)
# ----------------------------------------------------------------------
# Aditivo: reaproveita app.run_analysis (mesmo pipeline de /snapshot e
# /scan) -- não substitui /scan, que continua com seu próprio
# comportamento (zona de entrada/observar/fora de zona). Este endpoint
# responde "quais são as MELHORES oportunidades", não "onde está cada
# símbolo" -- ver discovery/engine.py para as limitações declaradas
# (estimativa de entrada/stop/TP de primeiro corte, 1 timeframe por
# chamada, Playbook ainda não validado por backtest).


@app.get("/discovery/top-trades", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_top_trades(
    symbols: str | None = Query(
        default=None,
        description=f"Símbolos separados por vírgula (padrão: watchlist de {len(DEFAULT_SCAN_SYMBOLS)} ativos em config.DEFAULT_SCAN_SYMBOLS).",
    ),
    btc_symbol: str = Query(default="BTCUSDT", description="Símbolo usado como contexto BTC (regime + força relativa)."),
    direction: str | None = Query(default=None, description="'long' | 'short' -- None considera as duas direções."),
    style: str | None = Query(default=None, description="Filtra o Playbook por estilo: 'day_trade' | 'intraday' | 'swing'."),
    timeframe: str = Query(default="1H", description="Timeframe usado para regime, estrutura e ranking."),
    top_n: int = Query(default=5, description="Máximo de oportunidades retornadas (Documento Master seção 21: seleção, não lista longa)."),
) -> dict:
    """Varre símbolos, detecta regime do BTC e ativo, aplica regime-first, calcula Multi-Score (9 scores + overall) e Correlated Exposure Engine. Retorna as top_n oportunidades e ativos sem edge, com motivo. Scores não são probabilidade; entry/stop/target são estimativas iniciais, não plano completo."""
    symbol_list = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if symbols
        else DEFAULT_SCAN_SYMBOLS
    )
    if len(symbol_list) > SCAN_MAX_SYMBOLS:
        raise HTTPException(
            status_code=422,
            detail=f"Máximo de {SCAN_MAX_SYMBOLS} símbolos por chamada, {len(symbol_list)} recebidos.",
        )
    if direction is not None and direction not in ("long", "short"):
        raise HTTPException(status_code=422, detail="direction deve ser 'long', 'short' ou omitido.")

    try:
        return scan_opportunities(
            symbols=symbol_list,
            btc_symbol=btc_symbol,
            direction=direction,
            style=style,
            timeframe=timeframe,
            top_n=top_n,
        )
    except InsufficientDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataUnavailableError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao buscar dados de mercado: {exc}") from exc


# ----------------------------------------------------------------------
# Risk Engine (Fase 4 do Plano de Evolução)
# ----------------------------------------------------------------------
# Persistência real (mesma AccountState/OpenPositionRecord/RiskEvent --
# ver persistence/models.py). Documento Master, seção 73: a autonomia
# do sistema é sobre DECISÃO, o risco continua subordinado a este
# motor -- nenhum outro endpoint contorna estes limites.


class AccountInitRequest(BaseModel):
    account_id: str = "default"
    starting_capital: float = Field(gt=0)
    max_risk_per_trade_pct: float | None = None
    daily_loss_limit_pct: float | None = None
    weekly_loss_limit_pct: float | None = None
    monthly_drawdown_limit_pct: float | None = None
    max_open_risk_pct: float | None = None


class RiskEvaluateRequest(BaseModel):
    account_id: str = "default"
    asset: str
    direction: str
    requested_risk_pct: float = Field(gt=0)
    correlation_group: str | None = None


class OpenPositionRequest(RiskEvaluateRequest):
    setup_id: int | None = None


class ClosePositionRequest(BaseModel):
    account_id: str = "default"
    pnl_pct: float


class RiskOfRuinRequest(BaseModel):
    win_rate_pct: float = Field(ge=0, le=100)
    payoff_ratio: float = Field(gt=0)
    risk_per_trade_pct: float = Field(gt=0)


@app.post("/risk/account", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_risk_account(request: AccountInitRequest) -> dict:
    """Cria a conta de risco (se ainda não existir) ou atualiza os limites de uma existente. O Risk Engine nunca assume capital inicial -- precisa ser informado explicitamente na primeira chamada."""
    with session_scope() as session:
        account = get_or_create_account(session, request.account_id, starting_capital=request.starting_capital)
        for field_name in (
            "max_risk_per_trade_pct", "daily_loss_limit_pct", "weekly_loss_limit_pct",
            "monthly_drawdown_limit_pct", "max_open_risk_pct",
        ):
            value = getattr(request, field_name)
            if value is not None:
                setattr(account, field_name, value)
        return account.to_dict()


@app.get("/risk/state", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_risk_state(account_id: str = "default") -> dict:
    """Capital atual, PnL realizado (dia/semana/mês), open risk agregado e limites configurados."""
    with session_scope() as session:
        try:
            account = get_or_create_account(session, account_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        state = build_risk_state(session, account, correlation_group=None)
        return {
            "account": account.to_dict(),
            "state": {
                "realized_pnl_today_pct": round(state.realized_pnl_today_pct, 3),
                "realized_pnl_week_pct": round(state.realized_pnl_week_pct, 3),
                "realized_pnl_month_pct": round(state.realized_pnl_month_pct, 3),
                "open_risk_pct": round(state.open_risk_pct, 3),
            },
            "open_positions": [p.to_dict() for p in list_open_positions(session, account_id)],
        }


@app.post("/risk/evaluate", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_risk_evaluate(request: RiskEvaluateRequest) -> dict:
    """Avalia um trade proposto contra os limites da conta (por trade, diário, semanal, mensal, open risk, correlação) SEM abrir a posição. Use POST /risk/positions para abrir de fato."""
    with session_scope() as session:
        try:
            account = get_or_create_account(session, request.account_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        state = build_risk_state(session, account, correlation_group=request.correlation_group)
        limits = build_risk_limits(account)
        trade = ProposedTrade(
            asset=request.asset, direction=request.direction,
            requested_risk_pct=request.requested_risk_pct, correlation_group=request.correlation_group,
        )
        decision = evaluate_trade_risk(trade, state, limits)
        return decision.to_dict()


@app.post("/risk/positions", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_risk_open_position(request: OpenPositionRequest) -> dict:
    """Avalia o trade E, se aprovado ou reduzido, abre a posição com o risco efetivamente aprovado (nunca o solicitado, se for maior). Se REJECTED, não abre nada e retorna a decisão com o motivo (HTTP 422)."""
    with session_scope() as session:
        try:
            account = get_or_create_account(session, request.account_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        state = build_risk_state(session, account, correlation_group=request.correlation_group)
        limits = build_risk_limits(account)
        trade = ProposedTrade(
            asset=request.asset, direction=request.direction,
            requested_risk_pct=request.requested_risk_pct, correlation_group=request.correlation_group,
        )
        decision = evaluate_trade_risk(trade, state, limits)
        if decision.decision == "REJECTED":
            raise HTTPException(status_code=422, detail=decision.to_dict())

        position = open_position(
            session, request.account_id, asset=request.asset, direction=request.direction,
            risk_pct=decision.approved_risk_pct, correlation_group=request.correlation_group, setup_id=request.setup_id,
        )
        return {"decision": decision.to_dict(), "position": position.to_dict()}


@app.post("/risk/positions/{position_id}/close", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_risk_close_position(position_id: int, request: ClosePositionRequest) -> dict:
    """Encerra uma posição aberta, registra o resultado (alimenta os limites diário/semanal/mensal) e atualiza o capital da conta."""
    with session_scope() as session:
        try:
            event = close_position(session, request.account_id, position_id, request.pnl_pct)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        account = get_or_create_account(session, request.account_id)
        return {"event": event.to_dict(), "account": account.to_dict()}


@app.post("/risk/ruin", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_risk_of_ruin(request: RiskOfRuinRequest) -> dict:
    """Estimativa analítica de Risk of Ruin dado win rate, payoff ratio e risco por trade -- aproximação, não simulação Monte Carlo (ver risk/ruin.py para as premissas)."""
    result = estimate_risk_of_ruin(request.win_rate_pct, request.payoff_ratio, request.risk_per_trade_pct)
    return result.to_dict()


# ----------------------------------------------------------------------
# Learning Engine (Fase 5 do Plano de Evolução)
# ----------------------------------------------------------------------
# Signal Feature Database + Call Reverse Engineering + hipóteses
# agregadas. `POST /learning/signals` faz a reconstrução histórica de
# contexto (rede real, via HistoryFetcher -- mesma infra da Fase 1);
# se ainda não houver `result` no momento do registro, o sinal fica
# com signal_quality_label=null (PENDING_RESULT) até
# PATCH /learning/signals/{id}/result ser chamado.


@app.post("/learning/signals", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_learning_signal(candidate: ExternalSignalInput) -> dict:
    """Registra sinal externo e reconstrói o contexto objetivo de mercado no instante da emissão (Call Reverse Engineering). Com `result`, classifica VALID_SIGNAL, WEAK_SIGNAL, LUCKY_WIN, GOOD_TRADE_BAD_RESULT ou BAD_TRADE_GOOD_RESULT; sem ele, fica PENDING_RESULT até atualização."""
    fetcher = HistoryFetcher(router=build_default_router())
    try:
        context = reconstruct_context(candidate.asset, candidate.direction, candidate.timeframe, candidate.signal_time, fetcher)
    except (HistoryFetchError, DataUnavailableError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Falha ao reconstruir contexto histórico: {exc}") from exc

    quality_score = context.inferences["quality_score"]
    label = classify_signal(quality_score, candidate.result)

    with session_scope() as session:
        record = create_signal(session, candidate, context.to_dict(), label if label != "PENDING_RESULT" else None)
        return {"signal": record.to_dict(), "reconstructed_context": context.to_dict()}


@app.get("/learning/signals", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_learning_signals(asset: str | None = None, strategy_guess: str | None = None, signal_quality_label: str | None = None) -> dict:
    """Lista sinais registrados, com filtros opcionais por ativo, estratégia inferida e classificação."""
    with session_scope() as session:
        records = list_signals(session, asset=asset, strategy_guess=strategy_guess, signal_quality_label=signal_quality_label)
        return {"count": len(records), "signals": [r.to_dict() for r in records]}


@app.patch("/learning/signals/{signal_id}/result", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def patch_learning_signal_result(signal_id: int, update: SignalResultUpdate) -> dict:
    """Atualiza o resultado de um sinal já registrado (quando o resultado passa a ser conhecido) e recalcula a classificação."""
    with session_scope() as session:
        record = get_signal(session, signal_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Sinal {signal_id} não encontrado.")
        quality_score = (record.reconstructed_context or {}).get("inferences", {}).get("quality_score", 50.0)
        label = classify_signal(quality_score, update.result)
        try:
            updated = update_signal_result(session, signal_id, update, label)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return updated.to_dict()


@app.get("/learning/hypotheses", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def get_learning_hypotheses(group_by: str = "strategy_guess") -> dict:
    """Agrega os sinais com resultado conhecido por `group_by` ('strategy_guess' ou 'asset') e classifica cada grupo (OBSERVATION/IN_TEST/VALIDATED/REJECTED). Nunca declara VALIDATED com amostra abaixo de 30."""
    if group_by not in ("strategy_guess", "asset"):
        raise HTTPException(status_code=422, detail="group_by deve ser 'strategy_guess' ou 'asset'.")
    with session_scope() as session:
        records = list_signals(session)
        signals_as_dicts = [
            {"strategy_guess": r.strategy_guess, "asset": r.asset, "result": r.result, "r_multiple": r.r_multiple}
            for r in records
        ]
        hypotheses = build_hypotheses(signals_as_dicts, group_by=group_by)
        return {"group_by": group_by, "hypotheses": [h.to_dict() for h in hypotheses]}


# ----------------------------------------------------------------------
# Decision Eligibility Engine (Fase 6 do Plano de Evolução)
# ----------------------------------------------------------------------
# Orquestra scoring (Fase 3) + Risk Engine (Fase 4) + Decision
# Eligibility (decision/engine.py) num único veredito determinístico.
# O GPT consome o `mentor_block` pronto -- não deve recalcular ou
# inventar nenhum dos números ali (Documento Master, seção 17/26).


class DecisionEvaluateRequest(BaseModel):
    account_id: str = "default"
    asset: str
    direction: str
    requested_risk_pct: float = Field(gt=0)
    correlation_group: str | None = None

    # Inputs de score (mesmos de scoring.engine.compute_opportunity_score) --
    # o chamador já tem isso de uma chamada anterior a /snapshot, /scan ou /discovery/top-trades.
    trend: str
    bos: bool
    choch: bool
    regime_compatible: bool
    rr: float | None = None
    distance_to_zone_pct: float | None = None
    volatility_bucket: str = "NORMAL"
    btc_context: str | None = None
    playbook_stats: dict | None = None

    # Setup / entrada
    setup_status: str = "UNKNOWN"
    entry_quality: str = "ENTRY_NOW"
    style: str | None = None
    entry_zone: list[float] | None = None  # [low, high]
    stop: float | None = None
    target: float | None = None
    invalidation: str | None = None
    main_risk: str | None = None


@app.post("/decision/evaluate", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_decision_evaluate(request: DecisionEvaluateRequest) -> dict:
    """Veredito determinístico: calcula Multi-Score, avalia o Risk Engine — soberano, pois REJECTED não é contornado por score alto — e decide LONG_NOW, SHORT_NOW, WAIT_TRIGGER, WAIT_PULLBACK, WATCH ou REJECT. Também retorna `mentor_block`, pronto para o GPT comunicar sem recalcular ou inventar números."""
    with session_scope() as session:
        try:
            account = get_or_create_account(session, request.account_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        risk_state = build_risk_state(session, account, correlation_group=request.correlation_group)
        risk_limits = build_risk_limits(account)
        proposed_trade = ProposedTrade(
            asset=request.asset, direction=request.direction,
            requested_risk_pct=request.requested_risk_pct, correlation_group=request.correlation_group,
        )
        risk_decision = evaluate_trade_risk(proposed_trade, risk_state, risk_limits)

        score = compute_opportunity_score(
            trend=request.trend, bos=request.bos, choch=request.choch,
            regime_compatible=request.regime_compatible, rr=request.rr,
            distance_to_zone_pct=request.distance_to_zone_pct, volatility_bucket=request.volatility_bucket,
            btc_context=request.btc_context, correlation_penalty=False, playbook_stats=request.playbook_stats,
        )

        eligibility = evaluate_decision(
            direction=request.direction, overall_score=score.overall, risk_decision=risk_decision.decision,
            setup_status=request.setup_status, entry_quality=request.entry_quality,
        )

        entry_zone_tuple = (request.entry_zone[0], request.entry_zone[1]) if request.entry_zone else None
        mentor_block = build_mentor_block(
            decision=eligibility.decision, conviction=eligibility.conviction,
            reasons=[*eligibility.reasons, *score.factors], asset=request.asset,
            entry_zone=entry_zone_tuple, stop=request.stop, target=request.target, rr=request.rr,
            approved_risk_pct=risk_decision.approved_risk_pct, volatility_bucket=request.volatility_bucket,
            style=request.style, invalidation=request.invalidation, main_risk=request.main_risk,
        )

        return {
            "score": score.to_dict(),
            "risk_decision": risk_decision.to_dict(),
            "eligibility": eligibility.to_dict(),
            "mentor_block": mentor_block,
        }


# ----------------------------------------------------------------------
# Monitoring / Scheduler (Fase 7 do Plano de Evolução)
# ----------------------------------------------------------------------
# O agendamento automático de verdade é o Render Cron Job em
# render.yaml (scripts/run_monitoring_cycle.py, chamado direto contra
# o banco). Este endpoint é o mesmo ciclo, sob demanda via HTTP -- útil
# para o GPT rodar uma checagem manual ("atualiza meus setups agora")
# sem esperar o próximo tick do cron.


@app.post("/monitoring/run-cycle", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_monitoring_run_cycle() -> dict:
    """Expira setups vencidos e atualiza o status dos setups em aberto (NEAR_ENTRY/INVALIDATED/TP1-3/COMPLETED) com base no preço atual de cada ativo. Mesmo ciclo que o Render Cron roda periodicamente -- este endpoint permite disparar sob demanda."""
    with session_scope() as session:
        result = run_monitoring_cycle(session)
        return result.to_dict()


# ----------------------------------------------------------------------
# Optimization / Robustness / Portfolio Intelligence (Fase 8 -- última fase do Plano de Evolução)
# ----------------------------------------------------------------------
# Walk-forward e parameter sweep reaproveitam strategy_dsl (Fase 1) --
# não recalculam simulação. Monte Carlo e Portfolio Selection são
# funções puras. Nenhum destes endpoints declara uma "melhor
# estratégia" -- sempre "melhor resultado no espaço pesquisado"
# (Documento 1, seção 17).


class WalkForwardRequest(BaseModel):
    strategy: dict[str, Any] = Field(description="Schema da estratégia genérica -- ver GET /schema_capabilities.")
    windows: list[list[datetime]] = Field(description="Lista de [start, end] (ISO 8601) -- cada par é uma janela de teste independente.")
    min_candles: int = 30


class ParameterSweepRequest(BaseModel):
    strategy: dict[str, Any] = Field(description="Schema base -- cada combinação do grid parte de uma cópia dele.")
    param_grid: dict[str, list[Any]] = Field(description="Ex.: {'indicators.0.period': [10,20,30], 'exit.take_profit.value': [2,3,4]}.")
    start: datetime
    end: datetime | None = None
    rank_by: str = "expectancy_r"
    min_candles: int = 30
    max_combinations: int = 60


class MonteCarloRequest(BaseModel):
    trade_pnl_pct: list[float] = Field(description="PnL % por trade (ex.: da lista trade_log de um backtest genérico já rodado).")
    starting_capital: float = Field(gt=0)
    num_simulations: int = Field(default=1000, gt=0, le=20_000)
    seed: int | None = None


class PortfolioSelectionRequest(BaseModel):
    opportunities: list[dict[str, Any]] = Field(description="Cada item precisa ter 'symbol' e 'overall_opportunity_score'.")
    max_open_risk_pct: float = Field(gt=0)
    risk_pct_per_trade: float = Field(gt=0)
    max_positions: int | None = None
    correlation_flags: dict[str, str | None] | None = None


@app.post("/optimization/walk-forward", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_walk_forward(request: WalkForwardRequest) -> dict:
    """Roda a MESMA estratégia (mesmo schema) em várias janelas de tempo independentes e agrega estabilidade (média/mediana/desvio padrão de expectancy_r, profit_factor, win_rate entre janelas). Desvio alto relativo à média indica dependência forte do período escolhido."""
    fetcher = HistoryFetcher(router=build_default_router())
    windows = [(w[0], w[1]) for w in request.windows]
    try:
        result = run_walk_forward(request.strategy, windows, fetcher, min_candles=request.min_candles)
    except StrategyDslError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    except (HistoryFetchError, DataUnavailableError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.to_dict()


@app.post("/optimization/parameter-sweep", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_parameter_sweep(request: ParameterSweepRequest) -> dict:
    """Testa uma grade de combinações de parâmetros sobre o MESMO período (nunca otimiza contra out-of-sample). Retorna cada resultado + o 'melhor resultado no espaço pesquisado' (nunca chamado de 'melhor estratégia') + aviso de overfitting sempre presente."""
    fetcher = HistoryFetcher(router=build_default_router())
    try:
        report = run_parameter_sweep(
            request.strategy, request.param_grid, fetcher, request.start, request.end,
            rank_by=request.rank_by, min_candles=request.min_candles, max_combinations=request.max_combinations,
        )
    except StrategyDslError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    except (HistoryFetchError, DataUnavailableError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return report.to_dict()


@app.post("/optimization/monte-carlo", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_monte_carlo(request: MonteCarloRequest) -> dict:
    """Bootstrap por reamostragem sobre trades já simulados -- distribuição (percentis 5/25/50/75/95) de capital final e drawdown máximo, e probabilidade de terminar no prejuízo. Não é uma previsão do futuro -- assume trades intercambiáveis (i.i.d.)."""
    try:
        result = run_monte_carlo(request.trade_pnl_pct, request.starting_capital, request.num_simulations, request.seed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.to_dict()


@app.post("/optimization/portfolio-selection", response_class=FlexibleJSONResponse, responses=_FREEFORM_JSON_OBJECT_RESPONSES)
def post_portfolio_selection(request: PortfolioSelectionRequest) -> dict:
    """Seleção gulosa da melhor combinação de oportunidades (ranqueadas por overall_opportunity_score) respeitando o teto de open risk, número máximo de posições e evitando duplicar exposição correlacionada (Documento Master, seção 38)."""
    result = select_best_combination(
        request.opportunities, request.max_open_risk_pct, request.risk_pct_per_trade,
        max_positions=request.max_positions, correlation_flags=request.correlation_flags,
    )
    return result.to_dict()
