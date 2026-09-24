"""Carry, roll-down e triagem de trades de valor relativo na curva DI.

Carry e roll-down (posição "dada" = recebe a taxa pré, comprada em PU)
----------------------------------------------------------------------
Para um prazo ``m`` e um horizonte ``h`` (dias úteis), supondo que a curva
fique **parada** (as taxas de cada prazo não mudam):

* **Carry** = ``f(h, m) − y(m)``: quanto a taxa a termo que começa em ``h``
  está acima da taxa spot de hoje. É o "prêmio" de manter a posição.
* **Roll-down** = ``y(m) − y(m − h)``: o contrato "envelhece" e passa a ser
  precificado por um ponto mais curto da curva.
* **Carry + roll** = ``f(h, m) − y(m − h)``: quanto a taxa pode subir até o
  horizonte antes de a posição dada começar a perder dinheiro (breakeven).

Todos os valores estão em bps de taxa. Em uma curva positivamente
inclinada, carry + roll é positivo para quem dá taxa.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import JANELA_PADRAO, VERTICES_PADRAO
from .curva import CurvaDI, dv01
from .movimentos import BUTTERFLIES_PADRAO, INCLINACOES_PADRAO, percentil_atual, spreads, zscore


def carry_roll(curva: CurvaDI, prazos: dict[str, int] | None = None, horizonte_du: int = 63,
               variacoes: pd.DataFrame | None = None, janela_vol: int = JANELA_PADRAO) -> pd.DataFrame:
    """Carry e roll-down por vértice para quem dá taxa, no horizonte informado.

    Args:
        curva: Curva do dia.
        prazos: Vértices {rótulo: dias úteis}. Padrão: ``VERTICES_PADRAO`` (sem o 3M).
        horizonte_du: Horizonte em dias úteis (63 ≈ 3 meses).
        variacoes: Variações diárias em bps (para normalizar pelo risco).
        janela_vol: Janela da volatilidade.

    Returns:
        DataFrame por vértice com taxa, forward, carry, roll-down, total (bps),
        DV01 por contrato (R$) e, se ``variacoes`` for dado, a razão
        carry+roll / volatilidade no horizonte.
    """
    prazos = prazos or {k: v for k, v in VERTICES_PADRAO.items() if v > horizonte_du}
    linhas = []
    for rotulo, m in prazos.items():
        if m <= horizonte_du or m > curva.du.max():
            continue
        y_m = curva.taxa(m)
        y_m_h = curva.taxa(m - horizonte_du)
        fwd = curva.forward(horizonte_du, m)
        linha = {
            "vertice": rotulo,
            "du": m,
            "taxa_%": y_m * 100,
            "forward_%": fwd * 100,
            "carry_bps": (fwd - y_m) * 1e4,
            "roll_down_bps": (y_m - y_m_h) * 1e4,
            "carry_roll_bps": (fwd - y_m_h) * 1e4,
            "dv01_R$": float(dv01(y_m, m)),
        }
        if variacoes is not None and rotulo in variacoes:
            vol_diaria = variacoes[rotulo].dropna().iloc[-janela_vol:].std()
            vol_horizonte = vol_diaria * np.sqrt(horizonte_du)
            linha["vol_horizonte_bps"] = vol_horizonte
            linha["carry_roll/vol"] = linha["carry_roll_bps"] / vol_horizonte
        linhas.append(linha)
    return pd.DataFrame(linhas).set_index("vertice")


def triagem_valor_relativo(taxas: pd.DataFrame, curva: CurvaDI, janela: int = JANELA_PADRAO,
                           horizonte_du: int = 63, limiar_z: float = 1.0) -> pd.DataFrame:
    """Triagem de inclinações e butterflies: quão "esticado" está cada spread.

    Para cada spread calcula o nível atual, média e desvio na janela, z-score
    e percentil, e sugere a direção de **reversão à média** quando
    ``|z| >= limiar_z``, junto com o carry + roll dessa posição e a razão de
    contratos que neutraliza o DV01.

    Isto é uma ferramenta de triagem, não uma recomendação: um spread pode
    ficar esticado por muito tempo quando há motivo macro para isso.
    """
    tabela_spreads = spreads(taxas)
    z = zscore(tabela_spreads, janela)
    cr = carry_roll(curva, VERTICES_PADRAO, horizonte_du)["carry_roll_bps"]

    def cr_de(v):
        return cr.get(v, np.nan)

    linhas = []
    for nome in tabela_spreads.columns:
        serie = tabela_spreads[nome].dropna()
        if serie.empty:
            continue
        janela_dados = serie.iloc[-janela:]
        atual, zz = serie.iloc[-1], z[nome].iloc[-1]
        linha = {
            "spread": nome,
            "tipo": "inclinação" if nome in INCLINACOES_PADRAO else "butterfly",
            "atual_bps": atual,
            "media_bps": janela_dados.mean(),
            "desvio_bps": janela_dados.std(),
            "z_score": zz,
            "percentil": percentil_atual(serie, janela),
        }
        if nome in INCLINACOES_PADRAO:
            curto, longo = INCLINACOES_PADRAO[nome]
            carry_steep = cr_de(curto) - cr_de(longo)  # dá o curto, toma o longo
            razao = float(dv01(curva.taxa(VERTICES_PADRAO[longo]), VERTICES_PADRAO[longo])
                          / dv01(curva.taxa(VERTICES_PADRAO[curto]), VERTICES_PADRAO[curto]))
            if zz >= limiar_z:
                linha["sugestao"] = f"flattener: dar {longo} / tomar {curto}"
                linha["carry_roll_bps"] = -carry_steep
            elif zz <= -limiar_z:
                linha["sugestao"] = f"steepener: tomar {longo} / dar {curto}"
                linha["carry_roll_bps"] = carry_steep
            else:
                linha["sugestao"] = "neutro"
                linha["carry_roll_bps"] = np.nan
            linha["contratos_curto_por_longo"] = razao
        else:
            a, b, c = BUTTERFLIES_PADRAO[nome]
            carry_barriga = 2 * cr_de(b) - cr_de(a) - cr_de(c)  # dá a barriga, toma as asas
            if zz >= limiar_z:
                linha["sugestao"] = f"dar barriga ({b}) / tomar asas ({a}, {c})"
                linha["carry_roll_bps"] = carry_barriga
            elif zz <= -limiar_z:
                linha["sugestao"] = f"tomar barriga ({b}) / dar asas ({a}, {c})"
                linha["carry_roll_bps"] = -carry_barriga
            else:
                linha["sugestao"] = "neutro"
                linha["carry_roll_bps"] = np.nan
            linha["contratos_curto_por_longo"] = np.nan
        linhas.append(linha)
    resultado = pd.DataFrame(linhas).set_index("spread")
    return resultado.sort_values("z_score", key=np.abs, ascending=False)
