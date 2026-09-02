# AlphaQuant Engine — Scan de universo completo (Bybit) + performance

## Problema relatado

`/scan` (25 ativos fixos, `config.DEFAULT_SCAN_SYMBOLS`) levava
**3 a 5 minutos** por chamada, e cobria só uma watchlist fixa —
qualquer altcoin fora da lista nunca era vista.

## Diagnóstico (o que estava causando a lentidão)

1. **Requisição de ticker desperdiçada em toda busca de candles.**
   `ProviderRouter.get_market_data` sempre chamava `provider.get_quote`
   internamente para popular `MarketDataResult.quote` — campo que
   **nenhum lugar do código lia**. Isso significava 1 requisição HTTP
   extra, totalmente inútil, em toda chamada a `get_candles`/
   `get_ohlcv_dataframe`, em cima da chamada de `get_current_price`
   que o `run_analysis` já fazia depois. Ou seja: 3 requisições por
   `run_analysis`, não 2.
2. **Sessão HTTP nova por análise.** Cada símbolo, em cada timeframe,
   criava seu próprio `MarketData()` → `build_default_router()` →
   `BybitClient()`/`BinanceClient()` do zero (`market_data=None` era o
   padrão em `scanner/screener._scan_one`), pagando handshake TCP/TLS
   novo em vez de reaproveitar conexão keep-alive.
3. **Pool de conexões pequeno.** O default do `requests`/`urllib3`
   (10 conexões) virava gargalo assim que a concorrência do scan
   (`SCAN_CONCURRENCY=8`, já baixo) tentava abrir mais conexões
   simultâneas do que o pool suportava.
4. **500 candles buscados quando 200 bastam.** `run_analysis` usa
   `DEFAULT_KLINES_LIMIT=500` por padrão; o scan não precisa de tanto
   histórico por candle (EMA200 + margem de segurança já cobre com
   ~260).
5. **Watchlist fixa.** `DEFAULT_SCAN_SYMBOLS` tinha ~25 pares mantidos
   manualmente — não refletia listagens novas da Bybit nem permitia
   varrer o mercado inteiro.

## O que foi feito

### 1. Universo dinâmico da Bybit (`providers/bybit_universe.py`, novo)

- `get_all_bybit_usdt_perpetuals()`: pagina `GET
  /v5/market/instruments-info` (`category=linear`, `quoteCoin=USDT`)
  e devolve todos os perpétuos negociáveis. Cache em memória com TTL
  de 6h (`config.SCAN_UNIVERSE_CACHE_TTL_SECONDS`) — a lista de pares
  muda pouco por dia. Se a Bybit falhar e houver cache anterior,
  degrada para o cache em vez de derrubar o scan inteiro.
- `get_bulk_ticker_snapshot()`: `GET /v5/market/tickers` **sem**
  `symbol` — devolve o ticker do mercado inteiro em UMA chamada HTTP.
  Sem cache (preço muda a cada segundo); o ganho vem de ser 1 chamada
  para todo o mercado em vez de 1 por símbolo.

### 2. Filtro rápido em duas etapas (`scanner/fast_filter.py`, novo)

`scanner.screener.scan_universe()` reduz o universo completo (~300+
símbolos) para um punhado de candidatos ANTES de gastar qualquer
candle/indicador neles:

- **Stage 1** (custo: os 1-2 requests acima, para o mercado inteiro):
  descarta ativos com liquidez abaixo de
  `SCAN_STAGE1_MIN_TURNOVER_USDT` (turnover 24h, padrão US$ 3M) e
  rankeia o resto por um score de atividade (volatilidade 24h +
  força do movimento 24h), usando só os campos do ticker em lote —
  zero candles.
- **Stage 2** (cara, só nos sobreviventes): roda o pipeline completo
  existente (`app.run_analysis`, indicadores + estrutura + score) nos
  `SCAN_STAGE1_TOP_N` (padrão 60) melhores candidatos da Stage 1,
  reaproveitando o preço já obtido no ticker em lote (não busca ticker
  de novo).

O retorno (`UniverseScanResult`) expõe `universe_size`,
`stage1_candidates` e `stage1_min_turnover_usdt` para transparência do
funil — a instrução do GPT (arquivo 16) foi atualizada para sempre
citar esses números ao usuário.

### 3. Eliminação da requisição de ticker desperdiçada

- `providers/router.py`: `get_market_data` ganhou um parâmetro
  `fetch_quote: bool = True`. Quando `False`, pula a chamada de rede
  ao ticker e devolve `quote=None` (`MarketDataResult.quote` agora é
  `Quote | None`).
- `api/market_data.py`: `MarketData.get_candles` passa
  `fetch_quote=False` — ninguém consumia esse campo neste caminho.
  Corta 1 requisição HTTP por símbolo/timeframe **em todo o sistema**
  (não só no scan): `/snapshot`, `/analyze`, CLI, discovery.
- `app.py`: `run_analysis` ganhou um parâmetro `current_price: float |
  None = None`. Quando informado, pula a chamada dedicada de
  `get_current_price` e usa o valor recebido — é isso que permite ao
  `scan_universe` reaproveitar o preço da Stage 1 na Stage 2, evitando
  1 requisição de ticker por símbolo por timeframe.

### 4. Sessão HTTP e concorrência

- `providers/bybit_client.py`: `BybitClient` agora monta um
  `HTTPAdapter` com `pool_connections`/`pool_maxsize=64`
  (`CONNECTION_POOL_SIZE`) em vez do default de 10 do `requests`.
- `scanner/screener.py`: `scan_market`/`scan_universe` criam **um
  único `ProviderRouter`** (`build_default_router()`) para o scan
  inteiro, compartilhado entre todas as threads do
  `ThreadPoolExecutor` — reaproveita conexões TCP/TLS em vez de abrir
  uma sessão nova por símbolo.
  - **Cuidado de concorrência**: o `ProviderRouter` é compartilhado
    (stateless, seguro), mas cada chamada a `_scan_one` cria seu
    PRÓPRIO `MarketData` leve (`MarketData(router=router)`). Isso é
    proposital — `MarketData.last_result` é mutável, e compartilhar o
    mesmo `MarketData` entre threads faria uma thread ler a
    proveniência (`data_source`) de OUTRO símbolo no meio de uma
    corrida. Validado com um teste de stress de 40 símbolos em
    paralelo (ver seção de testes) confirmando que não há
    contaminação cruzada.
- `config.py`: `SCAN_CONCURRENCY` subiu de 8 → 25.

### 5. Menos dado buscado por chamada no scan

- `config.SCAN_KLINES_LIMIT = 260` (era 500 via
  `DEFAULT_KLINES_LIMIT`) — `scanner.screener._scan_one` agora passa
  esse limite explicitamente para `run_analysis`.

### 6. Novo endpoint `/scan?universe=all_bybit`

- `server.py`: `/scan` ganhou os parâmetros `universe` (`"watchlist"`
  padrão | `"all_bybit"`), `top_n` e `min_turnover_usdt`. Modo
  `watchlist` preserva 100% o comportamento anterior (compatibilidade
  com quem já usa `symbols=`).
- `UniverseUnavailableError` (Bybit fora do ar e sem cache de universo
  utilizável) vira HTTP 502.

## Impacto esperado

Com o funil de duas etapas, a Stage 2 (a única parte cara) roda sobre
~60 candidatos em vez de ~300+, com metade das requisições por símbolo
(quote eliminado do caminho de candles, preço reaproveitado da Stage
1), sessão HTTP reaproveitada e mais concorrência. Nenhuma chamada de
rede real foi feita neste ambiente (sandbox sem acesso à internet),
então o tempo abaixo é uma estimativa de arquitetura, não uma medição:
scan do mercado Bybit inteiro em segundos a baixa dezena de segundos,
em vez de 3-5 minutos, mesmo cobrindo 10x+ mais ativos.

## Arquivos novos

- `providers/bybit_universe.py`
- `scanner/fast_filter.py`

## Arquivos alterados

- `providers/bybit_client.py` — `get_all_tickers`,
  `get_all_linear_usdt_symbols`, pool de conexões.
- `providers/router.py` — `get_market_data(fetch_quote=...)`,
  `MarketDataResult.quote` agora opcional.
- `api/market_data.py` — `get_candles` usa `fetch_quote=False`.
- `app.py` — `run_analysis(current_price=...)`.
- `scanner/screener.py` — `scan_universe`, `UniverseScanResult`,
  router compartilhado, `SCAN_KLINES_LIMIT`.
- `config.py` — `SCAN_CONCURRENCY` (8→25), `SCAN_KLINES_LIMIT`,
  `SCAN_STAGE1_TOP_N`, `SCAN_STAGE1_MIN_TURNOVER_USDT`,
  `SCAN_UNIVERSE_CACHE_TTL_SECONDS`, `SCAN_MAX_SYMBOLS` (40→60,
  aplica só ao modo `watchlist`).
- `server.py` — `/scan` com `universe`/`top_n`/`min_turnover_usdt`.

## Testado neste ambiente (sem acesso à rede)

- Sintaxe de todos os arquivos novos/alterados (`ast.parse`).
- Suíte de testes existente do projeto rodada com um shim mínimo de
  `pytest` (sem rede/pip disponível para instalar o pacote real):
  **42/42 testes passando** em `test_market_data_facade`,
  `test_provider_router`, `test_scanner`,
  `test_bybit_and_binance_providers` — nenhuma regressão introduzida
  pela remoção do fetch de quote nem pelas mudanças de assinatura.
- `get_all_linear_usdt_symbols`: paginação via `nextPageCursor` e
  filtro `quoteCoin=USDT` testados com resposta simulada de 2 páginas.
- `get_bulk_ticker_snapshot`: parsing testado com linha malformada no
  meio do lote (ignora essa linha, não derruba o snapshot inteiro).
- Cache de universo: testado que uma segunda chamada dentro do TTL não
  gera nova requisição.
- `rank_candidates` (Stage 1): testado que um ativo ilíquido é
  descartado e um ativo de alta atividade é priorizado sobre um ativo
  de alta liquidez mas baixa atividade.
- `_scan_one` ponta a ponta com provider mockado (sem rede),
  incluindo verificação de que `current_price` é propagado
  corretamente até o resultado final.
- Teste de stress de concorrência: 40 símbolos em paralelo
  (`ThreadPoolExecutor`, 20 workers) com um `ProviderRouter`
  compartilhado — cada símbolo retornou exatamente o próprio preço
  esperado, sem nenhuma contaminação cruzada entre threads.
- `UniverseScanResult` (dataclass com `slots=True` herdando de
  `ScanResult`): testado `to_dict()` — houve um bug real pego neste
  teste (`super()` quebra com `slots=True` em dataclasses herdadas) e
  corrigido chamando `ScanResult.to_dict(self)` explicitamente.

## Não testado end-to-end neste ambiente

Sem acesso à rede, não foi possível instalar `fastapi`/`pydantic` nem
chamar a API real da Bybit. **Antes de considerar pronto**: rodar
localmente (`uvicorn server:app --reload`) e chamar
`/scan?universe=all_bybit` de verdade, medir o tempo de resposta real,
e confirmar que o volume de dados (300+ símbolos no universo) não
estoura nenhum timeout do lado do GPT Action (costuma ser baixo,
~45s) — se a Stage 2 com `top_n=60` ainda for lenta demais na prática,
reduzir `top_n` primeiro antes de mexer em concorrência/timeouts.

## Deploy

Mesmo processo de sempre: sobrescrever os arquivos no repositório e
redeployar no Render. O schema OpenAPI do `/scan` é gerado
automaticamente pelo FastAPI a partir dos novos `Query(...)` em
`server.py` — não precisa editar nenhum JSON à mão, só re-sincronizar
a Action do GPT (Configurar → Importar do URL do schema) depois do
deploy para os parâmetros novos (`universe`, `top_n`,
`min_turnover_usdt`) aparecerem disponíveis para a IA.
