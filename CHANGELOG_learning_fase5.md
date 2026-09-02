# CHANGELOG — Fase 5: Learning Engine + External Signals + Call Reverse Engineering

Implementa o Documento 2 (seções 27-33) e o Documento Master (seções
27-33) do Plano de Evolução. 100% aditivo.

## Persistência (`persistence/models.py`)

- `SignalRecord` — sinal externo + contexto reconstruído (JSON) +
  resultado (opcional, preenchido depois) + classificação.

## Learning Engine (`learning/`)

- `schema.py` — `ExternalSignalInput` (entrada do sinal) e
  `SignalResultUpdate` (atualização posterior do resultado).
- `classification.py` — `classify_signal`: VALID_SIGNAL / WEAK_SIGNAL /
  LUCKY_WIN / GOOD_TRADE_BAD_RESULT / BAD_TRADE_GOOD_RESULT /
  PENDING_RESULT. Documento 2 (seção 27) nomeia as categorias sem dar o
  algoritmo — o mapeamento usado (quality_score × resultado) é uma
  interpretação explícita, documentada no próprio código, não uma
  transcrição literal. `quality_score` reaproveita `scoring.engine`
  (média de quality/confirmation), não duplica lógica.
- `reconstruction.py` — Call Reverse Engineering: busca candles
  históricos até `signal_time` (via `HistoryFetcher`, infra da Fase 1)
  e recalcula trend/estrutura/regime *como se fosse "agora" naquele
  instante*. Separa explicitamente FACT (calculado dos candles),
  INFERENCE (regra sobre o FACT, ex.: compatibilidade com Playbook) e
  deixa claro que HYPOTHESIS (a intenção de quem emitiu o sinal) nunca
  é gerada automaticamente — não é reconstruível a partir de candles.
- `repository.py` — I/O de `SignalRecord`.
- `hypotheses.py` — `build_hypotheses`: agrega sinais com resultado
  conhecido por estratégia (ou ativo), classifica
  OBSERVATION/IN_TEST/VALIDATED/REJECTED usando os mesmos limiares de
  amostra já estabelecidos no projeto (Documento 1, seção 14) — nunca
  declara VALIDATED com amostra < 30 (Documento Master, seção 29: "8
  calls não provam uma estratégia").

## Endpoints novos (aditivos)

- `POST /learning/signals` — registra sinal + reconstrói contexto
  histórico automaticamente. Classifica na hora se `result` já vier
  preenchido.
- `GET /learning/signals` — lista com filtros (asset, strategy_guess,
  signal_quality_label).
- `PATCH /learning/signals/{id}/result` — atualiza resultado quando
  ele passa a ser conhecido, reclassifica.
- `GET /learning/hypotheses` — agregação estatística por estratégia ou
  ativo.

## Limite de operações do GPT Actions — decisão explícita necessária

Schema OpenAPI agora: **23 operações, ~32KB** (era 19/~27KB na Fase 4).
Ainda dentro do limite técnico de 30, mas a margem ficou pequena: Fase
6 (Decision Eligibility) e Fase 7 (Monitoring/Scheduler) devem
adicionar mais 3-5 operações cada, o que ultrapassaria 30 antes do fim
do projeto. Fica registrado aqui como decisão pendente explícita (não
resolvida automaticamente, porque implica infraestrutura fora deste
repositório — configurar uma segunda Action no GPT Builder): dividir os
endpoints em 2 Actions (ex.: Action 1 = dados/análise/backtest/discovery,
já estável; Action 2 = setups/risk/learning/decision, ainda evoluindo)
antes de eu continuar para a Fase 6.

## Limitações conhecidas desta fase

- `reconstruct_context` não reconstrói o contexto BTC/força relativa do
  ativo no momento do sinal (só o contexto do próprio ativo) — mesma
  limitação de escopo do Discovery Engine da Fase 3, por ora.
- Sinais sem `result` entram no banco (úteis para Reverse Engineering
  qualitativo) mas ficam de fora da agregação de `/learning/hypotheses`
  até serem atualizados — nunca contam como "loss" ou "win" por omissão.
- Um único texto de `execution_quality` por sinal (não um histórico) —
  suficiente para o volume esperado nesta fase.

## Testes

```
pytest tests/ -q
# 309 passed (292 já existentes + 17 novos)
```

`tests/test_learning.py` (16 — classificação de sinais em todas as
combinações qualidade×resultado, motor de hipóteses: amostra pequena/
média/grande, grupos independentes, sinais sem resultado ignorados,
ordenação por tamanho de amostra) + `tests/test_learning_reconstruction.py`
(1 — smoke test da reconstrução histórica com provider fake, sem rede,
mesmo padrão de `tests/test_discovery_engine.py`). Fluxo completo
(`POST /learning/signals` -> `GET` -> `PATCH` -> `GET /learning/hypotheses`)
verificado manualmente via `TestClient` com provider fake.
