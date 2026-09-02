"""
validation
==========

Data Quality Layer: valida candles retornados por qualquer provider
antes que sejam consumidos por indicators/structure/smc/analysis.
"""

from validation.data_quality import DataQualityError, validate_candles

__all__ = ["DataQualityError", "validate_candles"]
