import numpy as np
import pandas as pd
import pytest

from curva_di import calendario as cal
from curva_di.copom import (
    probabilidades_movimento,
    reunioes_fallback,
    selic_implicita,
)
from curva_di.curva import CurvaDI


def test_calendario_embutido():
    r = reunioes_fallback()
    assert (r.groupby("ano").size() == 8).all()
    assert (r["data_decisao"].dt.dayofweek == 2).all()  # decisões sempre numa quarta-feira
    assert r.loc[r["reuniao"] == "R6/2026", "data_decisao"].iloc[0] == pd.Timestamp("2026-09-16")
    assert r.loc[r["reuniao"] == "R6/2026", "data_efetiva"].iloc[0] == pd.Timestamp("2026-09-17")


def _curva_com_caminho(data_ref, reunioes, r0, movimentos_bps):
    """Monta contratos DI1 mensais consistentes com um caminho de Selic conhecido."""
    data_ref = pd.Timestamp(data_ref)
    futuras = reunioes[reunioes["data_decisao"] >= data_ref].head(len(movimentos_bps))
    fronteiras = [cal.dias_uteis(data_ref, e) for e in futuras["data_efetiva"]]
    taxas_intervalo = [r0]
    for m in movimentos_bps:
        taxas_intervalo.append(taxas_intervalo[-1] + m / 1e4)

    linhas = []
    for mes in pd.date_range(data_ref + pd.offsets.MonthBegin(1), periods=14, freq="MS"):
        venc = pd.Timestamp(cal.deslocar(mes, 0))
        du = cal.dias_uteis(data_ref, venc)
        limites = [0] + fronteiras + [10_000]
        log_f = sum(max(0, min(du, limites[i + 1]) - limites[i]) / 252 * np.log1p(taxas_intervalo[i])
                    for i in range(len(taxas_intervalo)))
        taxa = np.expm1(log_f * 252 / du)
        linhas.append({"data": data_ref, "codigo": cal.codigo_di1(venc), "vencimento": venc, "du": du,
                       "taxa": taxa, "contratos_abertos": 1e6})
    return CurvaDI(data_ref, pd.DataFrame(linhas))


def test_recupera_caminho_conhecido():
    reunioes = reunioes_fallback()
    movimentos = [-25, -25, 0, -50, 0, 25]
    curva = _curva_com_caminho("2026-09-23", reunioes, 0.1365, movimentos)
    caminho = selic_implicita(curva, reunioes, max_reunioes=len(movimentos))
    isoladas = caminho[~caminho["agrupada"]]
    esperado = pd.Series(movimentos, index=caminho["reuniao"])
    assert len(isoladas) >= 4
    for _, linha in isoladas.iterrows():
        anteriores_agrupadas = caminho.loc[: linha.name - 1, "agrupada"]
        if anteriores_agrupadas.any():
            continue
        assert linha["variacao_bps"] == pytest.approx(esperado[linha["reuniao"]], abs=0.05)
    assert caminho.attrs["cdi_atual"] == pytest.approx(0.1365, abs=1e-9)
    assert caminho["selic_implicita"].iloc[0] == pytest.approx(0.1365 - 0.0025 + 0.0010, abs=1e-6)


def test_probabilidades_movimento():
    probs = probabilidades_movimento(-18)
    assert probs[-25.0] == pytest.approx(0.72)
    assert probs[0.0] == pytest.approx(0.28)
    assert probabilidades_movimento(-50) == {-50.0: 1.0}
    assert sum(probabilidades_movimento(37).values()) == pytest.approx(1)
