import numpy as np
import pandas as pd
import pytest

from curva_di.movimentos import classificar_movimento, pca_curva, spreads


@pytest.mark.parametrize("curto, longo, esperado", [
    (5, 12, "Bear steepening"),
    (12, 5, "Bear flattening"),
    (-12, -5, "Bull steepening"),
    (-5, -12, "Bull flattening"),
    (-6, 8, "Twist steepening"),
    (6, -8, "Twist flattening"),
    (7, 7.5, "Alta paralela"),
    (-7, -7.2, "Queda paralela"),
    (0.3, -0.4, "Estável"),
])
def test_classificacao(curto, longo, esperado):
    assert classificar_movimento(curto, longo) == esperado


def test_classificacao_vetorizada():
    s = classificar_movimento(pd.Series([5.0, -5.0]), pd.Series([12.0, -12.0]))
    assert list(s) == ["Bear steepening", "Bull flattening"]


def test_pca_recupera_fatores_sinteticos():
    rng = np.random.default_rng(42)
    vertices = ["3M", "6M", "1A", "2A", "3A", "5A", "10A"]
    x = np.linspace(0, 1, len(vertices))
    nivel = rng.normal(0, 10, 1000)
    inclinacao = rng.normal(0, 3, 1000)
    dados = np.outer(nivel, np.ones(len(vertices))) + np.outer(inclinacao, x - 0.5)
    dados += rng.normal(0, 0.3, dados.shape)
    variacoes = pd.DataFrame(dados, columns=vertices)
    resultado = pca_curva(variacoes)
    assert resultado.variancia_explicada["Nível"] > 0.9
    assert (resultado.cargas["Nível"] > 0).all()  # sinal normalizado
    assert resultado.cargas["Inclinação"].iloc[-1] > resultado.cargas["Inclinação"].iloc[0]
    assert resultado.variancia_explicada.sum() <= 1.0


def test_spreads_em_bps():
    taxas = pd.DataFrame({"1A": [0.13], "2A": [0.135], "5A": [0.14]})
    s = spreads(taxas, inclinacoes={"1A–5A": ("1A", "5A")}, butterflies={"1A/2A/5A": ("1A", "2A", "5A")})
    assert s["1A–5A"].iloc[0] == pytest.approx(100)
    assert s["1A/2A/5A"].iloc[0] == pytest.approx(0)
