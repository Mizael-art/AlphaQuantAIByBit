"""
strategy_dsl/expression_engine.py
====================================

Avaliador de regras determinísticas (Documento 1, seções 3 e 4).

Cada regra do schema (`entry.long`, `entry.short`, `filters`, e os
campos `value` de stop/take-profit quando expressos como fórmula) é
uma STRING como:

    "SMA20 crosses above SMA50"
    "RSI14 < 30"
    "close > highest(high, 20)"
    "volume > SMA(volume, 20) * 1.5"

Isso NÃO é avaliado com `eval()` sobre código Python arbitrário --
seria inseguro (o schema pode vir de qualquer chamador da Action) e
também não seria auditável. Em vez disso:

1. A regra é normalizada (sinônimos em inglês/português, "crosses
   above" -> `cross_above(...)`) para uma sintaxe Python-like restrita.
2. `ast.parse(..., mode="eval")` gera a árvore sintática.
3. Um `NodeVisitor` restrito rejeita qualquer nó fora da whitelist
   (nada de import, atributo, chamada de método, comprehension etc.)
   -- rejeita com `InvalidRuleError`, nunca tenta "consertar".
4. A árvore validada é avaliada de forma VETORIZADA sobre um contexto
   de `pandas.Series` já alinhadas ao índice do DataFrame (uma série
   por indicador declarado + OHLCV base) -- o resultado é uma Series
   booleana/numérica para a série inteira, não recalculada candle a
   candle em Python puro (mais rápido, e a garantia de não-lookahead
   vem de cada indicador/função só usar `.rolling()`/`.shift(positivo)`,
   nunca `.shift(negativo)`).

Funções suportadas (Documento 1, seção 4, "Estrutura" + "Funções"):
    cross_above(a, b) / crosses_above  -- alias: crossover
    cross_below(a, b) / crosses_below  -- alias: crossunder
    highest(series, n)
    lowest(series, n)
    sma(series, n) / ema(series, n)    -- funções inline, além dos indicadores declarados
    abs(x)
    min(x, y) / max(x, y)
"""

from __future__ import annotations

import ast
import re

import pandas as pd

from strategy_dsl.errors import InvalidRuleError, UnsupportedFunctionError

_ALLOWED_FUNCTIONS = {
    "cross_above", "cross_below", "crossover", "crossunder",
    "highest", "lowest", "sma", "ema", "abs", "min", "max",
}

# Normalização de linguagem natural restrita -> sintaxe da expressão.
# Só cobre os padrões literais do Documento 1 (seção 3) -- qualquer
# coisa fora disso precisa já vir como expressão, e se não for
# parseável, falha como `InvalidRuleError` (nunca tenta adivinhar).
_NORMALIZATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bcrosses\s+above\b", re.IGNORECASE), "CROSSES_ABOVE"),
    (re.compile(r"\bcrosses\s+below\b", re.IGNORECASE), "CROSSES_BELOW"),
    (re.compile(r"\bcruzou\s+acima\s+d[ae]\b", re.IGNORECASE), "CROSSES_ABOVE"),
    (re.compile(r"\bcruzou\s+abaixo\s+d[ae]\b", re.IGNORECASE), "CROSSES_BELOW"),
    (re.compile(r"\band\b", re.IGNORECASE), "and"),
    (re.compile(r"\bor\b", re.IGNORECASE), "or"),
    (re.compile(r"\bnot\b", re.IGNORECASE), "not"),
]

_CROSS_ABOVE_PATTERN = re.compile(r"^(?P<a>.+?)\s+CROSSES_ABOVE\s+(?P<b>.+)$")
_CROSS_BELOW_PATTERN = re.compile(r"^(?P<a>.+?)\s+CROSSES_BELOW\s+(?P<b>.+)$")


def _normalize(rule: str) -> str:
    text = rule.strip()
    for pattern, replacement in _NORMALIZATIONS:
        text = pattern.sub(replacement, text)

    cross_above_match = _CROSS_ABOVE_PATTERN.match(text)
    if cross_above_match:
        return f"cross_above({cross_above_match.group('a').strip()}, {cross_above_match.group('b').strip()})"

    cross_below_match = _CROSS_BELOW_PATTERN.match(text)
    if cross_below_match:
        return f"cross_below({cross_below_match.group('a').strip()}, {cross_below_match.group('b').strip()})"

    return text


class _SafeNodeVisitor(ast.NodeVisitor):
    """Percorre a AST e recusa qualquer nó fora da whitelist determinística."""

    _ALLOWED_NODES = (
        ast.Expression, ast.BoolOp, ast.And, ast.Or,
        ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
        ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
        ast.Compare, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
        ast.Call, ast.Name, ast.Load, ast.Constant,
    )

    def __init__(self, raw_rule: str) -> None:
        self.raw_rule = raw_rule

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, self._ALLOWED_NODES):
            raise InvalidRuleError(
                self.raw_rule,
                f"construção '{type(node).__name__}' não é uma condição determinística "
                "suportada (regras subjetivas ou código arbitrário não são aceitos).",
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise InvalidRuleError(self.raw_rule, "chamada de função inválida.")
            if node.func.id not in _ALLOWED_FUNCTIONS:
                raise UnsupportedFunctionError(node.func.id)
        super().generic_visit(node)


def validate_rule_syntax(rule: str) -> ast.Expression:
    """
    Valida que `rule` é uma expressão determinística aceitável.

    Raises:
        InvalidRuleError: sintaxe não parseável ou nó fora da whitelist
            (cobre o caso de linguagem subjetiva, Documento 1 seção 3).
        UnsupportedFunctionError: função referenciada não suportada.
    """
    normalized = _normalize(rule)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise InvalidRuleError(
            rule,
            "não é uma expressão determinística formalizável (verifique se não é "
            f"linguagem subjetiva). Erro de sintaxe: {exc.msg}",
        ) from exc

    _SafeNodeVisitor(rule).visit(tree)
    return tree


class _Evaluator(ast.NodeVisitor):
    """Avalia a AST validada sobre um contexto de `pandas.Series` alinhadas."""

    def __init__(self, context: dict[str, pd.Series | float], raw_rule: str) -> None:
        self.context = context
        self.raw_rule = raw_rule

    def visit(self, node: ast.AST):  # noqa: ANN001 - retorno é Series | float | bool-Series
        return super().visit(node)

    def visit_Expression(self, node: ast.Expression):
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant):
        return node.value

    def visit_Name(self, node: ast.Name):
        if node.id not in self.context:
            raise InvalidRuleError(self.raw_rule, f"variável/indicador '{node.id}' não foi declarado no schema.")
        return self.context[node.id]

    def visit_BinOp(self, node: ast.BinOp):
        left, right = self.visit(node.left), self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise InvalidRuleError(self.raw_rule, f"operador '{type(node.op).__name__}' não suportado.")

    def visit_UnaryOp(self, node: ast.UnaryOp):
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.Not):
            return ~operand if isinstance(operand, pd.Series) else (not operand)
        raise InvalidRuleError(self.raw_rule, f"operador unário '{type(node.op).__name__}' não suportado.")

    def visit_BoolOp(self, node: ast.BoolOp):
        values = [self.visit(v) for v in node.values]
        combine = (lambda a, b: a & b) if isinstance(node.op, ast.And) else (lambda a, b: a | b)
        result = values[0]
        for v in values[1:]:
            result = combine(result, v)
        return result

    def visit_Compare(self, node: ast.Compare):
        left = self.visit(node.left)
        result = None
        for op, comparator_node in zip(node.ops, node.comparators):
            right = self.visit(comparator_node)
            if isinstance(op, ast.Lt):
                cmp = left < right
            elif isinstance(op, ast.LtE):
                cmp = left <= right
            elif isinstance(op, ast.Gt):
                cmp = left > right
            elif isinstance(op, ast.GtE):
                cmp = left >= right
            elif isinstance(op, ast.Eq):
                cmp = left == right
            elif isinstance(op, ast.NotEq):
                cmp = left != right
            else:
                raise InvalidRuleError(self.raw_rule, f"comparador '{type(op).__name__}' não suportado.")
            result = cmp if result is None else (result & cmp)
            left = right
        return result

    def visit_Call(self, node: ast.Call):
        func_name = node.func.id
        args = [self.visit(a) for a in node.args]

        if func_name in ("cross_above", "crossover"):
            a, b = args
            return (a > b) & (a.shift(1) <= b.shift(1))
        if func_name in ("cross_below", "crossunder"):
            a, b = args
            return (a < b) & (a.shift(1) >= b.shift(1))
        if func_name == "highest":
            series, n = args
            return series.rolling(int(n)).max()
        if func_name == "lowest":
            series, n = args
            return series.rolling(int(n)).min()
        if func_name == "sma":
            series, n = args
            return series.rolling(int(n)).mean()
        if func_name == "ema":
            series, n = args
            return series.ewm(span=int(n), adjust=False).mean()
        if func_name == "abs":
            (x,) = args
            return x.abs() if isinstance(x, pd.Series) else abs(x)
        if func_name == "min":
            a, b = args
            return a.combine(b, min) if isinstance(a, pd.Series) else min(a, b)
        if func_name == "max":
            a, b = args
            return a.combine(b, max) if isinstance(a, pd.Series) else max(a, b)

        raise UnsupportedFunctionError(func_name)


def evaluate_rule(rule: str, context: dict[str, pd.Series | float]) -> pd.Series:
    """
    Valida e avalia `rule` sobre `context` (nomes de indicadores/OHLCV
    -> `pandas.Series` já alinhadas), retornando uma `Series` booleana
    (ou numérica, se a regra não for uma comparação) para a série
    histórica inteira -- sem lookahead, porque todo indicador do
    contexto já foi calculado apenas com `.rolling()`/EMA causais.
    """
    tree = validate_rule_syntax(rule)
    return _Evaluator(context, rule).visit(tree)
