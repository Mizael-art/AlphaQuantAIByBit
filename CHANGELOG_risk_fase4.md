# CHANGELOG — Fase 4: Risk Engine Central

Implementa o Documento 2 (seção 21) e o Documento Master (seções 21,
22, 32, 56, 73) do Plano de Evolução. Correlated Exposure Engine já foi
construído na Fase 3 (`discovery/correlation.py`) — esta fase adiciona
os limites por trade/dia/semana/mês, open risk, risk of ruin e capital
allocation. 100% aditivo.

## Persistência (`persistence/models.py`)

- `AccountState` — singleton por `account_id`: capital (inicial +
  atual) e os 5 limites configuráveis (risco por trade, perda diária/
  semanal, drawdown mensal, open risk máximo).
- `OpenPositionRecord` — posições abertas; soma de `risk_pct` = open
  risk agregado.
- `RiskEvent` — log de trades encerrados (realizado), base para os
  limites de perda por janela de tempo.

## Risk Engine (`risk/`)

- `engine.py` — `evaluate_trade_risk` (função pura, sem I/O): aplica os
  limites em ordem de prioridade -- perda diária/semanal/mensal são
  STOP absoluto (rejeita, nunca reduz parcialmente); correlação com
  posição já aberta rejeita; risco por trade e open risk reduzem até o
  espaço disponível. Retorna `APPROVED | REDUCED | REJECTED` com motivo
  explícito em cada linha de decisão (Documento Master, seção 77: "não
  usar 'Aguardar' como resposta de segurança" -- aqui, nunca REJECTED
  sem dizer exatamente qual limite foi violado).
- `repository.py` — I/O sobre a `Session`: soma PnL realizado por
  janela (24h/7d/30d a partir de `now`), soma open risk, detecta
  posição correlacionada já aberta, abre/fecha posições, atualiza
  capital ao fechar.
- `ruin.py` — `estimate_risk_of_ruin`: aproximação analítica clássica
  (edge = win_rate×payoff - loss_rate; risk_of_ruin ≈ ((1-edge)/(1+edge))^unidades).
  Declarado explicitamente como aproximação (trades i.i.d., edge
  constante, sem custos) — não uma simulação Monte Carlo.
- `capital_allocation.py` — `classify_capital_priority`:
  CORE/NORMAL/REDUCED/WATCH_ONLY, só rótulo de prioridade relativa
  (nunca altera risco sozinho — isso é sempre `risk/engine.py`).

## Endpoints novos (aditivos)

- `POST /risk/account` — cria/atualiza conta e limites (capital inicial
  sempre explícito, nunca assumido).
- `GET /risk/state` — capital, PnL realizado (dia/semana/mês), open
  risk, posições abertas.
- `POST /risk/evaluate` — avalia um trade proposto SEM abrir posição.
- `POST /risk/positions` — avalia E abre (com o risco efetivamente
  aprovado, nunca o solicitado se for maior); 422 se REJECTED.
- `POST /risk/positions/{id}/close` — encerra posição, registra
  resultado, atualiza capital.
- `POST /risk/ruin` — Risk of Ruin sob demanda (win rate, payoff,
  risco por trade).

## Limite de operações do GPT Actions (acompanhamento — agora mais sério)

Schema OpenAPI: **19 operações, ~27KB** (era 13/~19KB na Fase 3). A
salto foi maior nesta fase (6 endpoints novos) — a partir da Fase 5
(Learning Engine) recomendo já decidir a divisão em mais de uma Action/
serviço, em vez de esperar chegar perto do teto de 30.

## Limitações conhecidas desta fase

- Um único `account_id` por padrão ("default") — múltiplas contas
  funcionam (o schema já suporta), mas nada no sistema ainda escolhe
  automaticamente qual conta usar; é responsabilidade de quem chama a
  API informar `account_id`.
- `risk_pct` de uma posição aberta é fixo até o fechamento — não há
  ainda ajuste automático de risco em posições já abertas (ex.: reduzir
  risco de uma posição existente quando um novo trade correlacionado
  aparece). Hoje o sistema só REJEITA o novo trade.
- `estimate_risk_of_ruin` assume trades independentes e edge
  constante — não modela sequências de perdas correlacionadas nem
  mudança de regime no meio da série.
- Ainda não há integração entre `/discovery/top-trades` (Fase 3) e
  `/risk/evaluate` — o Decision Eligibility (Fase 6) é quem vai unir
  os dois automaticamente. Por ora, são consultados separadamente.

## Testes

```
pytest tests/ -q
# 292 passed (266 já existentes + 26 novos)
```

`tests/test_risk_engine.py` (18 — decisão pura: aprovação, rejeição por
cada limite, redução por teto de risco/open risk, risk of ruin,
capital allocation) + `tests/test_risk_repository.py` (8 — I/O:
criação de conta, abrir/fechar posição atualiza capital, soma de PnL
por janela de tempo, detecção de correlação). Smoke test manual via
`TestClient` confirmou o fluxo completo (conta -> evaluate -> open ->
rejeição por correlação -> close -> ruin).
