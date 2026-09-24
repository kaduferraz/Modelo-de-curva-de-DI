"""Calendário do Copom e Selic implícita por reunião, extraída da curva DI.

Ideia central
-------------
O CDI só muda quando o Copom muda a Selic. Entre duas reuniões, portanto, o
CDI é (praticamente) constante. Cada contrato DI1 embute a média do CDI de
hoje até o seu vencimento, então dá para "desmontar" a curva curta em uma
taxa para cada intervalo entre reuniões::

    ln F(T) = Σ_i  n_i(T) / 252 · ln(1 + r_i)

onde ``F(T)`` é o fator do contrato com vencimento ``T``, ``r_i`` é o CDI
vigente depois da reunião ``i`` (``r_0`` = CDI atual) e ``n_i(T)`` é o número
de dias úteis do intervalo ``i`` que caem antes de ``T``.

Resolvendo de forma sequencial (bootstrap) — usando, para cada intervalo, o
contrato que vence mais tarde dentro dele — obtemos o CDI implícito depois
de cada reunião e, somando o spread Selic–CDI, a **Selic implícita**. A
diferença entre reuniões consecutivas é o movimento que o mercado está
precificando para cada decisão.

Quando o único contrato disponível em um intervalo vence poucos dias depois
da reunião, um erro minúsculo no seu ajuste vira um salto enorme na taxa da
reunião. Nesses casos a reunião é estimada junto com a seguinte (ver
``MAX_AMPLIFICACAO``).

Validação (``surpresas_copom``): nas reuniões de 2024 a set/2026, a mudança
do CDI lida na curva no pregão seguinte coincide com a decisão anunciada
(desvio de até ~1,5 bp), usando apenas dados da B3.
"""

from __future__ import annotations

import re
import warnings

import numpy as np
import pandas as pd

from . import calendario as cal
from .config import (
    ARQUIVO_COPOM,
    MIN_CONTRATOS_ABERTOS_COPOM,
    PASTA_DADOS,
    SPREAD_SELIC_CDI,
    URL_BCB_COPOM_AGENDA,
    URL_BCB_COPOM_ATAS,
)
from .curva import CurvaDI

# Datas publicadas pelo BCB (início e decisão de cada reunião). Usadas quando o
# site do BCB não está acessível. Fontes: comunicados de calendário do Copom
# de 2024, 2025, 2026 e 2027 (o de 2027 foi divulgado em 23/06/2026).
REUNIOES_COPOM_FALLBACK: list[tuple[str, str]] = [
    # 2024
    ("2024-01-30", "2024-01-31"), ("2024-03-19", "2024-03-20"), ("2024-05-07", "2024-05-08"),
    ("2024-06-18", "2024-06-19"), ("2024-07-30", "2024-07-31"), ("2024-09-17", "2024-09-18"),
    ("2024-11-05", "2024-11-06"), ("2024-12-10", "2024-12-11"),
    # 2025
    ("2025-01-28", "2025-01-29"), ("2025-03-18", "2025-03-19"), ("2025-05-06", "2025-05-07"),
    ("2025-06-17", "2025-06-18"), ("2025-07-29", "2025-07-30"), ("2025-09-16", "2025-09-17"),
    ("2025-11-04", "2025-11-05"), ("2025-12-09", "2025-12-10"),
    # 2026
    ("2026-01-27", "2026-01-28"), ("2026-03-17", "2026-03-18"), ("2026-04-28", "2026-04-29"),
    ("2026-06-16", "2026-06-17"), ("2026-08-04", "2026-08-05"), ("2026-09-15", "2026-09-16"),
    ("2026-11-03", "2026-11-04"), ("2026-12-08", "2026-12-09"),
    # 2027
    ("2027-01-26", "2027-01-27"), ("2027-03-16", "2027-03-17"), ("2027-04-27", "2027-04-28"),
    ("2027-06-15", "2027-06-16"), ("2027-08-03", "2027-08-04"), ("2027-09-21", "2027-09-22"),
    ("2027-10-26", "2027-10-27"), ("2027-12-07", "2027-12-08"),
]


# ---------------------------------------------------------------------------
# Calendário
# ---------------------------------------------------------------------------
def _formatar_reunioes(decisoes: pd.Series, inicios: pd.Series | None, fonte: str | pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"data_decisao": pd.to_datetime(decisoes).dt.normalize()})
    df["data_inicio"] = pd.to_datetime(inicios).dt.normalize() if inicios is not None else pd.NaT
    df["fonte"] = fonte
    df = df.drop_duplicates("data_decisao").sort_values("data_decisao").reset_index(drop=True)
    # A nova taxa vale a partir do dia útil seguinte à decisão (anunciada à noite)
    df["data_efetiva"] = cal.deslocar(df["data_decisao"], 1)
    df["ano"] = df["data_decisao"].dt.year
    df["numero"] = df.groupby("ano").cumcount() + 1
    df["reuniao"] = "R" + df["numero"].astype(str) + "/" + df["ano"].astype(str)
    return df[["reuniao", "ano", "numero", "data_inicio", "data_decisao", "data_efetiva", "fonte"]]


def reunioes_fallback() -> pd.DataFrame:
    """Calendário embutido (2024–2027), usado sem acesso ao site do BCB."""
    inicios, decisoes = zip(*REUNIOES_COPOM_FALLBACK, strict=True)
    return _formatar_reunioes(pd.Series(decisoes), pd.Series(inicios), "embutido")


def baixar_reunioes_bcb() -> pd.DataFrame:
    """Calendário completo do Copom a partir do site do BCB.

    Combina a lista de atas (reuniões já realizadas, desde 1996) com a
    agenda oficial em formato ICS (reuniões futuras).
    """
    from .dados import _get

    atas = _get(URL_BCB_COPOM_ATAS + "?quantidade=500").json()["conteudo"]
    passadas = pd.to_datetime(pd.Series([a["dataReferencia"] for a in atas]))

    texto = _get(URL_BCB_COPOM_AGENDA).content.decode("utf-8-sig")
    texto = re.sub(r"\r?\n[ \t]", "", texto)
    dias = sorted({pd.Timestamp(m) for m in re.findall(r"DTSTART(?:;[^:]+)?:(\d{8})", texto)})
    # Cada reunião aparece como dois eventos em dias consecutivos: a decisão é o 2º dia
    futuras = [d2 for d1, d2 in zip(dias, dias[1:], strict=False) if (d2 - d1).days == 1]

    decisoes = pd.concat([passadas, pd.Series(futuras, dtype="datetime64[ns]")], ignore_index=True)
    return _formatar_reunioes(decisoes, None, "BCB")


def carregar_reunioes_copom(atualizar: bool = False) -> pd.DataFrame:
    """Calendário do Copom: BCB (se disponível), cache local ou lista embutida.

    As reuniões da lista embutida complementam as do BCB (por exemplo, datas
    futuras ainda não publicadas na agenda ICS).
    """
    embutido = reunioes_fallback()
    reunioes = None
    if atualizar:
        try:
            reunioes = baixar_reunioes_bcb()
            PASTA_DADOS.mkdir(parents=True, exist_ok=True)
            reunioes.to_csv(ARQUIVO_COPOM, index=False)
        except Exception as erro:  # noqa: BLE001 - qualquer falha cai no cache/fallback
            warnings.warn(f"Calendário do Copom via BCB indisponível ({erro}).", stacklevel=2)
    if reunioes is None and ARQUIVO_COPOM.exists():
        reunioes = pd.read_csv(ARQUIVO_COPOM, parse_dates=["data_inicio", "data_decisao", "data_efetiva"])
    if reunioes is None:
        return embutido
    todas = pd.concat([reunioes[["data_decisao", "fonte"]], embutido[["data_decisao", "fonte"]]])
    todas = todas.drop_duplicates("data_decisao", keep="first")
    inicios = embutido.set_index("data_decisao")["data_inicio"]
    resultado = _formatar_reunioes(todas["data_decisao"], None, todas["fonte"].to_numpy())
    resultado["data_inicio"] = resultado["data_decisao"].map(inicios)
    return resultado


# ---------------------------------------------------------------------------
# Selic implícita por reunião
# ---------------------------------------------------------------------------
GAP_MAXIMO_ULTIMA_REUNIAO = 40  # dias úteis após a última reunião conhecida
MAX_AMPLIFICACAO = 8.0


def selic_implicita(curva: CurvaDI, reunioes: pd.DataFrame, cdi_atual: float | None = None,
                    spread: float = SPREAD_SELIC_CDI, max_reunioes: int | None = None,
                    min_contratos_abertos: float | None = None,
                    max_amplificacao: float = MAX_AMPLIFICACAO) -> pd.DataFrame:
    """Caminho da Selic implícito na curva DI, reunião a reunião.

    Args:
        curva: Curva DI da data de referência (``CurvaDI.do_historico``).
        reunioes: Calendário (``carregar_reunioes_copom``).
        cdi_atual: CDI vigente (decimal). Só é usado se nenhum contrato vencer
            antes da próxima reunião; nesse caso, sem ``cdi_atual``, o
            primeiro contrato é usado como aproximação.
        spread: Diferença meta Selic − CDI (padrão 0,10 p.p.).
        max_reunioes: Limita o número de reuniões calculadas.
        min_contratos_abertos: Só usa contratos com pelo menos esse número de
            contratos em aberto (padrão: ``config.MIN_CONTRATOS_ABERTOS_COPOM``).
            Vencimentos pouco negociados têm ajuste "de modelo" e, como cada
            intervalo entre reuniões tem poucas semanas, pequenos ruídos neles
            viram saltos grandes na taxa de uma reunião.
        max_amplificacao: Um contrato só é usado para isolar uma reunião se
            ``du_contrato / dias_de_exposição_à_nova_taxa`` for no máximo esse
            valor. Essa razão é o quanto um erro de 1 bp no ajuste do contrato
            vira erro na taxa da reunião; acima do limite, a reunião é estimada
            junto com a seguinte (``agrupada=True``).

    Returns:
        DataFrame com uma linha por reunião futura: ``reuniao``,
        ``data_decisao``, ``data_efetiva``, ``cdi_implicito``,
        ``selic_implicita``, ``variacao_bps`` (vs. reunião anterior),
        ``acumulado_bps`` (vs. hoje), ``contrato`` usado e ``agrupada``
        (True quando não havia contrato para isolar a reunião e a taxa foi
        estimada junto com a reunião seguinte).

        ``resultado.attrs`` guarda ``cdi_atual`` (r_0) e ``fonte_cdi_atual``.
    """
    t = curva.data_referencia
    v = curva.vertices.sort_values("du")
    limite = MIN_CONTRATOS_ABERTOS_COPOM if min_contratos_abertos is None else min_contratos_abertos
    if limite and "contratos_abertos" in v and v["contratos_abertos"].notna().any():
        v = v[v["contratos_abertos"].fillna(0) >= limite]
    du_c = v["du"].to_numpy(dtype=float)
    lf_c = du_c / 252.0 * np.log1p(v["taxa"].to_numpy(dtype=float))  # log-fator de cada contrato
    codigos = v["codigo"].to_numpy()

    futuras = reunioes[reunioes["data_decisao"] >= t].sort_values("data_decisao")
    if max_reunioes:
        futuras = futuras.head(max_reunioes)
    if futuras.empty:
        raise ValueError("Não há reuniões futuras no calendário para essa data.")
    fronteiras = np.array([cal.dias_uteis(t, e) for e in futuras["data_efetiva"]], dtype=float)

    # --- r_0: CDI até a próxima reunião ---------------------------------
    antes = np.where(du_c <= fronteiras[0])[0]
    if len(antes):
        k = antes[-1]
        log_r0 = lf_c[k] / du_c[k] * 252.0
        fonte_r0 = f"contrato {codigos[k]}"
    elif cdi_atual is not None:
        log_r0 = np.log1p(cdi_atual)
        fonte_r0 = "CDI informado"
    else:
        log_r0 = lf_c[0] / du_c[0] * 252.0
        fonte_r0 = f"aproximação pelo {codigos[0]}"

    # --- bootstrap reunião a reunião ------------------------------------
    n = len(fronteiras)
    log_r = np.full(n, np.nan)
    contrato_usado = np.empty(n, dtype=object)
    agrupada = np.zeros(n, dtype=bool)

    acumulado = fronteiras[0] / 252.0 * log_r0  # log-fator de hoje até a 1ª data efetiva
    pendentes: list[int] = []  # reuniões sem contrato próprio, aguardando o próximo
    inicio_pendente = fronteiras[0]
    for i in range(n):
        if not pendentes:
            inicio_pendente = fronteiras[i]
        pendentes.append(i)
        fim = fronteiras[i + 1] if i + 1 < n else fronteiras[i] + GAP_MAXIMO_ULTIMA_REUNIAO
        exposicao = du_c - inicio_pendente
        with np.errstate(divide="ignore", invalid="ignore"):
            amplificacao = np.where(exposicao > 0, du_c / exposicao, np.inf)
        dentro = np.where((exposicao > 0) & (du_c <= fim) & (amplificacao <= max_amplificacao))[0]
        if not len(dentro):
            continue
        k = dentro[-1]  # contrato com maior exposição ao intervalo
        taxa_log = (lf_c[k] - acumulado) * 252.0 / (du_c[k] - inicio_pendente)
        for j in pendentes:
            log_r[j] = taxa_log
            contrato_usado[j] = codigos[k]
            agrupada[j] = len(pendentes) > 1
        # avança o acumulado até a próxima fronteira com a taxa encontrada
        proxima = fronteiras[i + 1] if i + 1 < n else fronteiras[i]
        acumulado += (proxima - inicio_pendente) / 252.0 * taxa_log
        pendentes = []

    resultado = futuras[["reuniao", "data_decisao", "data_efetiva"]].copy().reset_index(drop=True)
    resultado["du_ate_efetiva"] = fronteiras.astype(int)
    resultado["cdi_implicito"] = np.expm1(log_r)
    resultado["selic_implicita"] = resultado["cdi_implicito"] + spread
    r0 = float(np.expm1(log_r0))
    anteriores = np.concatenate([[r0], resultado["cdi_implicito"].to_numpy()[:-1]])
    resultado["variacao_bps"] = (resultado["cdi_implicito"] - anteriores) * 1e4
    resultado["acumulado_bps"] = (resultado["cdi_implicito"] - r0) * 1e4
    resultado["contrato"] = contrato_usado
    resultado["agrupada"] = agrupada
    resultado = resultado.dropna(subset=["cdi_implicito"])
    resultado.attrs.update({"data_referencia": t, "cdi_atual": r0, "selic_atual": r0 + spread,
                            "fonte_cdi_atual": fonte_r0})
    return resultado


def probabilidades_movimento(variacao_bps: float, passo: float = 25.0) -> dict[float, float]:
    """Traduz a variação implícita em probabilidades entre os dois passos vizinhos.

    Convenção de mesa: se o mercado precifica -18 bps e o Copom se move em
    passos de 25 bps, isso equivale a ~72% de chance de corte de 25 e ~28% de
    manutenção. (É uma leitura aproximada: ignora prêmio de risco.)

    Returns:
        Dicionário {movimento_em_bps: probabilidade}.
    """
    baixo = np.floor(variacao_bps / passo) * passo
    alto = baixo + passo
    p_alto = (variacao_bps - baixo) / passo
    if np.isclose(p_alto, 0.0):
        return {float(baixo): 1.0}
    return {float(baixo): float(1 - p_alto), float(alto): float(p_alto)}


def descrever_movimento(bps: float) -> str:
    if abs(bps) < 1e-9:
        return "manutenção"
    tipo = "alta" if bps > 0 else "corte"
    return f"{tipo} de {abs(bps):.0f} bps"


# ---------------------------------------------------------------------------
# Séries históricas
# ---------------------------------------------------------------------------
def historico_selic_implicita(historico: pd.DataFrame, reunioes: pd.DataFrame,
                              selic_cdi: pd.DataFrame | None = None, inicio=None,
                              max_reunioes: int = 8) -> pd.DataFrame:
    """Calcula o caminho implícito para todas as datas do histórico.

    Só usa datas cobertas pelo calendário (é preciso conhecer a reunião
    anterior e as próximas). O CDI vigente de cada dia vem, em ordem de
    preferência: de um contrato que vence antes da próxima reunião; da série
    do BCB (se disponível); ou do último valor identificado desde a reunião
    anterior.

    Returns:
        DataFrame "longo": uma linha por (data, reunião), com as colunas de
        ``selic_implicita`` mais ``data`` e ``cdi_atual``.
    """
    primeira_decisao = reunioes["data_decisao"].min()
    datas = pd.Series(historico["data"].unique()).sort_values()
    datas = datas[datas > primeira_decisao]
    if inicio is not None:
        datas = datas[datas >= pd.Timestamp(inicio)]
    ultima_decisao = reunioes["data_decisao"].max()
    datas = datas[datas <= ultima_decisao]

    cdi_bcb = selic_cdi["cdi"].dropna() if selic_cdi is not None and "cdi" in selic_cdi else None
    por_data = {d: g for d, g in historico[historico["data"].isin(datas)].groupby("data")}
    resultados = []
    r0_conhecido: float | None = None
    periodo_atual = None
    for d in datas:
        periodo = reunioes["data_decisao"].searchsorted(d)  # índice da próxima reunião
        if periodo != periodo_atual:
            periodo_atual, r0_conhecido = periodo, None
        cdi_dia = None
        if cdi_bcb is not None and d in cdi_bcb.index:
            cdi_dia = float(cdi_bcb.loc[d])
        elif r0_conhecido is not None:
            cdi_dia = r0_conhecido
        curva = CurvaDI(pd.Timestamp(d), por_data[d][por_data[d]["du"] > 0].sort_values("du"))
        try:
            caminho = selic_implicita(curva, reunioes, cdi_atual=cdi_dia, max_reunioes=max_reunioes)
        except ValueError:
            continue
        if caminho.attrs["fonte_cdi_atual"].startswith("contrato"):
            r0_conhecido = caminho.attrs["cdi_atual"]
        caminho.insert(0, "data", d)
        caminho["cdi_atual"] = caminho.attrs["cdi_atual"]
        caminho["fonte_cdi_atual"] = caminho.attrs["fonte_cdi_atual"]
        resultados.append(caminho)
    if not resultados:
        return pd.DataFrame()
    return pd.concat(resultados, ignore_index=True)


def surpresas_copom(historico_implicito: pd.DataFrame, reunioes: pd.DataFrame,
                    selic_cdi: pd.DataFrame | None = None, passo: float = 25.0) -> pd.DataFrame:
    """Compara o que estava precificado na véspera com o que o Copom decidiu.

    * **Precificado**: variação implícita para a reunião no fechamento do dia
      da decisão (o comunicado sai depois do fechamento do mercado).
    * **Decidido**: mudança do CDI vigente entre o dia da decisão e o dia
      seguinte, lida na própria curva (ou na meta Selic do BCB, se houver).
    * **Surpresa** = decidido − precificado.
    """
    linhas = []
    datas_disponiveis = set(pd.to_datetime(historico_implicito["data"].unique()))
    for _, reuniao in reunioes.iterrows():
        d, d1 = reuniao["data_decisao"], reuniao["data_efetiva"]
        if d not in datas_disponiveis or d1 not in datas_disponiveis:
            continue
        vespera = historico_implicito[(historico_implicito["data"] == d)
                                      & (historico_implicito["reuniao"] == reuniao["reuniao"])]
        depois = historico_implicito[historico_implicito["data"] == d1]
        if vespera.empty or depois.empty:
            continue
        precificado = float(vespera["variacao_bps"].iloc[0])
        cdi_antes = float(vespera["cdi_atual"].iloc[0])
        cdi_depois = float(depois["cdi_atual"].iloc[0])
        decidido_curva = (cdi_depois - cdi_antes) * 1e4
        decidido = round(decidido_curva / passo) * passo
        if selic_cdi is not None and "meta_selic" in selic_cdi:
            meta = selic_cdi["meta_selic"].dropna()
            antes_m = meta[meta.index <= d]
            depois_m = meta[meta.index >= d1]
            if len(antes_m) and len(depois_m):
                decidido = (float(depois_m.iloc[0]) - float(antes_m.iloc[-1])) * 1e4
        linhas.append({
            "reuniao": reuniao["reuniao"],
            "data_decisao": d,
            "precificado_bps": precificado,
            "decidido_bps": decidido,
            "decidido_curva_bps": decidido_curva,
            "surpresa_bps": decidido - precificado,
        })
    return pd.DataFrame(linhas)
