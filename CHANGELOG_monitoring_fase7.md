# CHANGELOG — Fase 7: Monitoring + Scheduler + Conditional Plans

Implementa o Documento 2 (seção 34) e o Documento Master (seções 34,
43-44) do Plano de Evolução. 100% aditivo.

## Monitoring (`monitoring/`)

- `setup_monitor.py` — `evaluate_setup_update` (função pura): a partir
  do preço atual e do snapshot de um setup persistido, decide a
  transição de estado:
  - `FORMATION`/`WATCH` + preço dentro da `entry_zone` → `NEAR_ENTRY`.
  - Setup armado (`NEAR_ENTRY`/`READY`/`TRIGGERED`/`ENTRY_READY`/`ACTIVE`/
    `TP1`/`TP2`) + preço atingiu o stop → `INVALIDATED`.
  - Preço atingiu TP1/TP2/TP3 → avança para `TP1`/`TP2`, ou direto
    `COMPLETED` se não houver mais alvos além do atingido. TP3 sempre
    completa, mesmo vindo de `TP1`.
  - Stop tem prioridade sobre TP quando ambos seriam tecnicamente
    atingíveis (mesma convenção conservadora do `backtest/simulator.py`).
- `service.py` — `run_monitoring_cycle`: expira setups vencidos
  primeiro (reaproveita `setups.expiration.sweep_expired` da Fase 2),
  depois busca o preço atual de cada setup em aberto restante (via
  `MarketData.get_current_price`) e aplica as transições. Erro de
  preço num único ativo fica registrado em `errors` sem travar o ciclo
  inteiro.

## Scheduler

- `scripts/run_monitoring_cycle.py` — entrypoint do cron: roda o ciclo
  direto contra o banco (mesma `DATABASE_URL`), sem depender do
  serviço web estar de pé nem de autenticação entre serviços.
- `render.yaml` — `alphaquant-monitoring-cycle` (Render Cron Job, a
  cada 15 minutos, ajustável). **Nota**: Cron Jobs exigem plano pago no
  Render (Starter+) — o plano free do serviço web não cobre isso.

## Endpoint novo (aditivo)

- `POST /monitoring/run-cycle` — mesmo ciclo do cron, sob demanda via
  HTTP (ex.: o GPT rodar "atualiza meus setups agora" sem esperar o
  próximo tick).

## Limite de operações do GPT Actions

Schema OpenAPI: **25 operações, ~36KB** (era 24/~35KB na Fase 6) — só
+1 endpoint. Ainda dentro do limite técnico de 30, mas a margem
restante (5 operações) é pequena para a Fase 8, que ainda não teve o
escopo de endpoints detalhado. Decisão sobre múltiplas Actions
continua em aberto (você optou por decidir depois).

## Limitações conhecidas desta fase

- `evaluate_setup_update` usa o último preço (quote), não um candle
  fechado — pode reagir a um pavio momentâneo que nunca teria fechado
  ali. Aceitável para o objetivo (monitoramento entre análises, não
  execução automática), mas vale ter em mente.
- Sem alertas/notificações (push, email, Slack) — o ciclo só atualiza
  o estado persistido; alguém (o usuário, via GPT) ainda precisa
  consultar `/setups/{symbol}` ou `/opportunities` para saber o que
  mudou. Isso está dentro do escopo original da Fase 7 (Documento
  Master, seção 44: "somente se necessário" para alert service).
- Cron a cada 15 minutos é um ponto de partida — não foi calibrado
  contra o custo de chamadas de API dos providers de mercado.

## Testes

```
pytest tests/ -q
# 343 passed (325 já existentes + 18 novos)
```

`tests/test_monitoring.py` (13 — todas as transições de
`evaluate_setup_update`: entrada na zona, stop invalida, TP1/TP2/TP3
avançam ou completam conforme o que resta, long e short, prioridade do
stop) + `tests/test_monitoring_service.py` (5 — smoke test do ciclo
completo com SQLite em memória + provider de preço fixo, sem rede:
setup entra na zona, invalida no stop, completa no TP, expira antes de
buscar preço, erro de preço não derruba o ciclo). Script de cron
testado manualmente de dois diretórios de trabalho diferentes para
confirmar que resolve o path corretamente.
