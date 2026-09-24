"""Construção da curva DI: PU, taxas, interpolação flat forward, forwards e DV01.

Convenções usadas em todo o projeto:

* Taxas em **decimal** ao ano, base 252 dias úteis (13,65% a.a. = 0.1365).
* Variações em **pontos-base** (1 bp = 0,01 p.p. = 0.0001).
* ``du`` = dias úteis entre a data de referência (inclusive) e o vencimento
  (exclusive), como a B3 conta.

Fórmulas básicas do DI1 (valor de face R$ 100.000 no vencimento)::

    PU    = 100.000 / (1 + taxa) ** (du / 252)
    taxa  = (100.000 / PU) ** (252 / du) - 1
    DV01  = PU * (du / 252) / (1 + taxa) * 0.0001      # R$ por contrato por 1 bp
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import BASE_DU, VALOR_FACE_DI1


# ---------------------------------------------------------------------------
# Fórmulas do contrato
# ---------------------------------------------------------------------------
def _num(x):
    """Mantém Series do pandas (preserva o índice); o resto vira array numpy."""
    return x.astype(float) if isinstance(x, pd.Series) else np.asarray(x, dtype=float)


def fator(taxa, du):
    """Fator de capitalização (1 + taxa) ** (du / 252)."""
    return (1.0 + _num(taxa)) ** (_num(du) / BASE_DU)


def pu(taxa, du, valor_face: float = VALOR_FACE_DI1):
    """PU do DI1 dado a taxa (decimal) e os dias úteis até o vencimento."""
    return valor_face / fator(taxa, du)


def taxa_de_pu(preco, du, valor_face: float = VALOR_FACE_DI1):
    """Taxa (decimal a.a.) implícita em um PU."""
    return (valor_face / _num(preco)) ** (BASE_DU / _num(du)) - 1.0


def dv01(taxa, du, valor_face: float = VALOR_FACE_DI1):
    """Variação do PU (R$ por contrato) para 1 bp de alta na taxa.

    É a derivada do PU em relação à taxa, multiplicada por 1 bp. O sinal é
    omitido: quando a taxa sobe, o PU cai nesse valor.
    """
    duration = _num(du) / BASE_DU
    return pu(taxa, du, valor_face) * duration / (1.0 + _num(taxa)) * 1e-4


def taxa_forward(taxa_1, du_1, taxa_2, du_2):
    """Taxa a termo entre du_1 e du_2 (decimal a.a.).

    É a taxa que, aplicada entre os dois prazos, iguala os fatores:
    (1 + t2)^(du2/252) = (1 + t1)^(du1/252) * (1 + fwd)^((du2 - du1)/252)
    """
    razao = fator(taxa_2, du_2) / fator(taxa_1, du_1)
    return razao ** (BASE_DU / (_num(du_2) - _num(du_1))) - 1.0


# ---------------------------------------------------------------------------
# Interpolação
# ---------------------------------------------------------------------------
def interpolar_flat_forward(du_vertices, taxas_vertices, du_alvo):
    """Interpola a curva pelo método flat forward (padrão do mercado brasileiro).

    O log do fator de capitalização é interpolado linearmente em dias úteis,
    o que equivale a supor uma **taxa a termo constante** entre dois vértices.
    Antes do primeiro vértice, a taxa é mantida constante; depois do último,
    a última taxa a termo é estendida.

    Args:
        du_vertices: Dias úteis dos vértices conhecidos (crescentes, > 0).
        taxas_vertices: Taxas dos vértices (decimal a.a.).
        du_alvo: Prazo(s) desejado(s) em dias úteis.

    Returns:
        Taxa(s) interpolada(s), no mesmo formato de ``du_alvo``.
    """
    x = np.asarray(du_vertices, dtype=float)
    y = np.asarray(taxas_vertices, dtype=float)
    ordem = np.argsort(x)
    x, y = x[ordem], y[ordem]
    alvo = np.atleast_1d(np.asarray(du_alvo, dtype=float))

    log_fator = x / BASE_DU * np.log1p(y)
    resultado = np.empty_like(alvo)

    antes = alvo <= x[0]
    resultado[antes] = y[0]

    meio = (alvo > x[0]) & (alvo <= x[-1])
    if meio.any():
        lf = np.interp(alvo[meio], x, log_fator)
        resultado[meio] = np.expm1(lf * BASE_DU / alvo[meio])

    depois = alvo > x[-1]
    if depois.any():
        if len(x) >= 2:
            fwd_log = (log_fator[-1] - log_fator[-2]) / (x[-1] - x[-2])
        else:
            fwd_log = np.log1p(y[-1]) / BASE_DU
        lf = log_fator[-1] + fwd_log * (alvo[depois] - x[-1])
        resultado[depois] = np.expm1(lf * BASE_DU / alvo[depois])

    if np.ndim(du_alvo) == 0:
        return float(resultado[0])
    return resultado


# ---------------------------------------------------------------------------
# Curva de um dia
# ---------------------------------------------------------------------------
@dataclass
class CurvaDI:
    """Curva DI de uma data, montada a partir dos ajustes dos contratos DI1.

    Attributes:
        data_referencia: Data da curva.
        vertices: DataFrame com colunas ``codigo``, ``vencimento``, ``du``,
            ``taxa``, ``pu`` e ``contratos_abertos`` (um contrato por linha).
    """

    data_referencia: pd.Timestamp
    vertices: pd.DataFrame = field(repr=False)

    @classmethod
    def do_historico(cls, historico: pd.DataFrame, data=None, apenas_liquidos: bool = False,
                     min_contratos_abertos: int | None = None) -> "CurvaDI":
        """Monta a curva de uma data a partir do histórico (padrão: último dia).

        Args:
            historico: DataFrame no formato de ``dados.carregar_historico_di1``.
            data: Data desejada. Se não houver pregão nela, usa o último
                pregão anterior.
            apenas_liquidos: Se True, descarta contratos pouco negociados.
            min_contratos_abertos: Limite de contratos em aberto para o filtro
                de liquidez (padrão em ``config``).
        """
        from .config import MIN_CONTRATOS_ABERTOS_LIQUIDO

        datas = historico["data"].drop_duplicates().sort_values()
        if data is None:
            data_ref = datas.iloc[-1]
        else:
            anteriores = datas[datas <= pd.Timestamp(data)]
            if anteriores.empty:
                raise ValueError(f"Não há dados até {pd.Timestamp(data):%d/%m/%Y}.")
            data_ref = anteriores.iloc[-1]

        dia = historico[historico["data"] == data_ref].copy()
        dia = dia[dia["du"] > 0].sort_values("du")
        limite = MIN_CONTRATOS_ABERTOS_LIQUIDO if min_contratos_abertos is None else min_contratos_abertos
        if "contratos_abertos" in dia:
            dia["liquido"] = dia["contratos_abertos"].fillna(0) >= limite
        else:
            dia["liquido"] = True
        if apenas_liquidos:
            dia = dia[dia["liquido"]]
        return cls(pd.Timestamp(data_ref), dia.reset_index(drop=True))

    # --- consultas -------------------------------------------------------
    @property
    def du(self) -> np.ndarray:
        return self.vertices["du"].to_numpy(dtype=float)

    @property
    def taxas(self) -> np.ndarray:
        return self.vertices["taxa"].to_numpy(dtype=float)

    def taxa(self, du):
        """Taxa spot (decimal a.a.) para qualquer prazo, via flat forward."""
        return interpolar_flat_forward(self.du, self.taxas, du)

    def fator(self, du):
        return fator(self.taxa(du), du)

    def forward(self, du_1, du_2):
        """Taxa a termo entre dois prazos quaisquer (decimal a.a.)."""
        return taxa_forward(self.taxa(du_1), du_1, self.taxa(du_2), du_2)

    def tabela_forwards(self) -> pd.DataFrame:
        """Forwards entre vértices consecutivos (o "degrau" de cada trecho da curva)."""
        v = self.vertices[["codigo", "vencimento", "du", "taxa"]].copy()
        du_ant = v["du"].shift(1)
        taxa_ant = v["taxa"].shift(1)
        v["forward"] = taxa_forward(taxa_ant, du_ant, v["taxa"], v["du"])
        # O primeiro trecho vai de hoje ao primeiro vencimento: forward = spot
        v.loc[v.index[0], "forward"] = v.loc[v.index[0], "taxa"]
        v["du_inicio"] = du_ant.fillna(0).astype(int)
        return v

    def curva_interpolada(self, passo_du: int = 5, du_max: int | None = None) -> pd.DataFrame:
        """Curva contínua (para gráficos), de ``passo_du`` em ``passo_du`` dias úteis."""
        du_max = int(self.du.max()) if du_max is None else du_max
        grade = np.arange(max(1, passo_du), du_max + 1, passo_du)
        return pd.DataFrame({"du": grade, "taxa": self.taxa(grade)})


# ---------------------------------------------------------------------------
# Vértices de prazo constante (séries históricas)
# ---------------------------------------------------------------------------
def vertices_constantes(historico: pd.DataFrame, prazos: dict[str, int] | None = None,
                        min_contratos_abertos: int = 0) -> pd.DataFrame:
    """Série histórica de taxas em prazos fixos (ex.: 1 ano, 5 anos).

    Os contratos DI1 têm vencimento fixo, então "envelhecem" a cada dia. Para
    estudar os movimentos da curva é preciso olhar sempre o mesmo prazo, e
    por isso cada dia é interpolado (flat forward) nos prazos desejados.

    Args:
        historico: DataFrame com colunas ``data``, ``du``, ``taxa`` e,
            opcionalmente, ``contratos_abertos``.
        prazos: Dicionário {rótulo: dias úteis}. Padrão: ``config.VERTICES_PADRAO``.
        min_contratos_abertos: Filtro de liquidez opcional.

    Returns:
        DataFrame (índice = data, colunas = rótulos) com taxas em decimal.
        Prazos além do contrato mais longo do dia ficam como NaN.
    """
    from .config import VERTICES_PADRAO

    prazos = VERTICES_PADRAO if prazos is None else prazos
    rotulos = list(prazos)
    alvo = np.array([prazos[r] for r in rotulos], dtype=float)

    base = historico[historico["du"] > 0]
    if min_contratos_abertos and "contratos_abertos" in base:
        base = base[base["contratos_abertos"].fillna(0) >= min_contratos_abertos]

    linhas = {}
    for data, dia in base.groupby("data", sort=True):
        dia = dia.sort_values("du")
        if len(dia) < 2:
            continue
        taxas = interpolar_flat_forward(dia["du"].to_numpy(), dia["taxa"].to_numpy(), alvo)
        taxas = np.where(alvo <= dia["du"].max(), taxas, np.nan)
        linhas[data] = taxas

    resultado = pd.DataFrame.from_dict(linhas, orient="index", columns=rotulos)
    resultado.index = pd.DatetimeIndex(resultado.index, name="data")
    return resultado
