"""
symbols
=======

Normalização central de símbolos: mapeia qualquer variação de símbolo
recebida (usuário, webhook, scan) para uma identidade canônica
(`canonical_symbol` + `asset_class`), usada por todo o resto do
sistema para decidir providers e rotear dados.
"""

from symbols.mapper import AssetClass, CanonicalSymbol, SymbolMapper, SymbolNotRecognizedError

__all__ = ["AssetClass", "CanonicalSymbol", "SymbolMapper", "SymbolNotRecognizedError"]
