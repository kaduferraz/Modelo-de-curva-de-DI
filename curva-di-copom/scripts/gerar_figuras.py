"""Gera as figuras do README (docs/img/*.png) a partir dos dados locais.

Uso:
    python scripts/gerar_figuras.py            # último pregão disponível
    python scripts/gerar_figuras.py --data 2026-09-23

Requer ``kaleido`` (já está no requirements.txt) e um Google Chrome instalado.
Se não tiver o Chrome, rode uma vez: ``plotly_get_chrome``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from curva_di import copom, graficos, movimentos, valor_relativo  # noqa: E402
from curva_di.analise import montar_analise  # noqa: E402
from curva_di.config import PASTA_FIGURAS  # noqa: E402
from curva_di.curva import CurvaDI  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", help="Data de referência (AAAA-MM-DD). Padrão: último pregão.")
    args = parser.parse_args()

    a = montar_analise(args.data)
    um_mes_antes = CurvaDI.do_historico(a.historico, a.data - pd.Timedelta(days=30))
    historico_implicito = copom.historico_selic_implicita(a.historico[a.historico["data"] <= a.data],
                                                          a.reunioes, a.selic_cdi)
    surpresas = copom.surpresas_copom(historico_implicito, a.reunioes, a.selic_cdi)

    figuras = {
        "curva.png": graficos.grafico_curva(a.curva, um_mes_antes, anos_max=10),
        "pca.png": graficos.grafico_pca(movimentos.pca_curva(a.variacoes)),
        "spread_1a_5a.png": graficos.grafico_spread(movimentos.spreads(a.taxas)["1A–5A"], "1A–5A",
                                                    desde=a.data - pd.DateOffset(years=3)),
        "carry.png": graficos.grafico_carry(valor_relativo.carry_roll(a.curva)),
    }
    if a.caminho is not None:
        figuras["copom.png"] = graficos.grafico_copom_variacoes(a.caminho)
        if a.focus_do_dia is not None:
            figuras["copom_vs_focus.png"] = graficos.grafico_copom_caminho(a.caminho, a.focus_do_dia)
    if not surpresas.empty:
        figuras["surpresas.png"] = graficos.grafico_surpresas(surpresas)

    salvas = 0
    for nome, fig in figuras.items():
        if graficos.salvar_png(fig, PASTA_FIGURAS / nome):
            salvas += 1
            print(f"ok  docs/img/{nome}")
    if salvas < len(figuras):
        print("\nAlgumas figuras não foram salvas. Se o erro mencionar o Chrome, rode `plotly_get_chrome`.")
    print(f"\nFiguras de {a.data:%d/%m/%Y} salvas em {PASTA_FIGURAS}.")


if __name__ == "__main__":
    main()
