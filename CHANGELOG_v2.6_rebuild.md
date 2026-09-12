# AlphaQuant Engine — v2.6 rebuild + 4 motores (Macro/Events/Unlocks/Fundamentals)

## Parte 1 — Deixando o projeto pronto (o zip original não rodava)

O zip `AlphaQuantEngine_v2_6_structure_consensus.zip` tinha dois
problemas que impediam o projeto de rodar:

1. **`server.py` estava vazio (0 bytes)** — o entrypoint FastAPI não
   existia. Reconstruído a partir do `README.md` (seção "Uso") e das
   assinaturas reais de `snapshot.build_market_snapshot`,
   `app.run_analysis` e `scanner.scan_market`. Expõe:
   - `GET /snapshot` — Market Snapshot completo (endpoint principal).
   - `GET /analyze` — análise single-timeframe (compat. Fase 1).
   - `GET /scan` — varredura multi-símbolo.
   - `GET /health` — health check.
   - `GET /openapi.json` — gerado automaticamente pelo FastAPI.

2. **O pacote `analysis/` inteiro estava faltando** — `app.py` e
   `snapshot/timeframe_snapshot.py` importavam
   `analysis.liquidity`, `analysis.score`, `analysis.support_resistance`
   e `analysis.trend`, nenhum dos quatro presentes no zip. Isso
   quebrava a coleta de 2 arquivos de teste inteiros
   (`test_json_contract.py`, `test_scanner.py`) e o projeto não subia.
   Reconstruído a partir do uso real desses dois arquivos (mesma
   assinatura, mesmo tipo de retorno):
   - `analysis/trend.py` — tendência final = empilhamento de EMAs +
     tendência estrutural; só assume Bullish/Bearish quando as duas
     leituras concordam, senão "Ranging".
   - `analysis/support_resistance.py` — clusteriza swing highs/lows
     próximos do preço atual em zonas de S/R.
   - `analysis/liquidity.py` — zonas de liquidez buy-side/sell-side a
     partir dos swings mais recentes.
   - `analysis/score.py` — score técnico 0-100 (tendência + momentum +
     estrutura + volume). Documentado explicitamente como SCORE
     TÉCNICO, não CONFIANÇA (Documento 4, seção 13) — não deve ser lido
     sozinho como "pode entrar".
   - `output/json_formatter.py` — serialização do `AnalysisResult`
     (também faltava, usado por `app.py`).

**Validação**: 148 → **159 testes passando** (0 falhas) após a
reconstrução, incluindo os 2 arquivos que antes nem coletavam. Smoke
test manual de ponta a ponta com dados sintéticos confirmou o pipeline
completo (indicadores → estrutura → análise → score) funcionando sem
erros. `server.py` testado com `fastapi.testclient.TestClient`.

## Parte 2 — Os 4 motores do Documento 4, seção 19

Pacote novo `fundamentals/`, com os 4 providers pedidos explicitamente
no documento de instruções ("Precisamos pesquisar as opções... Criar
interfaces abstratas... começar com fontes gratuitas..."). Nenhum
vendor pago foi contratado — cada motor tem uma avaliação de
custo/cobertura/limites documentada no próprio módulo, conforme a
seção 19 exige antes de qualquer compra.

Padrão comum aos 4 (`fundamentals/base.py`):
- Interface abstrata (contrato) independente de vendor.
- Uma implementação de referência **gratuita**.
- Um fallback `Null...Provider` explícito — nunca inventa/estima um
  valor; levanta `FundamentalsUnavailableError` com motivo claro,
  seguindo a mesma filosofia do `NoExchangeAvailableError` /
  `DataUnavailableError` já usados no resto do projeto.
- Suporte a **Point-in-Time** (Documento 4, seção 18): todo registro
  carrega `observed_at` (quando o dado ficou publicamente conhecido),
  separado da data a que o dado se refere. Backtesting pode filtrar
  por `observed_at <= as_of` para nunca vazar conhecimento futuro.

| # | Motor | Interface | Implementação de referência | Fonte |
|---|-------|-----------|------------------------------|-------|
| 1 | `fundamentals/macro.py` | `MacroDataProvider` | `FredMacroProvider` | FRED (St. Louis Fed) — grátis, requer API key gratuita |
| 2 | `fundamentals/events.py` | `EconomicEventsProvider` | `StaticCuratedEventsProvider` | Calendário local (JSON) — FOMC 2026 verificado contra federalreserve.gov |
| 3 | `fundamentals/unlocks.py` | `TokenUnlockProvider` | `DefiLlamaUnlockProvider` | DefiLlama `/emissions/{slug}` — grátis, sem API key |
| 4 | `fundamentals/crypto_fundamentals.py` | `CryptoFundamentalsProvider` | `CoinGeckoFundamentalsProvider` | CoinGecko `/coins/{id}` — grátis, sem API key |

### Motor 2 em detalhe — por que calendário estático em vez de vendor

Pesquisei calendários econômicos com API gratuita e sem restrição forte
de uso automatizado (Trading Economics, FXStreet/Investing.com,
ForexFactory) e não encontrei um equivalente "grátis e irrestrito" ao
que a DefiLlama oferece para unlocks. Em vez de bloquear a entrega
esperando aprovação de orçamento, o seed
(`fundamentals/data/events_calendar.json`) traz as 3 reuniões
restantes do FOMC em 2026 — **datas confirmadas na fonte oficial**
(federalreserve.gov, comunicado de 09/ago/2024):

- 16/set/2026, 28/out/2026, 09/dez/2026.

CPI, NFP e outros bancos centrais ainda não estão povoados. A tabela
de comparação de vendors pagos (Trading Economics vs. FXStreet vs.
ForexFactory) está no docstring do módulo, para preencher com cotação
real quando isso virar prioridade.

### Limitação importante — não testado contra rede real

Este ambiente de desenvolvimento não tem acesso às APIs externas
usadas pelas implementações de referência (`api.stlouisfed.org`,
`api.llama.fi`, `api.coingecko.com` estão fora da allowlist de rede do
sandbox). As 3 implementações HTTP (`FredMacroProvider`,
`DefiLlamaUnlockProvider`, `CoinGeckoFundamentalsProvider`) foram
escritas seguindo a documentação pública de cada API e cobertas por
**16 testes unitários com HTTP mockado** (parsing, Point-in-Time,
símbolo não mapeado, erro de rede) — mas nenhuma chamada real foi
feita. Antes de habilitar em produção: rodar uma chamada real contra
cada endpoint e confirmar o shape da resposta.

### O que NÃO foi feito nesta entrega (por escolha, não por esquecimento)

- **Nenhum dos 4 motores está conectado ao `snapshot/`.** São
  interfaces prontas para os motores superiores (Evidence & Scoring,
  Decision Intelligence) consumirem — a integração é uma decisão de
  produto separada (onde no payload do snapshot isso aparece, como
  isso combina com o Technical Score, etc.), não implícita no pedido
  de "montar os 4 motores".
- **`CryptoFundamentalsProvider` não é Point-in-Time de verdade** — o
  endpoint `/coins/{id}` da CoinGecko só expõe o estado atual. Isso
  está documentado explicitamente no módulo: não usar este motor para
  reconstruir o passado em backtest sem antes trocar pela variante
  `/coins/{id}/history`.
- **Data Confidence (seção 14)** e a combinação Score técnico × Data
  Confidence (seção 13) continuam pendentes — são a peça que consome
  estes 4 motores (junto com `validation/data_quality.py` e o
  `StructureConsensusEngine` já existente), mas é trabalho novo, não
  parte do pedido desta entrega.

## Arquivos novos

```
analysis/__init__.py
analysis/trend.py
analysis/support_resistance.py
analysis/liquidity.py
analysis/score.py
output/__init__.py
output/json_formatter.py
server.py
fundamentals/__init__.py
fundamentals/base.py
fundamentals/macro.py
fundamentals/events.py
fundamentals/unlocks.py
fundamentals/crypto_fundamentals.py
fundamentals/data/events_calendar.json
tests/test_fundamentals.py
backtest/registry.py
tests/test_backtest_registry.py
tests/test_backtest_endpoint.py
```

## Testes

```
pytest tests/ -q
# 194 passed
```

## Parte 3 — Backtest não funcionava + símbolos TradingView (CLUSDT.P) quebrados

Dois bugs relatados pelo usuário depois da entrega anterior:

### 3.1 — GPT não conseguia rodar backtest

**Causa raiz**: o motor de backtest (`backtest/simulator.py`,
`backtest/history_fetcher.py`, `backtest/strategy.py`,
`backtest/performance.py`) já existia completo e bem testado — mas
**não tinha nenhum endpoint HTTP**. O GPT só fala com o AlphaQuant
Engine via Action (HTTP), então não havia absolutamente nenhuma forma
de disparar um backtest, independente de quão bom o motor interno
fosse.

**Correção**:
- `backtest/registry.py` (novo) — registro nome público → `Strategy`
  concreta. Necessário porque o GPT só envia parâmetros estruturados a
  uma Action, nunca código Python; `"sma_cross"` é a única estratégia
  registrada por enquanto (a única implementada em
  `backtest/example_strategies.py` — os Playbooks reais do Documento 3
  ainda precisam ser codificados como `Strategy` antes de entrarem
  aqui).
- `GET /backtest/strategies` — lista as estratégias disponíveis.
- `POST /backtest` — recebe `symbol`, `timeframe`, `start`, `end`,
  `strategy`, `strategy_params`, `cost_model`; internamente chama
  `HistoryFetcher` (busca candles reais paginados) →
  `BacktestSimulator` (roda bar-a-bar, sem lookahead) →
  `calculate_performance`. Retorna metadados do histórico usado,
  relatório de performance completo (win rate, R médio, profit factor,
  drawdown, MAE/MFE) e a lista de trades individuais.
- Erros de dados (símbolo não suportado, histórico insuficiente, range
  inválido, estratégia não gerou nenhum trade) voltam como HTTP 422
  com o motivo — nunca um resultado parcial.
- **Validado de ponta a ponta** (não só testes unitários): rodei uma
  chamada real ao endpoint com um provider fake injetado (sem tocar
  rede), confirmando o fluxo completo símbolo → histórico → simulação
  → performance funcionando e retornando trades reais.

### 3.2 — `CLUSDT.P` (e qualquer símbolo copiado do TradingView) era rejeitado

**Causa raiz**: `.P` é a notação do TradingView para "isto é o
contrato perpétuo" (ex.: gráfico de "CLUSDT.P" na Bybit) — mas na API
real da Bybit esse mesmo ativo se chama só `CLUSDT`, diferenciado de
spot pelo parâmetro `category=linear`, não por sufixo no símbolo. O
`SymbolMapper` não removia esse `.P` nem um eventual prefixo de
exchange (`BYBIT:CLUSDT.P`), então qualquer símbolo colado direto de
um gráfico do TradingView — que é como o usuário efetivamente usa o
sistema — caía em `SymbolNotRecognizedError`. Isso não era um bug só
do CLUSDT: afetava QUALQUER par com `.P`, em todos os pontos do
sistema que resolvem símbolo (`snapshot`, `ProviderRouter`,
`CrossExchangeReconciliationEngine`, `StructureConsensusEngine`, e
agora também `/backtest`).

**Correção** (`symbols/mapper.py`): nova etapa de normalização antes
da resolução — remove prefixo `EXCHANGE:` e sufixo `.P` antes de
comparar contra a tabela de aliases ou o padrão de par cripto.
`CLUSDT.P`, `BYBIT:CLUSDT.P` e `CLUSDT` agora resolvem todos para o
mesmo `canonical_symbol` (`CLUSDT`, `crypto`). 6 testes de regressão
novos em `tests/test_symbol_mapper.py`.

## Testes (atualizado)

```
pytest tests/ -q
# 194 passed
```


## Deploy

Nenhuma variável de ambiente nova é obrigatória para o que já
funcionava antes (snapshot/analyze/scan continuam sem chave). Para
habilitar os motores novos:

- `FredMacroProvider(api_key=...)` — precisa de `FRED_API_KEY`
  (cadastro gratuito: https://fred.stlouisfed.org/docs/api/api_key.html).
- `DefiLlamaUnlockProvider` e `CoinGeckoFundamentalsProvider` — não
  precisam de chave, mas precisam de um mapa `symbol -> slug/id` do
  vendor (não existe um mapeamento automático `ARBUSDT -> arbitrum`
  hoje; passar explicitamente na instanciação).
- `StaticCuratedEventsProvider` — já funciona com o seed entregue.
