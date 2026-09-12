"""
strategy_dsl/schema.py
=========================

Modelo Pydantic da estratégia genérica (Documento 1, seção 2).

A estrutura do JSON de exemplo do documento não tem um "id" explícito
por indicador (usa "SMA20" como se fosse implícito a partir do tipo +
período). Na prática isso é ambíguo quando há dois indicadores do
mesmo tipo/período em contextos diferentes (ex.: RSI do 1H e RSI do
4H numa estratégia multi-timeframe futura) -- por isso cada indicador
aqui tem um `id` (opcional na entrada; se omitido, é derivado
deterministicamente de `type` + `period`, preservando compatibilidade
com o formato do documento pros casos simples).

Todos os modelos são `pydantic.BaseModel` com `extra="forbid"`: um
campo desconhecido no JSON é rejeitado na validação de schema (nunca
ignorado silenciosamente) -- ver Documento 1, seção 22 (validação
antes de executar).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Direction = Literal["long", "short", "long_short"]
IntrabarPriority = Literal["stop_first", "take_first"]
EntryTiming = Literal["next_bar_open"]  # única opção suportada hoje -- ver capabilities.py
OrderType = Literal["market"]  # única opção suportada hoje -- ver capabilities.py
SizingType = Literal["fixed_quantity", "fixed_notional", "risk_percent", "risk_amount"]
StopType = Literal["percent", "atr", "price"]
TakeProfitType = Literal["percent", "atr", "rr", "price"]
TrailingType = Literal["percent", "atr"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndicatorSpec(_Strict):
    id: str | None = None
    type: str
    period: int | None = None
    source: str = "close"
    # parâmetros extra específicos de um indicador (ex.: std_dev do Bollinger,
    # fast/slow/signal do MACD) -- validados pelo indicators_registry, não aqui.
    params: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _default_id(self) -> "IndicatorSpec":
        if self.id is None:
            suffix = str(self.period) if self.period is not None else ""
            object.__setattr__(self, "id", f"{self.type.upper()}{suffix}")
        return self


class EntryRules(_Strict):
    long: list[str] = Field(default_factory=list)
    short: list[str] = Field(default_factory=list)


class StopLossSpec(_Strict):
    type: StopType
    value: float


class TakeProfitSpec(_Strict):
    type: TakeProfitType
    value: float


class TrailingStopSpec(_Strict):
    type: TrailingType
    value: float
    activation_r: float = 0.0  # em qual R o trailing começa a valer (0 = desde a entrada)


class BreakEvenSpec(_Strict):
    trigger_r: float
    offset: float = 0.0  # deslocamento do stop além do preço de entrada (em unidades de preço)


class ExitRules(_Strict):
    stop_loss: StopLossSpec
    take_profit: TakeProfitSpec
    trailing_stop: TrailingStopSpec | None = None
    break_even: BreakEvenSpec | None = None


class ExecutionRules(_Strict):
    signal_at: Literal["bar_close"] = "bar_close"
    entry_at: EntryTiming = "next_bar_open"
    order_type: OrderType = "market"
    intrabar_priority: IntrabarPriority = "stop_first"
    allow_multiple_positions: bool = False
    pyramiding: int = 0

    @field_validator("allow_multiple_positions")
    @classmethod
    def _no_multiple_positions_yet(cls, v: bool) -> bool:
        if v:
            raise ValueError(
                "allow_multiple_positions=true não é suportado nesta versão do motor "
                "(uma posição por vez -- ver schema_capabilities)."
            )
        return v

    @field_validator("pyramiding")
    @classmethod
    def _no_pyramiding_yet(cls, v: int) -> int:
        if v != 0:
            raise ValueError("pyramiding != 0 não é suportado nesta versão do motor.")
        return v


class PositionSizingSpec(_Strict):
    type: SizingType
    value: float


class CostsSpec(_Strict):
    commission_bps: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    funding_bps_per_day: float = 0.0  # aceito no schema, mas ver capabilities.py (ainda não aplicado na simulação)


class MarketSpec(_Strict):
    symbols: list[str]
    timeframe: str
    exchange: str = "BINANCE"

    @field_validator("symbols")
    @classmethod
    def _single_symbol_for_now(cls, v: list[str]) -> list[str]:
        if len(v) != 1:
            raise ValueError(
                "Esta versão do motor só executa backtest de 1 símbolo por vez "
                "(multi-asset ainda não suportado -- ver schema_capabilities)."
            )
        return v


class GenericStrategySchema(_Strict):
    name: str
    description: str = ""
    market: MarketSpec
    direction: Direction
    indicators: list[IndicatorSpec] = Field(default_factory=list)
    entry: EntryRules
    filters: list[str] = Field(default_factory=list)
    exit: ExitRules
    execution: ExecutionRules = Field(default_factory=ExecutionRules)
    position_sizing: PositionSizingSpec
    costs: CostsSpec = Field(default_factory=CostsSpec)
    starting_capital: float | None = None

    @model_validator(mode="after")
    def _entry_rules_required(self) -> "GenericStrategySchema":
        if self.direction in ("long", "long_short") and not self.entry.long:
            raise ValueError("direction inclui 'long' mas entry.long está vazio.")
        if self.direction in ("short", "long_short") and not self.entry.short:
            raise ValueError("direction inclui 'short' mas entry.short está vazio.")
        return self

    @model_validator(mode="after")
    def _starting_capital_required_for_risk_sizing(self) -> "GenericStrategySchema":
        needs_capital = self.position_sizing.type in ("risk_percent", "risk_amount", "fixed_notional")
        if needs_capital and self.starting_capital is None:
            raise ValueError(
                f"position_sizing.type='{self.position_sizing.type}' exige 'starting_capital' "
                "explícito -- o motor nunca assume capital inicial (Documento 1, seção 8)."
            )
        return self
