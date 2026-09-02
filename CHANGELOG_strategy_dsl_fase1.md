# CHANGELOG — Fase 1: Backtest DSL Genérico

Implementa o Documento 1 (Backtest DSL) do Plano de Evolução do AlphaQuant X.
100% aditivo: nenhum endpoint/comportamento existente (`/snapshot`, `/analyze`,
`/scan`, `/backtest`, `/backtest/strategies`) foi alterado.

## Novo módulo `strategy_dsl/`

- `schema.py` — modelo Pydantic (v2, `extra="forbid"`) da estratégia genérica
  (Documento 1, seção 2): market, direction, indicators, entry/filters, exit
  (stop/take-profit/trailing/break-even), execution, position_sizing, costs,
  starting_capital. Validações: `starting_capital` obrigatório para sizing
  baseado em risco (nunca assumido), 1 símbolo por backtest (multi-asset ainda
  não suportado), regras de entrada obrigatórias para a direção declarada.
- `indicators_registry.py` — tabela de indicadores suportados (Documento 1,
  seção 4): SMA, EMA, WMA, RSI, MACD, ROC, Stochastic, ATR, Bollinger,
  Donchian, Volume SMA, OBV, VWAP, Highest, Lowest. Reaproveita 100% de
  `indicators/` já existente (SMA/WMA são os únicos calculados aqui, por não
  existirem lá). Indicador não suportado nunca é aproximado — levanta
  `UnsupportedIndicatorError` com o nome exato.
- `expression_engine.py` — avaliador de regras determinísticas
  ("SMA20 crosses above SMA50", "RSI14 < 30" etc.) via AST Python restrita
  (whitelist de nós — nunca `eval()` de código arbitrário). Funções
  suportadas: `cross_above`/`crossover`, `cross_below`/`crossunder`,
  `highest`, `lowest`, `sma`, `ema`, `abs`, `min`, `max`, operadores lógicos
  e de comparação. Regra subjetiva ou função não suportada é rejeitada com
  erro estruturado (Documento 1, seção 3).
- `generic_strategy.py` — `GenericStrategy`, implementação de
  `backtest.strategy.Strategy` que interpreta o schema. Pré-computa
  indicadores e regras vetorizados sobre o histórico completo (nunca
  recalcula candle a candle); indexação por posição garante alinhamento
  com o `BacktestSimulator` sem lookahead. Regras de `entry.long` /
  `entry.short` / `filters` são combinadas com AND (decisão de design
  documentada, já que o Documento 1 não especifica).
- `portfolio.py` — position sizing real (`fixed_quantity`, `fixed_notional`,
  `risk_percent`, `risk_amount`), trade log enriquecido (quantity, notional,
  gross/net PnL) e equity curve com drawdown (Documento 1, seções 8, 9, 11, 12).
- `capabilities.py` + `executor.py` — orquestração ponta a ponta (schema →
  histórico → simulação → performance → equity curve → relatório final) e
  fonte única da verdade para `GET /schema_capabilities` (Documento 1,
  seção 20 — o que é suportado e o que não é, nunca implícito).
- `errors.py` — erros estruturados (`unsupported_indicator`,
  `unsupported_function`, `invalid_rule`, `invalid_schema`,
  `unsupported_strategy`) — nunca falha parcial/silenciosa (Documento 1,
  seção 22).

## Extensões em código existente (retrocompatíveis)

- `backtest/strategy.py` — `Signal` ganha dois campos opcionais
  (`trailing_stop`, `break_even`), default `None` — comportamento anterior
  100% preservado para quem não usa esses campos.
- `backtest/simulator.py`:
  - `BacktestSimulator` ganha parâmetro `intrabar_priority`
    (`"stop_first"` default = comportamento anterior, ou `"take_first"`) —
    Documento 1, seção 6, nunca mais implícito.
  - Suporte a **trailing stop** (`percent` ou `atr`, com `activation_r`) e
    **break-even** (`trigger_r` + `offset`) — nunca afrouxam o stop, só
    apertam a favor do trade.

## Endpoints novos (aditivos)

- `GET /schema_capabilities` — indicadores/funções/tipos suportados e não
  suportados hoje.
- `POST /backtest/generic` — roda backtest de uma estratégia descrita por
  schema (não precisa estar pré-registrada em `backtest/registry.py`).
  Retorna `meta`, `execution` (com `intrabar_priority` explícito),
  `result_type` (`gross`/`net`), `performance`, `sample_quality`
  (insufficient/in_validation/moderate_confidence/high_confidence — limiares
  de 30/100/300 trades, Documento 1 seção 14), `trade_log` (com position
  sizing), `equity_curve` e `risks`. Erro de schema/indicador/regra volta
  como HTTP 422 com corpo estruturado.

## Nota sobre limite de operações do GPT Actions

Confirmado: a spec OpenAPI de uma Action do ChatGPT tem limite de
**30 operações** e ~1MB de tamanho total. Schema atual do AlphaQuant Engine:
8 operações, ~11KB — folga confortável hoje. Vale monitorar a partir da
Fase 2 em diante (endpoints de `/opportunities`, `/setups`, `/top-trades`
etc. vão empurrar essa contagem) — se necessário, dividir em mais de uma
Action/serviço (conforme já autorizado no Plano de Evolução).

## Limitações conhecidas desta fase (ver `GET /schema_capabilities`)

- 1 símbolo e 1 timeframe por backtest (multi-asset/multi-timeframe ficam
  para fases posteriores).
- 1 take-profit por trade (sem TP1/TP2/TP3 com saída parcial).
- Sem pyramiding / múltiplas posições simultâneas.
- `funding_bps_per_day` é aceito no schema mas ainda não aplicado na
  simulação.
- Custo total por trade é reportado, mas ainda não decomposto em
  commission/spread/slippage separados (a fonte, `CostModel`, já combina
  os três num bps só por perna).
- Walk-forward, parameter sweep, Monte Carlo e split in-sample/out-of-sample
  não implementados nesta fase — ver Plano de Evolução, Fase 8.

## Testes

```
pytest tests/ -q
# 213 passed (195 já existentes + 18 novos em tests/test_strategy_dsl.py)
```

Cobertura dos testes novos: rejeição de schema inválido/campo desconhecido,
capital inicial obrigatório para sizing por risco, indicador não suportado,
cálculo de SMA batendo com `rolling().mean()`, regra subjetiva rejeitada,
função não suportada rejeitada, `cross_above` no candle exato, geração de
trade real via `GenericStrategy` + `BacktestSimulator`, `intrabar_priority`
configurável, position sizing `risk_percent` batendo com o valor esperado,
equity curve partindo do capital inicial e rastreando drawdown, break-even
movendo o stop após atingir `trigger_r`, trailing stop percentual apertando
o stop a favor do trade.
