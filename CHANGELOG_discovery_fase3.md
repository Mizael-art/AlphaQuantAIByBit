# CHANGELOG — Fase 3: Multi-Score + Discovery/Ranking + Regime-First

Implementa o Documento 2 (seções 4-12, 20) e o Documento Master (seções
4-14, 25) do Plano de Evolução. 100% aditivo: nenhum endpoint/módulo
anterior foi alterado (`/scan` continua com seu próprio comportamento
de zona de entrada/observar/fora de zona; `/discovery/top-trades` é um
produto diferente -- "quais são as melhores oportunidades", não "onde
está cada símbolo").

## Regime-First Engine (`regime/`)

- `detector.py` — `detect_regime`: os 10 regimes do Documento 2 (seção
  7): TRENDING_UP/DOWN, RANGE, COMPRESSION, EXPANSION, ACCUMULATION,
  DISTRIBUTION, TRANSITION, HIGH/LOW_VOLATILITY. Prioridade explícita
  e documentada (volatilidade extrema > compressão/expansão >
  transição > tendência > ranging/acumulação/distribuição). Reaproveita
  100% de `analysis.trend`, `statistics_.volatility` e Bollinger Bands
  já existentes -- não recalcula nada do zero.
- `relative_strength.py` — força relativa vs. BTC (retorno % do ativo
  menos retorno % do BTC no mesmo lookback), classificada em
  STRONG/WEAK/NEUTRAL.
- `btc_filter.py` — `classify_btc_context`: BTC_SUPPORTIVE/NEUTRAL/
  HOSTILE, combinando regime do BTC + força relativa do ativo +
  direção pretendida (nunca "BTC caiu = nenhuma altcoin pode subir" --
  Documento Master, seção 8).
- Nota de honestidade metodológica (documentada nos próprios módulos):
  os limiares (percentis, +2%/-2% de força relativa) são um ponto de
  partida razoável, não uma calibração estatística -- a refinar quando
  o Learning Engine (Fase 5) tiver dados reais de resultado.

## Playbook Library (`playbook/`)

- 7 estratégias iniciais (não as ~40 dos documentos — decisão já
  registrada no Plano de Evolução): Trend Continuation, EMA Pullback,
  Liquidity Sweep Reversal, Breakout + Retest, Compression Breakout,
  Range High Rejection, Range Low Rejection. Cada uma com regimes
  compatíveis, direção, estilo (day_trade/intraday/swing) e RR mínimo.
- `compatible_playbooks(regime, direction, style)` — filtro regime-first
  (Documento Master, seção 11). Lista vazia é o resultado correto
  quando nada é compatível — o Discovery Engine pula o ativo em vez de
  forçar um match.
- **Limitação declarada explicitamente**: são metadados de filtro,
  ainda NÃO validados por backtest (Documento 2, seção 11: BACKTEST ->
  OUT-OF-SAMPLE -> FORWARD TEST -> LIVE ELIGIBILITY). Cada uma é
  formalizável no `strategy_dsl` da Fase 1 e deveria passar por
  `POST /backtest/generic` antes de uso real — ainda não feito.

## Multi-Score Engine (`scoring/`)

- `compute_opportunity_score` — os 9 scores do Documento 2 (seção 12):
  Quality, Tradeability, Timing, Risk, Asymmetry, Confirmation, Setup
  Maturity, Statistical Edge, Overall. Nenhum é probabilidade de lucro
  (Documento Master, seção 75).
- `statistical_edge_available=False` sempre que não há
  `playbook_stats` com amostra >= 30 — nunca finge estatística que não
  existe (o Learning Engine que alimentaria isso de verdade é Fase 5).
- OVERALL_SCORE = média ponderada declarada dos outros 8 (pesos no
  código, ajustáveis — Documento Master seção 25 já autoriza isso
  explicitamente). Nota de honestidade metodológica: os pesos da seção
  25 do Documento Master (10 fatores) não mapeiam 1:1 com os 9 scores
  nomeados da seção 12 do Documento 2 — este módulo faz uma adaptação
  explícita entre os dois, documentada no próprio código.

## Correlated Exposure Engine (`discovery/correlation.py`)

- Separado do ranking (Documento Master, seção 20: primeiro RANKING,
  depois CORRELATION FILTER). Correlação de Pearson entre retornos;
  threshold 0.85 marca dois ativos como "a mesma aposta" — só o de
  score mais alto do cluster fica sem penalidade.

## Discovery Engine (`discovery/engine.py`)

- `scan_opportunities`: orquestra regime (ativo + BTC) -> força
  relativa -> contexto BTC -> filtro do Playbook -> estimativa de
  entry/stop/target a partir de suporte/resistência já calculados ->
  Multi-Score -> ranking -> Correlated Exposure Engine -> corte no
  `top_n`. Reaproveita `app.run_analysis` (mesmo pipeline de
  `/snapshot`/`/scan`) para trend/estrutura/score.
- Símbolos sem estratégia compatível no regime atual voltam em
  `no_edge`, com o motivo — nunca escondidos (Documento Master, seção 40).
- **Limitação declarada**: entry/stop/target são uma estimativa de
  primeiro corte a partir de suporte/resistência, não o "Trade Plan
  Generator" completo do Documento Master (seção 17) — bom para
  ranquear, não para tomar como plano de execução definitivo. 1
  timeframe por chamada (multi-timeframe de verdade, Documento Master
  seção 19, é trabalho futuro).

## Endpoint novo (aditivo)

- `GET /discovery/top-trades` — `symbols`, `btc_symbol`, `direction`,
  `style`, `timeframe`, `top_n`. Retorna `opportunities` (rankeadas),
  `no_edge`, `errors`, `btc_regime`, `disclaimer`.

## Limite de operações do GPT Actions (acompanhamento)

Schema OpenAPI agora: **13 operações, ~19KB** (era 12/~16KB na Fase 2).
Ainda dentro do limite de 30, mas a cada fase o consumo sobe de forma
previsível — Fase 4 (Risk Engine) deve adicionar 2-3 operações; vale
decidir sobre Actions separadas o mais tardar na Fase 5/6.

## Testes

```
pytest tests/ -q
# 266 passed (226 já existentes + 40 novos)
```

Novos: `tests/test_regime.py` (21 — detecção de regime, força relativa,
filtro BTC), `tests/test_scoring.py` (11 — multi-score, incluindo
garantia de que todo score fica em [0,100]), `tests/test_playbook_and_correlation.py`
(6 — filtro regime-first do Playbook, matriz de correlação, flag de
duplicatas), `tests/test_discovery_engine.py` (3 — smoke test ponta a
ponta do Discovery Engine com um `MarketDataProvider` fake, sem rede,
seguindo o mesmo padrão de `tests/test_market_data_facade.py`).

`discovery/engine.py` em si (a orquestração com rede real) segue a
mesma convenção já estabelecida no repo para `scanner/screener.py`:
não é coberta por teste de unidade além do smoke test com provider
fake — só as peças puras (`regime/`, `scoring/`, `playbook/`,
`discovery/correlation.py`) têm cobertura extensiva.
