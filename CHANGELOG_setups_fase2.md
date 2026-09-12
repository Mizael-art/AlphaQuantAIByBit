# CHANGELOG — Fase 2: Persistência + Setup Lifecycle + Setup Memory

Implementa o Documento 2 (seções 13-15, 41) e o Documento Master (seções
13-15, 34, 46) do Plano de Evolução — a parte de persistência/lifecycle,
não o Discovery Engine em si (isso é Fase 3). 100% aditivo: nenhum
endpoint/comportamento anterior foi alterado.

## Persistência (`persistence/`)

- `models.py` — `SetupRecord` (ORM SQLAlchemy 2.x): asset, direction,
  strategy, status, entry_zone, trigger, stop, tp1-3, rr, score +
  `score_history` (JSON), invalidation, expiration, reason_for_change,
  created_at/updated_at/status_changed_at.
- `db.py` — engine/sessão. Produção: `DATABASE_URL` (Postgres gerenciado
  no Render). Local/testes: SQLite (arquivo por default, `:memory:` nos
  testes). Normaliza `postgres://`/`postgresql://` (formato que o Render
  entrega) para `postgresql+psycopg://` (driver instalado).
- Só a tabela `setups` nesta fase — `signals`, `playbooks`, `backtests`
  salvos etc. (Documento Master, seção 46) ficam para quando as fases
  que realmente as usam (5, 3/6) existirem.

## Setup Lifecycle + Setup Memory (`setups/`)

- `lifecycle.py` — os 14 estados do Documento 2 (seção 13) / Master
  (seção 13): FORMATION, WATCH, NEAR_ENTRY, READY, TRIGGERED,
  ENTRY_READY, ACTIVE, TP1, TP2, TP3, COMPLETED, INVALIDATED, EXPIRED,
  CANCELLED. Único travamento real: nunca sai de um estado terminal
  (`InvalidTransitionError`) — um novo candidato pro mesmo
  ativo+direção+estratégia vira um setup NOVO, nunca reabre o antigo.
- `memory.py` — `upsert_setup`: se já existe um setup em aberto (status
  não-terminal) para o mesmo `asset+direction+strategy`, ATUALIZA (nunca
  duplica); senão cria. Classifica a mudança em
  `new / activated / improved / worsened / invalidated / expired /
  unchanged` (Documento 2, seção 41 — "NOVOS/MELHORARAM/PIORARAM/
  ATIVADOS/INVALIDADOS/EXPIRADOS").
- `expiration.py` — `sweep_expired`: marca `EXPIRED` todo setup em aberto
  cujo `expiration` já passou. Pronta para o scheduler automático da
  Fase 7 chamar periodicamente — hoje funciona sob demanda via endpoint.
- `schema.py` — `SetupCandidate` (Pydantic, `extra="forbid"`) — schema de
  entrada tanto para o GPT registrar um setup manualmente hoje quanto
  para o Discovery Engine da Fase 3 alimentar automaticamente depois.

## Endpoints novos (aditivos)

- `POST /setups` — registra um candidato (cria ou atualiza via Setup
  Memory). Retorna `created`, `change_type`, `setup`.
- `GET /setups/{symbol}` — setups conhecidos de um ativo (default: só
  não-terminais; `include_terminal=true` traz tudo).
- `GET /opportunities` — todos os setups em aberto. `status` filtra por
  estado; `since` (ISO 8601) traz só o que mudou desde aquele momento
  (Documento Master, seção 14 — evita reprocessar tudo a cada chamada).
  Isto é a base sobre a qual a Fase 3 constrói o ranking/Top Trades — o
  Discovery Engine em si ainda não existe, então hoje esta lista só
  reflete o que foi registrado via `POST /setups`.
- `POST /setups/sweep-expired` — varre e expira setups vencidos (sob
  demanda; scheduler automático é Fase 7).

## Infra

- `requirements.txt` — `sqlalchemy>=2.0.0`, `psycopg[binary]>=3.1.0`.
- `render.yaml` — serviço Postgres gerenciado (`alphaquant-db`, plano
  free) + `DATABASE_URL` injetada automaticamente no serviço web.

## Limite de operações do GPT Actions (acompanhamento)

Schema OpenAPI agora: **12 operações, ~16KB** (era 8/~11KB na Fase 1).
Ainda folgado frente ao limite de 30 operações / ~1MB, mas a trajetória
confirma o que já estava previsto — vale reavaliar a divisão em mais de
uma Action a partir da Fase 3 (quando `/top-trades`, `/setups` com mais
verbos etc. entrarem).

## Limitações conhecidas desta fase

- Não há ainda quem POSTe setups automaticamente — a Fase 3 (Discovery/
  Ranking Engine) é quem vai alimentar `/setups` a partir do scanner.
  Por ora, `/opportunities` só mostra o que for registrado manualmente
  (ex.: pelo GPT, ao identificar um setup numa conversa).
- Migrations: `Base.metadata.create_all()` cria a tabela se não existir,
  mas não há Alembic (nem é necessário ainda, com 1 tabela) — a decidir
  quando o schema começar a evoluir com frequência.
- `reason_for_change` guarda só a última razão, não um histórico
  completo de razões (o `score_history` já é uma série; um histórico de
  mudanças completo, se necessário, é fácil de adicionar depois sem
  quebrar nada).

## Testes

```
pytest tests/ -q
# 226 passed (213 já existentes + 13 novos em tests/test_setups.py)
```

Cobertura: transições de lifecycle (rejeição de status desconhecido,
rejeição de sair de estado terminal, progressão normal), upsert cria
quando não há setup aberto, upsert atualiza sem duplicar (e acumula
`score_history`), classificação de "activated", candidato depois de
status terminal cria setup NOVO (não reabre), rejeição de transição
inválida direto no repository, sweep_expired marca vencidos e ignora
os que ainda não venceram, validação de schema do candidato (direction/
status inválidos).
