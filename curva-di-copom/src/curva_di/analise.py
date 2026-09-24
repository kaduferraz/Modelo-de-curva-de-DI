"""Monta, em uma única chamada, todas as peças usadas pelo dashboard e pelas figuras."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import copom, dados, movimentos
from .curva import CurvaDI, vertices_constantes


def focus_na_data(focus: pd.DataFrame | None, data) -> pd.DataFrame | None:
    """Última pesquisa Focus publicada até ``data`` (uma linha por reunião)."""
    if focus is None or focus.empty:
        return None
    anteriores = focus[focus["data"] <= pd.Timestamp(data)]
    if anteriores.empty:
        return None
    ultima = anteriores["data"].max()
    return anteriores[anteriores["data"] == ultima].reset_index(drop=True)


@dataclass
class Analise:
    """Tudo o que é calculado para uma data de referência."""

    data: pd.Timestamp
    historico: pd.DataFrame = field(repr=False)
    reunioes: pd.DataFrame = field(repr=False)
    taxas: pd.DataFrame = field(repr=False)
    variacoes: pd.DataFrame = field(repr=False)
    curva: CurvaDI = field(repr=False)
    curva_anterior: CurvaDI = field(repr=False)
    caminho: pd.DataFrame | None = field(repr=False)
    caminho_anterior: pd.DataFrame | None = field(repr=False, default=None)
    focus: pd.DataFrame | None = field(repr=False, default=None)
    focus_do_dia: pd.DataFrame | None = field(repr=False, default=None)
    selic_cdi: pd.DataFrame | None = field(repr=False, default=None)


def montar_analise(data=None, historico: pd.DataFrame | None = None, atualizar: bool = False) -> Analise:
    """Carrega os dados locais e calcula curva, Copom implícito e movimentos.

    Args:
        data: Data de referência (padrão: último pregão disponível).
        historico: Histórico do DI1 já carregado (evita reler o arquivo).
        atualizar: Se True, atualiza os dados na internet antes.
    """
    if historico is None:
        historico = dados.carregar_historico_di1(atualizar=atualizar)
    reunioes = copom.carregar_reunioes_copom(atualizar=atualizar)
    selic_cdi = dados.carregar_selic_cdi(atualizar=atualizar)
    focus = dados.carregar_focus_selic(atualizar=atualizar)

    curva = CurvaDI.do_historico(historico, data)
    datas = historico["data"].drop_duplicates().sort_values()
    anteriores = datas[datas < curva.data_referencia]
    curva_anterior = CurvaDI.do_historico(historico, anteriores.iloc[-1])

    taxas = vertices_constantes(historico.loc[historico["data"] <= curva.data_referencia])
    variacoes = movimentos.variacoes_bps(taxas)

    # CDI vigente em cada data: BCB (se houver) ou o último valor identificado
    # na própria curva desde a reunião anterior (ver copom.historico_selic_implicita)
    recente = copom.historico_selic_implicita(
        historico[historico["data"] <= curva.data_referencia], reunioes, selic_cdi,
        inicio=curva.data_referencia - pd.Timedelta(days=120), max_reunioes=1)

    def _cdi(d):
        if selic_cdi is not None and "cdi" in selic_cdi and d in selic_cdi.index:
            return float(selic_cdi.loc[d, "cdi"])
        if not recente.empty:
            linhas = recente[recente["data"] == d]
            if not linhas.empty:
                return float(linhas["cdi_atual"].iloc[0])
        return None

    caminho, caminho_anterior = None, None
    # O calendário precisa cobrir a data (a reunião anterior tem de ser conhecida)
    if reunioes["data_decisao"].min() < curva_anterior.data_referencia:
        try:
            caminho = copom.selic_implicita(curva, reunioes, cdi_atual=_cdi(curva.data_referencia))
            caminho_anterior = copom.selic_implicita(curva_anterior, reunioes,
                                                     cdi_atual=_cdi(curva_anterior.data_referencia))
        except ValueError:
            pass

    return Analise(
        data=curva.data_referencia, historico=historico, reunioes=reunioes, taxas=taxas,
        variacoes=variacoes, curva=curva, curva_anterior=curva_anterior, caminho=caminho,
        caminho_anterior=caminho_anterior, focus=focus,
        focus_do_dia=focus_na_data(focus, curva.data_referencia), selic_cdi=selic_cdi,
    )
