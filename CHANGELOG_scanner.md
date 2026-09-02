# AlphaQuant Engine — Scanner (multi-símbolo)

## O que foi adicionado

Novo endpoint **`GET /scan`**, que varre uma lista de símbolos (ou a
watchlist padrão em `config.DEFAULT_SCAN_SYMBOLS`) em dois timeframes
(HTF = contexto, LTF = gatilho) e classifica cada um em:

- `entry_zone` — preço já dentro de uma zona de suporte/resistência
  relevante, score combinado ≥ 70, sem conflito de tendência HTF×LTF.
- `watch` — se aproximando de uma zona (≤ 2%) e/ou score ≥ 60.
- `out_of_zone` — sem confluência agora (omitido por padrão).

## Arquivos novos

- `scanner/__init__.py`
- `scanner/screener.py` — lógica de varredura, distância até a zona e
  classificação.
- `tests/test_scanner.py` — testes da lógica pura (classificação e
  distância), sem dependência de rede.
- `openapi_v2.1_com_scan.json` — schema atualizado com `/scan`, para
  re-sincronizar a Action do GPT.

## Arquivos alterados

- `config.py` — novos parâmetros `DEFAULT_SCAN_SYMBOLS`,
  `DEFAULT_SCAN_HTF/LTF`, `SCAN_CONCURRENCY`, `SCAN_MAX_SYMBOLS`,
  `SCAN_ENTRY_ZONE_PCT`, `SCAN_WATCH_ZONE_PCT`,
  `SCAN_MIN_SCORE_ENTRY`, `SCAN_MIN_SCORE_WATCH`.
- `server.py` — importa `scanner.scan_market` e expõe `GET /scan`.

## Reaproveitamento

Não duplica lógica de indicadores/estrutura/score: cada símbolo é
processado com `app.run_analysis` (o mesmo pipeline do `/analyze`),
só que em lote e com `ThreadPoolExecutor` para paralelizar as
chamadas HTTP à Binance.

## Limitação importante (documentada também na instrução da IA)

`/scan` é uma varredura **pontual**, do momento em que é chamada —
não é um monitoramento contínuo nem envia push/alerta sozinho. Um GPT
customizado só roda quando o usuário manda mensagem; não há como ele
avisar "sozinho" no meio do dia. O jeito de emular "fica de olho
durante o dia" é o usuário chamar de novo periodicamente (o
Arquivo 25 orienta a IA a sugerir isso).

## Não testado end-to-end neste ambiente

Este sandbox não tem acesso à rede, então não deu para instalar
`fastapi`/`pandas`/`requests` nem chamar a Binance de verdade daqui.
O que foi validado:

- Sintaxe de todos os arquivos novos/alterados (`ast.parse`).
- Lógica pura de classificação e cálculo de distância
  (`_classify`, `_nearest_zone`) replicada e testada isoladamente —
  7 casos, todos passando.
- Consistência do schema OpenAPI (`json.load` sem erro).

**Antes de considerar pronto**, rode localmente (`uvicorn server:app
--reload`) e chame `/scan` de verdade contra a Binance, e rode
`pytest tests/ -q` — o pipeline usado pelo scan (`run_analysis`) já é
coberto pelos testes existentes do projeto, só o scanner em si que é
novo.

## Deploy

Mesmo processo do v2.1: sobrescrever os arquivos no repositório
(inclusive o `AlphaQuantAI-main`, que hoje está atrasado — falta o
`order_flow` do v2.1 além disso) e redeployar no Render. Depois,
re-importar/sincronizar o `openapi_v2.1_com_scan.json` na Action do
GPT para o `/scan` aparecer disponível pra IA.
