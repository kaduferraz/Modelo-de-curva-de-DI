import datetime as dt

import numpy as np
import pandas as pd
import pytest

from curva_di import calendario as cal


@pytest.mark.parametrize("ano, esperado", [
    (2024, dt.date(2024, 3, 31)),
    (2025, dt.date(2025, 4, 20)),
    (2026, dt.date(2026, 4, 5)),
    (2027, dt.date(2027, 3, 28)),
])
def test_pascoa(ano, esperado):
    assert cal.pascoa(ano) == esperado


def test_feriados_2026():
    esperado = {
        dt.date(2026, 1, 1), dt.date(2026, 2, 16), dt.date(2026, 2, 17), dt.date(2026, 4, 3),
        dt.date(2026, 4, 21), dt.date(2026, 5, 1), dt.date(2026, 6, 4), dt.date(2026, 9, 7),
        dt.date(2026, 10, 12), dt.date(2026, 11, 2), dt.date(2026, 11, 15), dt.date(2026, 11, 20),
        dt.date(2026, 12, 25),
    }
    assert set(cal.feriados_nacionais(2026)) == esperado


def test_consciencia_negra_so_a_partir_de_2024():
    assert dt.date(2023, 11, 20) not in cal.feriados_nacionais(2023)
    assert dt.date(2024, 11, 20) in cal.feriados_nacionais(2024)


def test_dias_uteis_contagem_b3():
    # DI1F27 em 23/09/2026: 68 dias úteis (confere com o PU de ajuste da B3)
    assert cal.dias_uteis("2026-09-23", "2027-01-04") == 68
    # intervalo [inicio, fim): o dia final não conta
    assert cal.dias_uteis("2026-09-21", "2026-09-22") == 1
    assert cal.dias_uteis("2026-09-21", "2026-09-21") == 0


def test_regime_antigo_antes_da_lei():
    # Referência antes de 26/12/2023: 20/11/2024 ainda contava como dia útil
    antes = cal.dias_uteis("2023-12-01", "2024-12-02")
    depois = cal.dias_uteis("2023-12-26", "2024-12-02") + cal.dias_uteis("2023-12-01", "2023-12-26")
    assert antes == depois + 1


def test_dias_uteis_vetorizado():
    inicio = pd.Series(pd.to_datetime(["2026-09-23", "2026-09-23"]))
    fim = pd.Series(pd.to_datetime(["2027-01-04", "2026-10-01"]))
    resultado = cal.dias_uteis(inicio, fim)
    assert list(resultado) == [68, 6]


def test_deslocar_e_dia_util():
    assert cal.deslocar("2026-09-16", 1) == dt.date(2026, 9, 17)
    assert cal.deslocar("2026-11-19", 1) == dt.date(2026, 11, 23)  # pula o 20/11 e o fim de semana
    assert cal.deslocar("2026-11-20", 0) == dt.date(2026, 11, 23)
    assert not cal.eh_dia_util("2026-11-20")
    assert cal.eh_dia_util("2026-11-19")


@pytest.mark.parametrize("codigo, vencimento", [
    ("DI1F27", dt.date(2027, 1, 4)),   # 01/01 é feriado e 02-03/01 é fim de semana
    ("DI1N26", dt.date(2026, 7, 1)),
    ("DI1V26", dt.date(2026, 10, 1)),
    ("di1x26", dt.date(2026, 11, 3)),  # 01/11 é domingo e 02/11 é Finados
])
def test_vencimento_di1(codigo, vencimento):
    assert cal.vencimento_di1(codigo) == vencimento


def test_vencimento_vetorizado_e_codigo():
    venc = cal.vencimento_di1(pd.Series(["DI1F27", "DI1N26"]))
    assert list(venc.dt.date) == [dt.date(2027, 1, 4), dt.date(2026, 7, 1)]
    assert cal.codigo_di1("2027-01-04") == "DI1F27"


def test_dias_de_pregao_excluem_24_e_31_de_dezembro():
    dias = cal.gerar_dias_de_pregao("2026-12-20", "2027-01-05")
    assert pd.Timestamp("2026-12-24") not in dias
    assert pd.Timestamp("2026-12-31") not in dias
    assert pd.Timestamp("2026-12-23") in dias
    assert np.all(cal.eh_dia_util(dias))
