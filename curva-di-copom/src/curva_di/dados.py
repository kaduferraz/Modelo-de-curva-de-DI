"""Coleta e armazenamento local dos dados (B3 e Banco Central).

Fluxo de dados do projeto::

    B3 (boletim diário SPRD) ─┐
    Espelho histórico (2018+) ┴─> data/di1_historico.parquet ─> curva, Copom, movimentos
    BCB SGS (Selic, CDI) ────────> data/bcb_series.parquet
    BCB Focus (Selic/reunião) ───> data/focus_selic.parquet

Tudo é salvo em ``data/`` para que as análises rodem rápido e offline depois
da primeira coleta. Rode ``python scripts/atualizar_dados.py`` para atualizar.
"""

from __future__ import annotations

import datetime as dt
import io
import time
import warnings
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

from . import calendario as cal
from .config import (
    ARQUIVO_BCB,
    ARQUIVO_FOCUS,
    ARQUIVO_HISTORICO_DI1,
    CABECALHOS_HTTP,
    PASTA_DADOS,
    SGS_CDI_ANUAL,
    SGS_META_SELIC,
    TIMEOUT_HTTP,
    URL_B3_BOLETIM,
    URL_BCB_FOCUS_SELIC,
    URL_BCB_SGS,
    URL_ESPELHO_HISTORICO,
)
from .curva import pu as calcular_pu

COLUNAS_DI1 = ["data", "codigo", "vencimento", "du", "taxa", "pu", "contratos_abertos",
               "contratos_negociados", "fonte"]
FUSO_BRASILIA = dt.timezone(dt.timedelta(hours=-3))


class FonteIndisponivel(RuntimeError):
    """Uma fonte de dados externa não respondeu (sem internet, site fora do ar, etc.)."""


class ArquivoNaoEncontrado(FonteIndisponivel):
    """A fonte respondeu, mas o arquivo pedido não existe (ex.: boletim ainda não publicado)."""


def hoje_brasil() -> dt.date:
    return dt.datetime.now(FUSO_BRASILIA).date()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _get(url: str, tentativas: int = 3, timeout: int = TIMEOUT_HTTP) -> requests.Response:
    ultimo_erro: Exception | None = None
    for tentativa in range(tentativas):
        try:
            resposta = requests.get(url, headers=CABECALHOS_HTTP, timeout=timeout)
        except requests.RequestException as erro:  # noqa: PERF203 - rede instável: tenta de novo
            ultimo_erro = erro
            time.sleep(1.5 * (tentativa + 1))
            continue
        if resposta.status_code == 404:
            raise ArquivoNaoEncontrado(f"{url} não encontrado (404)")
        if resposta.status_code >= 500 or resposta.status_code == 429:
            ultimo_erro = requests.HTTPError(f"HTTP {resposta.status_code}")
            time.sleep(1.5 * (tentativa + 1))
            continue
        try:
            resposta.raise_for_status()
        except requests.HTTPError as erro:
            raise FonteIndisponivel(f"Falha ao acessar {url}: {erro}") from erro
        return resposta
    raise FonteIndisponivel(f"Falha ao acessar {url}: {ultimo_erro}")


# ---------------------------------------------------------------------------
# B3: boletim de preços (SPRD)
# ---------------------------------------------------------------------------
def _extrair_xml(conteudo: bytes) -> bytes | None:
    """Extrai o XML do arquivo da B3 (ZIP dentro de ZIP, ZIP simples ou XML puro)."""
    if conteudo[:4] != b"PK\x03\x04":
        return conteudo if conteudo.lstrip()[:1] == b"<" else None
    with zipfile.ZipFile(io.BytesIO(conteudo)) as externo:
        nomes = externo.namelist()
        if not nomes:
            return None
        xmls = sorted(n for n in nomes if n.lower().endswith(".xml"))
        if xmls:
            return externo.read(xmls[-1])
        return _extrair_xml(externo.read(nomes[0]))


def _sem_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def ler_boletim_b3(conteudo: bytes, prefixo: str = "DI1") -> pd.DataFrame:
    """Lê o boletim de preços da B3 e devolve os ajustes dos contratos futuros.

    Args:
        conteudo: Bytes do arquivo baixado (ZIP) ou do XML.
        prefixo: Prefixo do contrato (``DI1`` por padrão).

    Returns:
        DataFrame com colunas ``data``, ``codigo``, ``pu_ajuste``,
        ``taxa_ajuste`` (em % a.a., como publicado) e ``contratos_abertos``.
    """
    xml = _extrair_xml(conteudo) if conteudo else None
    if not xml:
        return pd.DataFrame(columns=["data", "codigo", "pu_ajuste", "taxa_ajuste", "contratos_abertos"])

    registros = []
    for _, elem in ET.iterparse(io.BytesIO(xml), events=("end",)):
        if _sem_namespace(elem.tag) != "PricRpt":
            continue
        campos: dict[str, str] = {}
        for filho in elem.iter():
            nome = _sem_namespace(filho.tag)
            if nome in {"Dt", "TckrSymb", "AdjstdQt", "AdjstdQtTax", "OpnIntrst", "FinInstrmQty"} and filho.text:
                campos.setdefault(nome, filho.text.strip())
        codigo = campos.get("TckrSymb", "")
        if codigo.startswith(prefixo) and len(codigo) == len(prefixo) + 3:
            registros.append(campos)
        elem.clear()

    df = pd.DataFrame(registros)
    if df.empty:
        return pd.DataFrame(columns=["data", "codigo", "pu_ajuste", "taxa_ajuste", "contratos_abertos"])
    saida = pd.DataFrame({
        "data": pd.to_datetime(df["Dt"]),
        "codigo": df["TckrSymb"],
        "pu_ajuste": pd.to_numeric(df.get("AdjstdQt"), errors="coerce"),
        "taxa_ajuste": pd.to_numeric(df.get("AdjstdQtTax"), errors="coerce"),
        "contratos_abertos": pd.to_numeric(df.get("OpnIntrst"), errors="coerce"),
    })
    if "FinInstrmQty" in df:
        saida["contratos_negociados"] = pd.to_numeric(df["FinInstrmQty"], errors="coerce")
    return saida


def baixar_boletim_b3(data, prefixo: str = "DI1") -> pd.DataFrame:
    """Baixa o boletim de um pregão direto do site da B3.

    Retorna DataFrame vazio se não houve pregão na data (ou se o arquivo
    ainda não foi publicado, o que acontece até o início da noite).
    """
    d = pd.Timestamp(data)
    url = URL_B3_BOLETIM.format(data=d.strftime("%y%m%d"))
    try:
        resposta = _get(url)
    except ArquivoNaoEncontrado:
        return ler_boletim_b3(b"", prefixo)
    # Dias sem pregão devolvem um arquivo vazio/minúsculo
    if len(resposta.content) < 1024:
        return ler_boletim_b3(b"", prefixo)
    try:
        return ler_boletim_b3(resposta.content, prefixo)
    except (zipfile.BadZipFile, ET.ParseError):
        return ler_boletim_b3(b"", prefixo)


def padronizar_di1(bruto: pd.DataFrame, fonte: str) -> pd.DataFrame:
    """Converte o formato bruto da B3 no formato padrão do projeto.

    Calcula vencimento e dias úteis, converte a taxa para decimal e descarta
    contratos já vencidos.
    """
    if bruto.empty:
        return pd.DataFrame(columns=COLUNAS_DI1)
    df = bruto.dropna(subset=["taxa_ajuste"]).copy()
    df["vencimento"] = cal.vencimento_di1(df["codigo"])
    df["du"] = cal.dias_uteis(df["data"], df["vencimento"]).astype(int)
    df = df[df["du"] > 0]
    df["taxa"] = df["taxa_ajuste"] / 100.0
    df["pu"] = df["pu_ajuste"].where(df["pu_ajuste"].notna(), calcular_pu(df["taxa"], df["du"]))
    if "contratos_negociados" not in df:
        df["contratos_negociados"] = np.nan
    df["fonte"] = fonte
    df["data"] = df["data"].astype("datetime64[ns]")
    df["vencimento"] = df["vencimento"].astype("datetime64[ns]")
    return (df[COLUNAS_DI1]
            .sort_values(["data", "vencimento"])
            .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Espelho histórico (bootstrap rápido)
# ---------------------------------------------------------------------------
def baixar_espelho_historico() -> pd.DataFrame:
    """Baixa o histórico de ajustes do DI1 desde 2018 (espelho público dos dados da B3).

    O arquivo é mantido pelo projeto open source PYield e contém exatamente
    os campos do boletim da B3. Usar o espelho evita baixar ~2.000 arquivos
    diários um a um na primeira execução.
    """
    resposta = _get(URL_ESPELHO_HISTORICO, timeout=120)
    bruto = pd.read_parquet(io.BytesIO(resposta.content))
    di1 = bruto[bruto["TckrSymb"].astype(str).str.match(r"^DI1[FGHJKMNQUVXZ]\d{2}$")]
    convertido = pd.DataFrame({
        "data": pd.to_datetime(di1["TradDt"]),
        "codigo": di1["TckrSymb"].astype(str),
        "pu_ajuste": pd.to_numeric(di1["AdjstdQt"], errors="coerce"),
        "taxa_ajuste": pd.to_numeric(di1["AdjstdQtTax"], errors="coerce"),
        "contratos_abertos": pd.to_numeric(di1["OpnIntrst"], errors="coerce"),
        "contratos_negociados": pd.to_numeric(di1.get("FinInstrmQty"), errors="coerce"),
    })
    return padronizar_di1(convertido, fonte="espelho B3")


# ---------------------------------------------------------------------------
# Histórico local do DI1
# ---------------------------------------------------------------------------
def _salvar(df: pd.DataFrame, caminho) -> None:
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    df.to_parquet(caminho, index=False)


def atualizar_historico_di1(ate=None, usar_espelho: bool = True, verbose: bool = True,
                            dias_max_via_b3: int = 15) -> pd.DataFrame:
    """Atualiza o histórico local do DI1 até a data ``ate`` (padrão: hoje).

    1. Se não existe histórico local (ou ele está muito defasado), baixa o
       espelho histórico completo.
    2. Completa os pregões que faltam baixando o boletim oficial da B3, dia a dia.

    Args:
        ate: Última data desejada.
        usar_espelho: Se False, nunca usa o espelho (só a B3).
        verbose: Mostra o progresso.
        dias_max_via_b3: Acima dessa defasagem, prefere rebaixar o espelho.
    """
    ate = pd.Timestamp(ate or hoje_brasil()).normalize()
    historico = carregar_historico_di1(atualizar=False, silencioso=True)

    defasagem = None
    if not historico.empty:
        defasagem = len(cal.gerar_dias_uteis(historico["data"].max() + pd.Timedelta(days=1), ate))

    if usar_espelho and (historico.empty or (defasagem or 0) > dias_max_via_b3):
        if verbose:
            print("Baixando histórico do DI1 (espelho dos dados da B3, desde 2018)...")
        try:
            espelho = baixar_espelho_historico()
            historico = _combinar(historico, espelho)
            if verbose:
                print(f"  {espelho['data'].nunique()} pregões até {espelho['data'].max():%d/%m/%Y}.")
        except FonteIndisponivel as erro:
            warnings.warn(f"Espelho indisponível ({erro}). Seguindo só com a B3.", stacklevel=2)

    inicio = (historico["data"].max() + pd.Timedelta(days=1)) if not historico.empty else ate - pd.Timedelta(days=30)
    faltantes = cal.gerar_dias_de_pregao(inicio, ate)
    novos = []
    for data in faltantes:
        try:
            bruto = baixar_boletim_b3(data)
        except FonteIndisponivel as erro:
            warnings.warn(f"B3 indisponível para {data:%d/%m/%Y}: {erro}", stacklevel=2)
            break
        if bruto.empty:
            if verbose:
                print(f"  {data:%d/%m/%Y}: sem boletim (feriado local, sem pregão ou ainda não publicado).")
            continue
        novos.append(padronizar_di1(bruto, fonte="B3"))
        if verbose:
            print(f"  {data:%d/%m/%Y}: {len(bruto)} contratos DI1 (B3).")

    if novos:
        historico = _combinar(historico, pd.concat(novos, ignore_index=True))
    if not historico.empty:
        _salvar(historico, ARQUIVO_HISTORICO_DI1)
        if verbose:
            print(f"Histórico salvo: {historico['data'].nunique()} pregões, "
                  f"de {historico['data'].min():%d/%m/%Y} a {historico['data'].max():%d/%m/%Y}.")
    return historico


def _combinar(antigo: pd.DataFrame, novo: pd.DataFrame) -> pd.DataFrame:
    if antigo.empty:
        return novo.reset_index(drop=True)
    juntos = pd.concat([antigo, novo], ignore_index=True)
    juntos = juntos.drop_duplicates(subset=["data", "codigo"], keep="last")
    return juntos.sort_values(["data", "vencimento"]).reset_index(drop=True)


def carregar_historico_di1(atualizar: bool = False, silencioso: bool = False) -> pd.DataFrame:
    """Lê o histórico local do DI1 (``data/di1_historico.parquet``).

    Args:
        atualizar: Se True, atualiza antes de ler (precisa de internet).
        silencioso: Se True, devolve DataFrame vazio quando não há arquivo.
    """
    if atualizar:
        return atualizar_historico_di1()
    if not ARQUIVO_HISTORICO_DI1.exists():
        if silencioso:
            return pd.DataFrame(columns=COLUNAS_DI1)
        raise FileNotFoundError(
            "Histórico do DI1 não encontrado. Rode `python scripts/atualizar_dados.py` "
            "ou `carregar_historico_di1(atualizar=True)`."
        )
    df = pd.read_parquet(ARQUIVO_HISTORICO_DI1)
    df["data"] = pd.to_datetime(df["data"]).astype("datetime64[ns]")
    df["vencimento"] = pd.to_datetime(df["vencimento"]).astype("datetime64[ns]")
    return df


# ---------------------------------------------------------------------------
# Banco Central: SGS (Selic e CDI)
# ---------------------------------------------------------------------------
def serie_sgs(codigo: int, inicio, fim=None) -> pd.Series:
    """Baixa uma série do SGS/BCB. Valores em % são convertidos para decimal.

    A API limita consultas de séries diárias a 10 anos; por isso a consulta
    é feita em blocos de 5 anos.
    """
    inicio = pd.Timestamp(inicio)
    fim = pd.Timestamp(fim or hoje_brasil())
    partes = []
    bloco_inicio = inicio
    while bloco_inicio <= fim:
        bloco_fim = min(bloco_inicio + pd.DateOffset(years=5) - pd.Timedelta(days=1), fim)
        url = (URL_BCB_SGS.format(codigo=codigo)
               + f"?formato=json&dataInicial={bloco_inicio:%d/%m/%Y}&dataFinal={bloco_fim:%d/%m/%Y}")
        dados = _get(url).json()
        if dados:
            partes.append(pd.DataFrame(dados))
        bloco_inicio = bloco_fim + pd.Timedelta(days=1)
    if not partes:
        return pd.Series(dtype=float)
    df = pd.concat(partes, ignore_index=True)
    serie = pd.Series(pd.to_numeric(df["valor"], errors="coerce").to_numpy() / 100.0,
                      index=pd.to_datetime(df["data"], format="%d/%m/%Y"), name=str(codigo))
    return serie[~serie.index.duplicated(keep="last")].sort_index()


def atualizar_selic_cdi(inicio="2018-01-01") -> pd.DataFrame:
    """Baixa meta Selic e CDI (base 252) do BCB e salva em ``data/``."""
    selic = serie_sgs(SGS_META_SELIC, inicio)
    cdi = serie_sgs(SGS_CDI_ANUAL, inicio)
    df = pd.DataFrame({"meta_selic": selic, "cdi": cdi}).sort_index()
    df.index.name = "data"
    df["meta_selic"] = df["meta_selic"].ffill()
    _salvar(df.reset_index(), ARQUIVO_BCB)
    return df


def carregar_selic_cdi(atualizar: bool = False) -> pd.DataFrame | None:
    """Série diária de meta Selic e CDI (decimal). ``None`` se indisponível."""
    if atualizar:
        try:
            return atualizar_selic_cdi()
        except FonteIndisponivel as erro:
            warnings.warn(f"BCB indisponível: {erro}", stacklevel=2)
    if ARQUIVO_BCB.exists():
        df = pd.read_parquet(ARQUIVO_BCB)
        return df.set_index(pd.to_datetime(df["data"])).drop(columns="data")
    return None


# ---------------------------------------------------------------------------
# Banco Central: Focus (Selic esperada por reunião do Copom)
# ---------------------------------------------------------------------------
def baixar_focus_selic(desde="2024-01-01", base_calculo: int = 0) -> pd.DataFrame:
    """Expectativas do Focus para a meta Selic em cada reunião do Copom.

    Args:
        desde: Data inicial das pesquisas.
        base_calculo: 0 = respostas dos últimos 30 dias (padrão do relatório
            Focus); 1 = apenas respostas dos últimos 5 dias úteis.

    Returns:
        DataFrame com ``data`` (da pesquisa), ``reuniao`` (ex.: ``R7/2026``),
        ``ano``, ``numero`` (ordem da reunião no ano), ``mediana``, ``media``,
        ``minimo``, ``maximo`` (decimal) e ``respondentes``.
    """
    filtro = f"Data ge '{pd.Timestamp(desde):%Y-%m-%d}' and baseCalculo eq {base_calculo}"
    campos = "Data,Reuniao,Media,Mediana,Minimo,Maximo,numeroRespondentes"
    url = (f"{URL_BCB_FOCUS_SELIC}?$filter={quote(filtro)}&$select={campos}"
           f"&$orderby={quote('Data desc')}&$top=100000&$format=json")
    dados = _get(url).json().get("value", [])
    if not dados:
        return pd.DataFrame()
    df = pd.DataFrame(dados)
    partes = df["Reuniao"].str.extract(r"R(\d+)/(\d{4})").astype(int)
    saida = pd.DataFrame({
        "data": pd.to_datetime(df["Data"]),
        "reuniao": df["Reuniao"],
        "numero": partes[0],
        "ano": partes[1],
        "mediana": df["Mediana"] / 100.0,
        "media": df["Media"] / 100.0,
        "minimo": df["Minimo"] / 100.0,
        "maximo": df["Maximo"] / 100.0,
        "respondentes": df["numeroRespondentes"],
    })
    return saida.sort_values(["data", "ano", "numero"]).reset_index(drop=True)


def carregar_focus_selic(atualizar: bool = False) -> pd.DataFrame | None:
    """Focus Selic por reunião (cache local). ``None`` se indisponível."""
    if atualizar:
        try:
            df = baixar_focus_selic()
            if not df.empty:
                _salvar(df, ARQUIVO_FOCUS)
                return df
        except FonteIndisponivel as erro:
            warnings.warn(f"Focus indisponível: {erro}", stacklevel=2)
    if ARQUIVO_FOCUS.exists():
        df = pd.read_parquet(ARQUIVO_FOCUS)
        df["data"] = pd.to_datetime(df["data"])
        return df
    return None
