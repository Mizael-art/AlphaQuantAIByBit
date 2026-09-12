# CHANGELOG — Fase 6: Decision Eligibility + Mentor Integration

Implementa o Documento Master (seções 25, 67-82) do Plano de Evolução
— a decisão explícita de trade migra do GPT (só linguagem) para uma
camada determinística no backend, como já estava decidido desde o
Prompt Mestre (documento 4). 100% aditivo.

## Decision Eligibility Engine (`decision/`)

- `engine.py` — `evaluate_decision` (função pura): `LONG_NOW / SHORT_NOW
  / WAIT_TRIGGER / WAIT_PULLBACK / WATCH / REJECT`. Ordem de prioridade:
  1) Risk Engine sempre primeiro — `REJECTED` do risco nunca é
     contornado por score alto (Documento Master, seção 73).
  2) Score abaixo de 50 → REJECT direto (nunca WATCH por segurança —
     seção 77).
  3) Entrada não executável (chase risk) → WAIT_PULLBACK.
  4) Setup ainda em formação/observação → WAIT_TRIGGER.
  5) Tudo pronto + score ≥ 65 + entrada executável agora → LONG_NOW/
     SHORT_NOW explícito (seção 76: nunca vira "continue observando").
  6) Aguardando confirmação/retest/breakout específico → WAIT_TRIGGER.
  7) Nenhum critério bateu → WATCH (por ausência de critério, não por
     evasão).
  - Convicção (LOW/MEDIUM/HIGH) escala com o Overall Score — nunca é
    probabilidade de lucro (seção 75), reportado como tal em todo lugar.
- `mentor_block.py` — formata a decisão no bloco 🟢/🔴/🟡/🟠/⚪/❌
  (seções 27, 69): ativo, entrada, stop, TP, RR, risco%, alavancagem
  recomendada, holding esperado, motivo, risco principal, invalidação.
  Campos de execução ficam `None` explicitamente quando a decisão não
  é entrada imediata (nunca omitidos silenciosamente). **Limitação
  declarada**: `recommended_leverage` é heurística conservadora por
  bucket de volatilidade (LOW=5x/NORMAL=3x/HIGH=2x/EXTREME=1x), não um
  cálculo de margem/liquidação; `expected_holding` vem do estilo do
  Playbook, não de estatística real de duração de trades fechados.

## Endpoint novo (aditivo)

- `POST /decision/evaluate` — orquestra `scoring.engine` (Fase 3) +
  `risk.engine`/`risk.repository` (Fase 4) + `decision.engine` num
  único veredito. Retorna `score`, `risk_decision`, `eligibility` e
  `mentor_block` prontos — o GPT não deve recalcular nem inventar
  nenhum desses números, só comunicá-los (Documento Master, seção 26).

## Limite de operações do GPT Actions

Schema OpenAPI: **24 operações, ~35KB** (era 23/~32KB na Fase 5) — só
+1 endpoint nesta fase, porque a decisão orquestra módulos já
existentes em vez de expor peças novas. Ainda dentro do limite técnico
de 30. Decisão sobre dividir em mais de uma Action segue em aberto
(você optou por decidir depois na Fase 5) — Fase 7 deve adicionar mais
2-3 operações (scheduler/monitoring), o que deixaria o total por volta
de 26-27.

## Limitações conhecidas desta fase

- `POST /decision/evaluate` não busca dados de mercado sozinho — o
  chamador (GPT, tipicamente após um `/discovery/top-trades` ou
  `/snapshot`) precisa fornecer os inputs de score. Integração
  automática (discovery -> decision num só endpoint) não foi feita
  nesta fase para manter os dois desacoplados e testáveis
  separadamente; pode ser um endpoint de conveniência futuro se
  o uso mostrar que vale a pena.
- `setup_status="UNKNOWN"` (trade avaliado ad-hoc, sem setup
  persistido) é tratado como "pronto para decisão agora" — não passa
  pelo WAIT_TRIGGER que um setup em WATCH/FORMATION passaria. Isso é
  intencional (o usuário pode pedir uma decisão sobre um ativo que
  nunca foi registrado como setup), mas vale ter em mente.

## Testes

```
pytest tests/ -q
# 325 passed (309 já existentes + 16 novos)
```

`tests/test_decision_engine.py` (16 — todas as branches de decisão:
risco rejeitado sempre vence, score baixo rejeita direto, entrada
pronta gera LONG_NOW/SHORT_NOW, setup em espera gera WAIT_TRIGGER,
chase risk gera WAIT_PULLBACK, convicção escala com score, mentor_block
esconde campos de execução quando não é entrada imediata). Fluxo
completo (`/risk/account` -> `/decision/evaluate`) verificado
manualmente via `TestClient`, confirmando o bloco 🟢 ABRIR LONG AGORA
com todos os campos preenchidos corretamente.
