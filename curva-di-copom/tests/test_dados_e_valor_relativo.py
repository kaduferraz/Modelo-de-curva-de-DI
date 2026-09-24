import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from curva_di.curva import CurvaDI
from curva_di.dados import ler_boletim_b3, padronizar_di1
from curva_di.valor_relativo import carry_roll

FIXTURE = Path(__file__).parent / "fixtures" / "boletim_exemplo.xml"


def _zip_dentro_de_zip(xml: bytes) -> bytes:
    interno = io.BytesIO()
    with zipfile.ZipFile(interno, "w") as z:
        z.writestr("BVBG.187.01_exemplo.xml", xml)
    externo = io.BytesIO()
    with zipfile.ZipFile(externo, "w") as z:
        z.writestr("SPRD260112.zip", interno.getvalue())
    return externo.getvalue()


@pytest.mark.parametrize("empacotar", [False, True])
def test_ler_boletim_filtra_di1(empacotar):
    xml = FIXTURE.read_bytes()
    conteudo = _zip_dentro_de_zip(xml) if empacotar else xml
    df = ler_boletim_b3(conteudo)
    assert sorted(df["codigo"]) == ["DI1F27", "DI1N26"]  # ignora dólar e opções
    linha = df.set_index("codigo").loc["DI1F27"]
    assert linha["taxa_ajuste"] == pytest.approx(13.741)
    assert linha["contratos_abertos"] == 5495596


def test_padronizar_calcula_du_e_taxa_decimal():
    df = padronizar_di1(ler_boletim_b3(FIXTURE.read_bytes()), fonte="teste")
    f27 = df.set_index("codigo").loc["DI1F27"]
    assert f27["vencimento"] == pd.Timestamp("2027-01-04")
    assert f27["taxa"] == pytest.approx(0.13741)
    # o PU publicado bate com a taxa publicada e os dias úteis calculados
    assert (100_000 / f27["pu"]) ** (252 / f27["du"]) - 1 == pytest.approx(0.13741, abs=5e-6)


def test_boletim_vazio():
    assert ler_boletim_b3(b"").empty


def test_carry_roll_curva_plana_e_inclinada():
    def curva(taxas):
        v = pd.DataFrame({"du": [63, 252, 504, 1260, 2520], "taxa": taxas,
                          "codigo": list("ABCDE"), "vencimento": pd.NaT})
        return CurvaDI(pd.Timestamp("2026-09-23"), v)

    plana = carry_roll(curva([0.14] * 5))
    assert plana["carry_roll_bps"].abs().max() < 1e-6
    inclinada = carry_roll(curva([0.13, 0.135, 0.14, 0.145, 0.15]))
    assert (inclinada["carry_roll_bps"] > 0).all()


class _RespostaFalsa:
    def __init__(self, status: int, conteudo: bytes = b""):
        self.status_code = status
        self.content = conteudo

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_baixar_boletim_sem_arquivo_devolve_vazio(monkeypatch):
    from curva_di import dados

    monkeypatch.setattr(dados.requests, "get", lambda *a, **k: _RespostaFalsa(404))
    assert dados.baixar_boletim_b3("2026-09-24").empty


def test_baixar_boletim_com_arquivo(monkeypatch):
    from curva_di import dados

    conteudo = _zip_dentro_de_zip(FIXTURE.read_bytes())
    monkeypatch.setattr(dados.requests, "get", lambda *a, **k: _RespostaFalsa(200, conteudo))
    df = dados.baixar_boletim_b3("2026-01-12")
    assert set(df["codigo"]) == {"DI1F27", "DI1N26"}
