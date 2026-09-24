"""Comentário de mercado automático, no estilo de um resumo diário de mesa de juros."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .copom import descrever_movimento, probabilidades_movimento
from .movimentos import LEITURA_REGIME, classificar_movimento, percentil_atual, spreads, zscore


def _bps(x: float) -> str:
    return f"{x:+.1f} bps".replace(".", ",")


def _pct(x: float, casas: int = 2) -> str:
    return f"{x * 100:.{casas}f}%".replace(".", ",")


def comentario_do_dia(taxas: pd.DataFrame, data=None, caminho_hoje: pd.DataFrame | None = None,
                      caminho_anterior: pd.DataFrame | None = None, curto: str = "1A",
                      longo: str = "5A") -> str:
    """Gera um parágrafo (markdown) descrevendo o movimento da curva no dia.

    Args:
        taxas: Taxas de prazo constante (``curva.vertices_constantes``).
        data: Data do comentário (padrão: última disponível).
        caminho_hoje / caminho_anterior: Saídas de ``copom.selic_implicita``
            para o dia e para o pregão anterior (opcionais).
    """
    datas = taxas.index[taxas.index <= pd.Timestamp(data)] if data is not None else taxas.index
    d = datas[-1]
    anterior = taxas.index[taxas.index.get_loc(d) - 1]
    delta = (taxas.loc[d] - taxas.loc[anterior]) * 1e4

    regime = classificar_movimento(delta[curto], delta[longo])
    tabela_spreads = spreads(taxas.loc[:d])
    nome_incl = f"{curto}–{longo}"
    incl = tabela_spreads[nome_incl] if nome_incl in tabela_spreads else (taxas[longo] - taxas[curto]).loc[:d] * 1e4
    z_incl = zscore(incl).iloc[-1]
    pct_incl = percentil_atual(incl)

    z_txt = f"{z_incl:+.1f}".replace(".", ",")
    partes = [
        f"**{d:%d/%m/%Y} — {regime}.** "
        f"O {curto} variou {_bps(delta[curto])} (para {_pct(taxas.loc[d, curto])}) e o {longo} "
        f"{_bps(delta[longo])} (para {_pct(taxas.loc[d, longo])}); "
        f"a inclinação {nome_incl} mudou {_bps(delta[longo] - delta[curto])} e está em "
        f"{incl.iloc[-1]:.0f} bps (z-score {z_txt} em 12 meses, percentil {pct_incl:.0f})."
    ]
    if regime in LEITURA_REGIME:
        partes.append(f"Leitura: {LEITURA_REGIME[regime]}.")

    if "10A" in delta and not np.isnan(delta["10A"]):
        partes.append(f"Na ponta longa, o 10A andou {_bps(delta['10A'])}.")

    if caminho_hoje is not None and not caminho_hoje.empty:
        prox = caminho_hoje.iloc[0]
        probs = probabilidades_movimento(prox["variacao_bps"])
        principal = max(probs, key=probs.get)
        texto_copom = (
            f"Para a próxima reunião do Copom ({prox['data_decisao']:%d/%m}), a curva precifica "
            f"{_bps(prox['variacao_bps'])} ({probs[principal] * 100:.0f}% de chance de "
            f"{descrever_movimento(principal)})"
        )
        if caminho_anterior is not None and not caminho_anterior.empty:
            mesma = caminho_anterior[caminho_anterior["reuniao"] == prox["reuniao"]]
            if not mesma.empty:
                texto_copom += f", ante {_bps(mesma['variacao_bps'].iloc[0])} no pregão anterior"
        ate_dez = caminho_hoje[caminho_hoje["data_decisao"].dt.year == prox["data_decisao"].year]
        if len(ate_dez):
            ultima = ate_dez.iloc[-1]
            texto_copom += (f". Até a reunião de {ultima['data_decisao']:%d/%m/%Y}, o movimento "
                            f"acumulado precificado é {_bps(ultima['acumulado_bps'])}, levando a "
                            f"Selic implícita a {_pct(ultima['selic_implicita'])}")
        partes.append(texto_copom + ".")
    return " ".join(partes)
