"""
strategy_dsl/errors.py
=========================

Erros estruturados do DSL de estratégia genérica.

Princípio (Documento 1, seções 3 e 4): quando uma regra ou indicador
não puder ser representado, o motor NUNCA aproxima ou ignora
silenciosamente -- ele recusa com um erro explicando exatamente o
motivo. Cada erro aqui carrega o suficiente pra virar o JSON
estruturado que a Action HTTP devolve ao GPT.
"""

from __future__ import annotations


class StrategyDslError(Exception):
    """Classe base -- todo erro do DSL carrega um `error_code` estável."""

    error_code: str = "strategy_dsl_error"

    def to_dict(self) -> dict:
        return {"error": self.error_code, "message": str(self)}


class UnsupportedIndicatorError(StrategyDslError):
    """Indicador referenciado no schema não está na tabela suportada."""

    error_code = "unsupported_indicator"

    def __init__(self, indicator: str) -> None:
        self.indicator = indicator
        super().__init__(f"Indicador '{indicator}' não está disponível neste motor.")

    def to_dict(self) -> dict:
        return {"error": self.error_code, "indicator": self.indicator, "message": str(self)}


class UnsupportedFunctionError(StrategyDslError):
    """Função referenciada numa regra de entrada/saída/filtro não é suportada."""

    error_code = "unsupported_function"

    def __init__(self, function_name: str) -> None:
        self.function_name = function_name
        super().__init__(f"Função '{function_name}' não está disponível neste motor.")

    def to_dict(self) -> dict:
        return {"error": self.error_code, "function": self.function_name, "message": str(self)}


class InvalidRuleError(StrategyDslError):
    """
    Regra não é uma expressão determinística válida -- inclui o caso de
    linguagem subjetiva ("estrutura bonita", "volume forte") que não é
    formalizável (Documento 1, seção 3).
    """

    error_code = "invalid_rule"

    def __init__(self, rule: str, reason: str) -> None:
        self.rule = rule
        self.reason = reason
        super().__init__(f"Regra '{rule}' inválida: {reason}")

    def to_dict(self) -> dict:
        return {"error": self.error_code, "rule": self.rule, "reason": self.reason, "message": str(self)}


class SchemaValidationError(StrategyDslError):
    """Schema da estratégia é estruturalmente inválido (campos ausentes/incoerentes)."""

    error_code = "invalid_schema"

    def __init__(self, details: str) -> None:
        self.details = details
        super().__init__(details)

    def to_dict(self) -> dict:
        return {"error": self.error_code, "details": self.details, "message": str(self)}


class UnsupportedStrategyError(StrategyDslError):
    """
    A estratégia, como um todo, não pode ser representada pelo DSL
    suportado (Documento 1, seção 24) -- usado quando a combinação de
    features pedidas excede o que o motor sabe simular hoje (ex.:
    multi-asset, walk-forward), mesmo que cada regra individual seja
    válida.
    """

    error_code = "unsupported_strategy"

    def __init__(self, reason: str, supported_capabilities: list[str]) -> None:
        self.reason = reason
        self.supported_capabilities = supported_capabilities
        super().__init__(reason)

    def to_dict(self) -> dict:
        return {
            "status": "unsupported_strategy",
            "reason": self.reason,
            "supported_capabilities": self.supported_capabilities,
        }
