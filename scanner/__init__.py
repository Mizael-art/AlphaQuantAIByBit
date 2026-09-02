"""
scanner
=======

Módulo de varredura de mercado (multi-símbolo). Diferente de
`app.run_analysis` / `snapshot.build_market_snapshot` (que analisam
UM símbolo por chamada, sob demanda), este módulo roda a análise em
uma LISTA de símbolos e devolve um resumo compacto, classificando
cada um em:

- "zona_de_entrada": preço já dentro de uma zona de suporte/resistência
  relevante, com score de qualidade acima do mínimo configurado.
- "observar": setup se formando (score razoável e/ou preço se
  aproximando de uma zona), mas ainda não está "gatilhado".
- "fora_de_zona": sem confluência suficiente no momento (omitido do
  retorno por padrão, para não inflar o payload).

Existe para suportar o modo "procurar oportunidades" do AlphaQuant X,
sem precisar que o usuário informe um símbolo por vez.
"""

from scanner.screener import scan_market

__all__ = ["scan_market"]
