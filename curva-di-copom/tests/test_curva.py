import numpy as np
import pandas as pd
import pytest

from curva_di import calendario as cal
from curva_di.curva import CurvaDI, dv01, interpolar_flat_forward, pu, taxa_de_pu, taxa_forward, vertices_constantes

# Ajustes reais da B3 em 23/09/2026 (código, PU de ajuste, taxa de ajuste em %)
AJUSTES_20260923 = [
    ("DI1V26", 99695.73, 13.654),
    ("DI1F27", 96630.77, 13.543),
    ("DI1F28", 85119.44, 13.573),
    ("DI1F29", 74781.05, 13.787),
    ("DI1F31", 57464.15, 13.965),
    ("DI1F36", 29882.21, 14.020),
]


@pytest.mark.parametrize("codigo, pu_b3, taxa_b3", AJUSTES_20260923)
def test_reproduz_taxa_de_ajuste_da_b3(codigo, pu_b3, taxa_b3):
    du = cal.dias_uteis("2026-09-23", cal.vencimento_di1(codigo))
    taxa = taxa_de_pu(pu_b3, du)
    assert round(taxa * 100, 3) == pytest.approx(taxa_b3, abs=1e-9)


def test_pu_e_taxa_sao_inversos():
    assert taxa_de_pu(pu(0.1365, 300), 300) == pytest.approx(0.1365)
    assert pu(0.0, 500) == pytest.approx(100_000)


def test_dv01_bate_com_derivada_numerica():
    taxa, du = 0.14, 756
    numerico = pu(taxa, du) - pu(taxa + 0.0001, du)
    assert dv01(taxa, du) == pytest.approx(numerico, rel=1e-3)


def test_forward_recompoe_os_fatores():
    t1, d1, t2, d2 = 0.13, 100, 0.14, 400
    fwd = taxa_forward(t1, d1, t2, d2)
    esquerda = (1 + t2) ** (d2 / 252)
    direita = (1 + t1) ** (d1 / 252) * (1 + fwd) ** ((d2 - d1) / 252)
    assert esquerda == pytest.approx(direita)


def test_flat_forward_respeita_vertices_e_forward_constante():
    du = np.array([50, 200, 500])
    taxas = np.array([0.13, 0.135, 0.14])
    assert interpolar_flat_forward(du, taxas, du) == pytest.approx(taxas)
    # dentro de um trecho, a forward entre quaisquer dois pontos é a mesma
    t_a, t_b, t_c = interpolar_flat_forward(du, taxas, [250, 300, 450])
    f1 = taxa_forward(t_a, 250, t_b, 300)
    f2 = taxa_forward(t_b, 300, t_c, 450)
    assert f1 == pytest.approx(f2)
    # antes do primeiro vértice a taxa fica constante
    assert interpolar_flat_forward(du, taxas, 10) == pytest.approx(0.13)


def _historico_sintetico():
    datas = pd.to_datetime(["2026-09-22", "2026-09-23"])
    linhas = []
    for i, d in enumerate(datas):
        for du, taxa in [(10, 0.1365), (70, 0.1354), (320, 0.1357), (820, 0.1392), (1330, 0.14)]:
            linhas.append({"data": d, "codigo": f"X{du}", "du": du, "taxa": taxa + i * 0.0005,
                           "contratos_abertos": 200_000, "vencimento": d + pd.Timedelta(days=int(du * 1.45))})
    return pd.DataFrame(linhas)


def test_curva_do_historico_e_vertices_constantes():
    hist = _historico_sintetico()
    curva = CurvaDI.do_historico(hist)
    assert curva.data_referencia == pd.Timestamp("2026-09-23")
    assert curva.taxa(70) == pytest.approx(0.1359)
    serie = vertices_constantes(hist, {"1A": 252, "5A": 1260, "10A": 2520})
    assert list(serie.columns) == ["1A", "5A", "10A"]
    assert serie["10A"].isna().all()  # além do contrato mais longo
    assert (serie["1A"].diff().iloc[-1]) == pytest.approx(0.0005, abs=1e-9)
