# AlphaQuant Engine

Motor Python que consome dados públicos da Binance (Spot + Futures),
calcula indicadores técnicos, estrutura de mercado, Smart Money
Concepts, Volume Profile, estatística e derivativos — gerando um
Market Snapshot multi-timeframe estruturado, para que um GPT
especializado consiga analisar qualquer ativo sem depender de prints
de gráfico. Serve como backend de dados para o **AlphaQuant X**.

## Visão geral do pipeline

```
Binance Spot (público)          Binance Futures (público)
        │                                │
        ▼                                ▼
   api/  ── klines, price, depth    derivatives/ ── OI, funding, L/S ratio
        │
        ▼
indicators/ ── EMA/RSI/ATR/MACD/Volume + ADX/CCI/MFI/Stoch/OBV/CMF/
               Bollinger/Donchian/Keltner/SuperTrend/SAR/Ichimoku/VWAP
        │
        ▼
structure/ ── Swings, HH/HL/LH/LL, BOS, CHOCH
smc/       ── Order Blocks, Breaker Blocks, FVG/iFVG, Equal H/L,
               Liquidity Sweeps, Premium/Discount/OTE
volume_profile/ ── POC, VAH, VAL, HVN, LVN
statistics_/    ── Z-score, volatilidade histórica/realizada, percentis
        │
        ▼
analysis/ ── Tendência final, Suporte/Resistência, Liquidez, Score
        │
        ▼
snapshot/ ── Orquestrador multi-timeframe (15m/1H/4H/1D) + confluência
        │
        ▼
output/ ── JSON padronizado (single timeframe) | snapshot/ (multi-timeframe)
```

## Estrutura do projeto

```
AlphaQuantEngine/
├── app.py                       # Orquestrador single-timeframe / CLI
├── server.py                    # API HTTP (FastAPI) — /analyze e /snapshot
├── config.py                    # Configurações centrais
├── requirements.txt
├── Dockerfile / .dockerignore / render.yaml
├── README.md
├── .env.example
│
├── api/                         # Binance Spot (klines, price, depth)
├── derivatives/                 # Binance Futures (OI, funding, L/S ratio)
├── indicators/                  # Indicadores clássicos + estendidos
├── structure/                   # Swings, HH/HL/LH/LL, BOS, CHOCH
├── smc/                         # Smart Money Concepts
├── volume_profile/              # POC, VAH, VAL, HVN, LVN
├── statistics_/                 # Z-score, volatilidade, percentis
├── analysis/                    # Tendência, S/R, liquidez, score
├── snapshot/                    # Orquestrador multi-timeframe + confluência
├── models/                      # Candle, AnalysisResult
├── output/                      # Formatação JSON
└── tests/                       # 33 testes unitários (pytest)
```

## Instalação

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # opcional (nenhuma chave é necessária)
```

## Uso

### API HTTP (recomendado — é o que o GPT consome)

```bash
uvicorn server:app --reload --port 8000
```

- **`GET /snapshot?symbol=ETHUSDT&timeframes=15m,1H,4H,1D`** — Market
  Snapshot completo: indicadores, estrutura, SMC, volume profile,
  estatística, derivativos e confluência multi-timeframe. **Este é o
  endpoint principal.**
- **`GET /analyze?symbol=ETHUSDT&timeframe=4H`** — análise de um único
  timeframe (mantido por compatibilidade, escopo da Fase 1).
- **`GET /health`** — health check.
- **`GET /openapi.json`** — schema usado para configurar a Action do GPT.

### Via linha de comando (single-timeframe)

```bash
python app.py --symbol ETHUSDT --timeframe 4H
```

### Via código

```python
from snapshot import build_market_snapshot

result = build_market_snapshot(symbol="ETHUSDT", timeframes=("15m", "1H", "4H", "1D"))
print(result.to_dict())
```

## Timeframes suportados

`1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 8H, 12H, 1D, 3D, 1W, 1M`
(ver `config.TIMEFRAME_MAP`).

## Testes

```bash
pytest tests/ -v
```

## Decisões de implementação

- **Sem `pandas-ta`**: os indicadores foram implementados diretamente
  com `pandas`/`numpy` (suavização de Wilder onde aplicável), evitando
  fixar o projeto a uma dependência externa com histórico de
  incompatibilidade com versões recentes de `pandas`/`numpy`.
- **Volume Profile via candles OHLCV**: como a Binance não fornece
  volume por nível de preço via REST público, o perfil é aproximado
  distribuindo o volume de cada candle ao longo do seu range
  (high-low) — a mesma aproximação usada pela maioria das plataformas
  quando não há dados de tick.
- **Derivativos via Binance Futures (não CoinGlass)**: Open Interest,
  Funding Rate e Long/Short Ratio são obtidos direto da Binance
  Futures (endpoints públicos, sem chave), evitando dependência de um
  provedor pago. Se o par não tiver contrato futuro, o snapshot marca
  `available: false` sem quebrar a análise Spot.
- **Deploy fora dos EUA**: a Binance bloqueia requisições vindas de
  infraestrutura de cloud nos EUA (HTTP 451). Use regiões como
  Singapore ou Frankfurt no provedor de hospedagem.

## Roadmap

- [x] **Fase 1** — Integração Binance Spot, indicadores clássicos, estrutura básica, JSON single-timeframe.
- [x] **Fase 2** — Smart Money Concepts completo, Volume Profile, VWAP, indicadores estendidos, estatística.
- [x] **Fase 3** — Derivativos (Open Interest, Funding Rate, Long/Short Ratio) via Binance Futures.
- [x] **Fase 4** — Orquestrador multi-timeframe (15m/1H/4H/1D) + Market Snapshot + confluência.
- [ ] **Fase 5** — Order Flow de tick-level (delta/CVD real via stream de trades, absorção, icebergs) — requer infraestrutura de websocket/armazenamento separada.
- [ ] Cache inteligente (Redis) para reduzir chamadas repetidas à Binance em janelas curtas de tempo.
- [ ] Processamento assíncrono dos 4 timeframes em paralelo (atualmente sequencial).

