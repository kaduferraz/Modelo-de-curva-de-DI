"""curva_di — Curva de juros DI, Selic implícita por reunião do Copom e análise de movimentos.

Módulos:
    calendario      dias úteis (ANBIMA/B3) e vencimentos do DI1
    dados           coleta (B3, BCB) e cache local em data/
    curva           PU, taxas, flat forward, forwards, DV01, vértices de prazo constante
    copom           calendário do Copom e Selic implícita por reunião
    movimentos      variações, PCA, regimes (bull/bear, steepening/flattening), Copom
    valor_relativo  carry, roll-down e triagem de inclinações e butterflies
    comentario      comentário de mercado automático
    graficos        gráficos Plotly
"""

from .copom import carregar_reunioes_copom, selic_implicita
from .curva import CurvaDI, vertices_constantes
from .dados import carregar_focus_selic, carregar_historico_di1, carregar_selic_cdi

__version__ = "1.0.0"

__all__ = [
    "CurvaDI",
    "carregar_focus_selic",
    "carregar_historico_di1",
    "carregar_reunioes_copom",
    "carregar_selic_cdi",
    "selic_implicita",
    "vertices_constantes",
]
