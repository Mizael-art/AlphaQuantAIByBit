# AlphaQuant Engine — v2.1 (Order Flow / Delta / CVD)

## O que mudou

O `/snapshot` (e o `/analyze`) agora retorna um novo bloco `order_flow`
em cada timeframe, ao lado de `indicators`, `structure`, `smc`,
`volume_profile` e `statistics`:

```json
"order_flow": {
  "delta_last_candle": 120.28,
  "buy_volume_pct_last_candle": 61.83,
  "dominant_side_last_candle": "buyers",
  "cvd_last": 1114.79,
  "cvd_trend": "flat",
  "cvd_slope_pct": -1.23,
  "cvd_price_divergence": "bullish",
  "lookback_used": 20,
  "method": "taker_buy_volume_proxy",
  "note": "..."
}
```

## Por que isso importa

As instruções originais (arquivo 06 — Volume & Order Flow Engine)
pediam explicitamente **Delta** e leitura de fluxo, mas o motor só
tinha `volume`, `volume_avg`, `obv` e `cmf` — nenhum deles é Delta de
fato (todos são baseados em volume total, não em quem iniciou a
ordem). Isso forçava a IA a "inventar" ou aproximar Delta a partir de
OBV, o que não é a mesma coisa e violava a regra de "nunca inventar
dado que não está no JSON".

A Binance já devolve, **de graça, em todo candle de `/klines`**, o
campo `taker_buy_base_volume` — quanto daquele candle foi volume
iniciado por ordens de mercado compradoras. Isso permite calcular:

- **Delta por candle** = `(2 × taker_buy_volume) − volume`
- **CVD (Cumulative Volume Delta)** = soma acumulada do delta ao longo
  da janela de candles retornada
- **Divergência CVD × Preço** = quando o preço faz um novo
  topo/fundo mas o CVD não acompanha (sinal clássico de exaustão,
  muito usado para confirmar Spring/UTAD no Wyckoff)

Não precisou de nenhuma chamada extra à API nem do endpoint
`/aggTrades` (que seria pesado e gastaria muito mais rate limit em
timeframes com centenas de candles).

## Limitação (documentada no próprio JSON, campo `note`)

Isso é uma **aproximação por candle**, não Delta de tick-a-tick. É
essencially o mesmo método que a maioria das ferramentas de order flow
de varejo usa quando não têm acesso a feed de trades individuais. Para
Delta "verdadeiro" (por trade), seria necessário consumir
`/aggTrades` — o que é possível como Fase 2 caso a granularidade atual
não seja suficiente, mas custa muito mais requisições (um símbolo/TF
de 500 candles pode ter dezenas de milhares de trades).

## Arquivos alterados/criados

- `models/candle.py` — novo campo `taker_buy_volume`
- `api/market_data.py` — propaga a coluna no DataFrame
- `order_flow/__init__.py` (novo)
- `order_flow/delta.py` (novo) — cálculo de Delta/CVD/divergência
- `snapshot/timeframe_snapshot.py` — integra `order_flow` no payload
- `tests/test_order_flow.py` (novo) — 5 testes, todos passando

Rodei a suíte completa (`pytest tests/ -q`) após a mudança: **38/38
testes passando**, incluindo os 5 novos.

## Deploy

Nenhuma variável de ambiente ou dependência nova — é só substituir os
arquivos no seu repositório (ou aplicar o zip anexado por cima) e
redeployar no Render normalmente. O schema OpenAPI (`/openapi.json`)
muda automaticamente porque o `FlexibleJSONResponse` já aceita
`additionalProperties: true` — não precisa reimportar a Action no GPT,
só re-sincronizar o schema se o seu builder cachear o schema antigo.
