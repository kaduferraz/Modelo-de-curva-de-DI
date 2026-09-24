"""Análise de movimentos da curva: variações, PCA, regimes, z-scores e Copom.

As análises usam as séries de **prazo constante** (``curva.vertices_constantes``):
o "1A" de hoje e o "1A" de ontem são o mesmo ponto da curva, ainda que
representados por contratos diferentes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import JANELA_PADRAO

# Spreads padrão: inclinações (longo − curto) e butterflies (2·barriga − asas), em bps
INCLINACOES_PADRAO: dict[str, tuple[str, str]] = {
    "3M–1A": ("3M", "1A"),
    "1A–2A": ("1A", "2A"),
    "1A–5A": ("1A", "5A"),
    "2A–5A": ("2A", "5A"),
    "2A–10A": ("2A", "10A"),
    "5A–10A": ("5A", "10A"),
}
BUTTERFLIES_PADRAO: dict[str, tuple[str, str, str]] = {
    "6M/1A/2A": ("6M", "1A", "2A"),
    "1A/2A/5A": ("1A", "2A", "5A"),
    "1A/3A/5A": ("1A", "3A", "5A"),
    "2A/5A/10A": ("2A", "5A", "10A"),
}

NOMES_REGIME = [
    "Bear steepening", "Bear flattening", "Bull steepening", "Bull flattening",
    "Twist steepening", "Twist flattening", "Alta paralela", "Queda paralela", "Estável",
]

LEITURA_REGIME: dict[str, str] = {
    "Bear steepening": "juros sobem puxados pela ponta longa — em geral, aumento de prêmio de risco "
                       "(fiscal, inflação de longo prazo) mais do que mudança na Selic esperada",
    "Bear flattening": "juros sobem puxados pela ponta curta — o mercado passa a precificar uma "
                       "política monetária mais apertada nos próximos meses",
    "Bull steepening": "juros caem puxados pela ponta curta — o mercado antecipa cortes (ou menos "
                       "altas) da Selic",
    "Bull flattening": "juros caem puxados pela ponta longa — alívio de prêmio de risco ou fluxo "
                       "comprador de duration",
    "Twist steepening": "curto cai e longo sobe — cortes à frente, mas com desconforto sobre o longo "
                        "prazo (credibilidade, fiscal)",
    "Twist flattening": "curto sobe e longo cai — aperto monetário visto como crível, que ancora as "
                        "expectativas de longo prazo",
    "Alta paralela": "movimento de nível: a curva inteira sobe, sem mudança relevante de inclinação",
    "Queda paralela": "movimento de nível: a curva inteira cai, sem mudança relevante de inclinação",
    "Estável": "variações pequenas em toda a curva",
}


# ---------------------------------------------------------------------------
# Variações e spreads
# ---------------------------------------------------------------------------
def variacoes_bps(taxas: pd.DataFrame) -> pd.DataFrame:
    """Variação diária em pontos-base (taxas em decimal)."""
    return (taxas.diff() * 1e4).iloc[1:]


def spreads(taxas: pd.DataFrame, inclinacoes: dict | None = None,
            butterflies: dict | None = None) -> pd.DataFrame:
    """Inclinações e butterflies em bps a partir das taxas de prazo constante.

    * Inclinação "1A–5A" = taxa(5A) − taxa(1A). Positiva = curva positivamente inclinada.
    * Butterfly "1A/2A/5A" = 2·taxa(2A) − taxa(1A) − taxa(5A). Positiva = barriga
      "alta" (barata) em relação às asas.
    """
    inclinacoes = INCLINACOES_PADRAO if inclinacoes is None else inclinacoes
    butterflies = BUTTERFLIES_PADRAO if butterflies is None else butterflies
    saida = {}
    for nome, (curto, longo) in inclinacoes.items():
        if {curto, longo} <= set(taxas.columns):
            saida[nome] = (taxas[longo] - taxas[curto]) * 1e4
    for nome, (a, b, c) in butterflies.items():
        if {a, b, c} <= set(taxas.columns):
            saida[nome] = (2 * taxas[b] - taxas[a] - taxas[c]) * 1e4
    return pd.DataFrame(saida, index=taxas.index)


def zscore(serie: pd.Series | pd.DataFrame, janela: int = JANELA_PADRAO):
    """Z-score em janela móvel: (valor − média) / desvio-padrão da janela."""
    media = serie.rolling(janela, min_periods=janela // 2).mean()
    desvio = serie.rolling(janela, min_periods=janela // 2).std()
    return (serie - media) / desvio


def percentil_atual(serie: pd.Series, janela: int | None = JANELA_PADRAO) -> float:
    """Percentil (0–100) do último valor dentro da janela histórica."""
    dados = serie.dropna()
    if janela:
        dados = dados.iloc[-janela:]
    if dados.empty:
        return np.nan
    return float((dados <= dados.iloc[-1]).mean() * 100)


# ---------------------------------------------------------------------------
# PCA
# ---------------------------------------------------------------------------
@dataclass
class ResultadoPCA:
    """Resultado da decomposição da curva em componentes principais.

    Attributes:
        cargas: DataFrame (vértices × componentes). Mostra quanto cada vértice
            se move quando o fator anda 1 unidade.
        variancia_explicada: Série com a fração da variância total de cada componente.
        fatores: DataFrame (datas × componentes) com o valor diário de cada fator.
        desvio_fatores: Desvio-padrão diário de cada fator (bps).
    """

    cargas: pd.DataFrame
    variancia_explicada: pd.Series
    fatores: pd.DataFrame
    desvio_fatores: pd.Series

    def resumo(self) -> pd.DataFrame:
        return pd.DataFrame({
            "variancia_explicada_%": self.variancia_explicada * 100,
            "acumulada_%": self.variancia_explicada.cumsum() * 100,
            "desvio_diario_bps": self.desvio_fatores,
        })


def pca_curva(variacoes: pd.DataFrame, n_componentes: int = 3, janela: int | None = None) -> ResultadoPCA:
    """Decompõe as variações diárias da curva em nível, inclinação e curvatura.

    Usa a matriz de covariância das variações em bps (sem padronizar: todos os
    vértices estão na mesma unidade, e é justamente a diferença de volatilidade
    entre eles que interessa). Os sinais são normalizados para leitura:

    * Nível: todas as cargas positivas (a curva inteira sobe).
    * Inclinação: ponta longa positiva (a curva "abre" / inclina).
    * Curvatura: barriga positiva (a barriga sobe em relação às asas).

    Args:
        variacoes: Variações diárias em bps (datas × vértices).
        n_componentes: Número de componentes.
        janela: Se informado, usa só os últimos ``janela`` dias.
    """
    dados = variacoes.dropna()
    if janela:
        dados = dados.iloc[-janela:]
    centrado = dados - dados.mean()
    _, valores_singulares, vt = np.linalg.svd(centrado.to_numpy(), full_matrices=False)
    autovalores = valores_singulares**2 / (len(dados) - 1)
    cargas = vt[:n_componentes].T.copy()

    # normalização de sinais
    cargas[:, 0] *= np.sign(cargas[:, 0].sum()) or 1
    if n_componentes > 1:
        cargas[:, 1] *= np.sign(cargas[-1, 1] - cargas[0, 1]) or 1
    if n_componentes > 2:
        meio = len(cargas) // 2
        cargas[:, 2] *= np.sign(cargas[meio, 2] - (cargas[0, 2] + cargas[-1, 2]) / 2) or 1

    nomes = ["Nível", "Inclinação", "Curvatura", "PC4", "PC5", "PC6", "PC7"][:n_componentes]
    cargas_df = pd.DataFrame(cargas, index=dados.columns, columns=nomes)
    fatores = pd.DataFrame(centrado.to_numpy() @ cargas, index=dados.index, columns=nomes)
    variancia = pd.Series(autovalores[:n_componentes] / autovalores.sum(), index=nomes)
    return ResultadoPCA(cargas_df, variancia, fatores, fatores.std())


# ---------------------------------------------------------------------------
# Regimes de movimento
# ---------------------------------------------------------------------------
def classificar_movimento(delta_curto, delta_longo, limiar: float = 1.0):
    """Classifica o movimento da curva a partir da variação de dois vértices (bps).

    * **Bear** = juros sobem; **Bull** = juros caem (a referência é o preço).
    * **Steepening** = a curva inclina (longo − curto aumenta);
      **Flattening** = a curva achata.
    * **Twist** = curto e longo andam em direções opostas.

    Args:
        delta_curto: Variação do vértice curto (bps). Escalar ou Series.
        delta_longo: Variação do vértice longo (bps).
        limiar: Variações menores que isso (em bps) contam como zero.
    """
    escalar = np.ndim(delta_curto) == 0
    c = np.atleast_1d(np.asarray(delta_curto, dtype=float))
    lo = np.atleast_1d(np.asarray(delta_longo, dtype=float))
    inclinacao = lo - c
    nivel = (c + lo) / 2

    resultado = np.full(c.shape, "Estável", dtype=object)
    oposto = (np.abs(c) >= limiar) & (np.abs(lo) >= limiar) & (np.sign(c) != np.sign(lo))
    paralelo = np.abs(inclinacao) < limiar
    relevante = (np.abs(c) >= limiar) | (np.abs(lo) >= limiar)

    alta = nivel > 0
    inclina = inclinacao > 0
    resultado = np.where(relevante & ~oposto & ~paralelo & alta & inclina, "Bear steepening", resultado)
    resultado = np.where(relevante & ~oposto & ~paralelo & alta & ~inclina, "Bear flattening", resultado)
    resultado = np.where(relevante & ~oposto & ~paralelo & ~alta & inclina, "Bull steepening", resultado)
    resultado = np.where(relevante & ~oposto & ~paralelo & ~alta & ~inclina, "Bull flattening", resultado)
    resultado = np.where(relevante & ~oposto & paralelo & alta, "Alta paralela", resultado)
    resultado = np.where(relevante & ~oposto & paralelo & ~alta, "Queda paralela", resultado)
    resultado = np.where(oposto & inclina, "Twist steepening", resultado)
    resultado = np.where(oposto & ~inclina, "Twist flattening", resultado)
    resultado = np.where(np.isnan(c) | np.isnan(lo), None, resultado)

    if escalar:
        return resultado[0]
    if isinstance(delta_curto, pd.Series):
        return pd.Series(resultado, index=delta_curto.index, name="regime")
    return resultado


def regimes(variacoes: pd.DataFrame, curto: str = "1A", longo: str = "5A", limiar: float = 1.0) -> pd.DataFrame:
    """Tabela diária com a variação dos dois vértices e o regime do movimento."""
    tabela = pd.DataFrame({
        f"Δ{curto} (bps)": variacoes[curto],
        f"Δ{longo} (bps)": variacoes[longo],
        f"Δ inclinação {curto}–{longo} (bps)": variacoes[longo] - variacoes[curto],
    })
    tabela["regime"] = classificar_movimento(variacoes[curto], variacoes[longo], limiar)
    return tabela


def frequencia_regimes(tabela_regimes: pd.DataFrame, ultimos: int | None = JANELA_PADRAO) -> pd.DataFrame:
    """Quantas vezes cada regime ocorreu (e a variação média do nível nesses dias)."""
    dados = tabela_regimes.iloc[-ultimos:] if ultimos else tabela_regimes
    contagem = dados["regime"].value_counts().reindex(NOMES_REGIME).fillna(0).astype(int)
    return pd.DataFrame({"dias": contagem, "% dos dias": contagem / contagem.sum() * 100})


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------
def maiores_movimentos(variacoes: pd.DataFrame, vertice: str = "5A", n: int = 10) -> pd.DataFrame:
    """Os ``n`` dias com maior variação absoluta em um vértice."""
    serie = variacoes[vertice].dropna()
    datas = serie.abs().nlargest(n).index
    tabela = variacoes.loc[datas].copy()
    tabela.insert(0, "regime", classificar_movimento(variacoes.loc[datas, "1A"], variacoes.loc[datas, "5A"])
                  if {"1A", "5A"} <= set(variacoes.columns) else None)
    return tabela.round(1)


def reacao_copom(taxas: pd.DataFrame, reunioes: pd.DataFrame, vertices: list[str] | None = None) -> pd.DataFrame:
    """Reação da curva no pregão seguinte a cada decisão do Copom (bps).

    O comunicado sai depois do fechamento; por isso a reação é medida do
    fechamento do dia da decisão ao fechamento do dia útil seguinte.
    """
    vertices = vertices or [c for c in ["6M", "1A", "2A", "5A", "10A"] if c in taxas.columns]
    linhas = []
    for _, r in reunioes.iterrows():
        d, d1 = r["data_decisao"], r["data_efetiva"]
        if d in taxas.index and d1 in taxas.index:
            delta = (taxas.loc[d1, vertices] - taxas.loc[d, vertices]) * 1e4
            linha = {"reuniao": r["reuniao"], "data_decisao": d}
            linha.update({f"Δ{v}": delta[v] for v in vertices})
            linhas.append(linha)
    tabela = pd.DataFrame(linhas)
    if not tabela.empty and {"Δ1A", "Δ5A"} <= set(tabela.columns):
        tabela["regime"] = classificar_movimento(tabela["Δ1A"], tabela["Δ5A"])
    return tabela
