# CHANGELOG — Fase 8: Optimization + Robustness + Portfolio Intelligence

Última fase do Plano de Evolução. Implementa o Documento 1 (seções
15-17), o Documento 2 (seção 32) e o Documento Master (seções 31-32,
38). 100% aditivo.

## `optimization/`

- `monte_carlo.py` — `run_monte_carlo`: bootstrap por reamostragem com
  reposição sobre os PnL % de trades já simulados. Distribuição
  (percentis 5/25/50/75/95) de capital final e drawdown máximo, e
  probabilidade de terminar no prejuízo. **Limitação declarada**:
  assume trades i.i.d. — não preserva sequência cronológica real nem
  correlação serial entre perdas; é ferramenta de robustez, não
  previsão.
- `portfolio.py` — `select_best_combination`: seleção gulosa (greedy)
  por Overall Score decrescente, respeitando teto de open risk, número
  máximo de posições e evitando duplicar exposição correlacionada
  (consome a saída de `discovery.correlation`, não reimplementa).
- `walk_forward.py` — `run_walk_forward`: roda a MESMA estratégia
  (schema idêntico) em várias janelas de tempo independentes via
  `strategy_dsl.executor` (Fase 1), agrega estabilidade
  (média/mediana/desvio padrão de expectancy_r, profit_factor,
  win_rate entre janelas). Desvio alto relativo à média = resultado
  dependente do período, não estratégia robusta.
- `parameter_sweep.py` — `run_parameter_sweep`: testa uma grade de
  combinações de parâmetros (caminho dotted -> lista de valores) sobre
  o mesmo período. Nunca retorna "melhor estratégia" — sempre "melhor
  resultado no espaço pesquisado", com aviso de overfitting SEMPRE
  presente no payload (Documento 1, seção 17, é explícito sobre isso).
  Teto de segurança (`max_combinations`, default 60) evita sweep
  acidental de milhares de combinações numa chamada só.

## Endpoints novos (aditivos)

- `POST /optimization/walk-forward`
- `POST /optimization/parameter-sweep`
- `POST /optimization/monte-carlo`
- `POST /optimization/portfolio-selection`

## Limite de operações do GPT Actions — atingido o teto prático

Schema OpenAPI final: **29 operações, ~42KB** — a 1 operação do limite
técnico de 30. Este projeto terminou exatamente no limite que vínhamos
acompanhando desde a Fase 4. **Não é possível adicionar mais nenhum
endpoint a esta Action sem dividir em mais de uma** — se qualquer
trabalho futuro exigir um endpoint novo, a divisão em múltiplas Actions
(decisão que você optou por adiar) deixa de ser opcional.

## Limitações conhecidas desta fase (e do projeto como um todo nesta rodada)

- `walk_forward`/`parameter_sweep` não persistem resultados — cada
  chamada roda do zero. Guardar histórico de backtests/sweeps
  (`backtests` salvos, mencionado no Documento Master seção 46) não foi
  implementado — nenhuma fase anterior chegou a precisar disso na
  prática ainda.
- `select_best_combination` usa um `risk_pct_per_trade` FIXO para todas
  as oportunidades (não integra com o position sizing individual do
  Risk Engine, que pode aprovar tamanhos diferentes por trade). Unir os
  dois de forma precisa ficaria para uma iteração futura.
- Nenhum destes 4 endpoints foi testado com dados de mercado reais
  (todos os smoke tests usam providers fake) — o comportamento com
  histórico real de exchanges ainda precisa de validação manual antes
  do primeiro uso em produção.

## Testes

```
pytest tests/ -q
# 357 passed (343 já existentes + 14 novos)
```

`tests/test_optimization.py` (11 — Monte Carlo: rejeita input vazio,
todos os trades positivos nunca perde, todos negativos sempre perde,
percentis ordenados, reprodutível com seed; Portfolio: prioriza score,
respeita orçamento de risco, respeita limite de posições, pula
correlacionados) + `tests/test_optimization_integration.py` (3 — smoke
test de walk-forward e parameter sweep com provider fake, incluindo
rejeição de grid acima do teto de combinações). Endpoints puros
(monte-carlo, portfolio-selection) verificados ponta a ponta via
`TestClient`.

---

## Resumo do projeto completo (Fases 1-8)

| Fase | Entrega | Testes ao final |
|---|---|---|
| 1 | Backtest DSL genérico | 213 |
| 2 | Persistência + Setup Lifecycle + Setup Memory | 226 |
| 3 | Multi-score + Discovery/Ranking + Regime-first | 266 |
| 4 | Risk Engine central | 292 |
| 5 | Learning Engine + External Signals | 309 |
| 6 | Decision Eligibility + Mentor Integration | 325 |
| 7 | Monitoring + Scheduler + Conditional Plans | 343 |
| 8 | Optimization + Robustness + Portfolio Intelligence | 357 |

29 endpoints novos no total, 0 regressões em nenhuma fase, arquitetura
final: 1 serviço web (Render) + 1 Postgres gerenciado + 1 Cron Job,
conforme decidido no Plano de Evolução original — sem necessidade de
múltiplos repositórios/serviços além do previsto.
