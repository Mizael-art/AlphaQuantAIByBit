# Validação do Playbook — Nota de Cobertura e Próximos Passos

## Limitação encontrada

Este ambiente onde estou rodando **não tem acesso de rede às exchanges**
(Bybit/Binance) — só a domínios de pacotes (pypi, npm, github). Tentei
buscar histórico real e recebi:

```
Bybit retornou status 403: Host not in allowlist: api.bybit.com
```

Isso significa que **não consigo gerar números de performance reais**
das 7 estratégias do Playbook a partir daqui. O que fiz em vez disso,
que é trabalho real e útil:

## 1) Avaliação de cobertura: quais estratégias o DSL consegue expressar

| Estratégia | Status | Motivo |
|---|---|---|
| Trend Continuation | ✅ Expressável (aproximação) | "BOS na direção" não tem primitivo — uso alinhamento de EMA20/50/200 como proxy |
| EMA Pullback | ✅ Expressável | Recuo até EMA50 + reação, direto |
| Compression Breakout | ✅ Expressável (aproximação) | Rompimento de Bollinger — mas a precondição de "squeeze" (percentil de largura) não é input do rule engine, só existe no regime detector separado |
| Range High Rejection | ✅ Expressável (aproximação) | Usa limiares percentuais de proximidade à máxima, não a lógica real de wick/liquidez SMC |
| Range Low Rejection | ✅ Expressável (aproximação) | Espelho da anterior |
| Breakout + Retest | ⚠️ Parcial | Só o "Breakout" roda — "+Retest" exige estado entre candles que o rule engine atual não expõe |
| Liquidity Sweep Reversal | ❌ Não suportado | Depende de detecção de sweep de liquidez + Order Block/FVG — sem primitivo no DSL. Rodar isso exigiria estender `strategy_dsl/expression_engine.py` com uma função de sweep, o que não foi feito |

Essa avaliação sozinha já é útil: mostra que **2 das 7 estratégias do
Playbook não podem ser validadas com o motor de backtest como está
hoje** — antes mesmo de rodar um único trade.

## 2) Validação mecânica (sintética, sem rede)

Rodei as 6 estratégias expressáveis contra 4.500 candles sintéticos
(random walk, sem nenhum edge real embutido) só para confirmar que:
- os schemas são estruturalmente válidos;
- o motor executa sem erro do início ao fim;
- produzem trade log, performance e sample_quality coerentes.

**Isto NÃO valida se as estratégias são lucrativas** — dados sintéticos
não têm estrutura de mercado real. É só a garantia de que, quando você
rodar com dados reais, o schema não vai quebrar por um erro de código.

Resultado (`scripts/validate_playbook.py --synthetic`):

| Estratégia | Trades | Sample Quality |
|---|---|---|
| Trend Continuation | 65 | in_validation |
| EMA Pullback | 83 | in_validation |
| Compression Breakout | 144 | moderate_confidence |
| Range High Rejection | 17 | insufficient |
| Range Low Rejection | 4 | insufficient |
| Breakout (sem retest) | 0 | insufficient |

Todas rodaram sem erro mecânico.

## 3) O que falta — e como você roda com dados reais

`scripts/validate_playbook.py` está pronto no repositório. Onde houver
rede real para Bybit/Binance (seu computador, ou já em produção no
Render), basta:

```bash
python scripts/validate_playbook.py --symbol BTCUSDT --days 180
```

Isso vai:
1. Buscar histórico real via o mesmo `HistoryFetcher` da Fase 1.
2. Rodar as 6 estratégias expressáveis via `strategy_dsl` (idêntico ao
   que `POST /backtest/generic` faria).
3. Salvar o resultado completo em JSON, com performance, trade log,
   equity curve e sample_quality reais.

Depois disso, o próximo passo natural (fora do escopo desta rodada) é
o ciclo completo do Documento 2, seção 11: **out-of-sample → forward
test → live eligibility** — este script cobre só a primeira etapa
(backtest in-sample).

## Se quiser resolver a limitação de rede

O erro do provider já sugere a saída: "Add this host to your network
egress settings to allow access" — ou seja, se este ambiente permitir
configurar domínios de rede liberados, adicionar `api.bybit.com` (e/ou
`api.binance.com`) resolveria e eu poderia rodar os backtests reais
diretamente aqui.
