"""Calendário de dias úteis brasileiro (padrão ANBIMA/B3) e vencimentos do DI1.

Todo contrato de juros no Brasil é precificado em **dias úteis** (base 252).
Um erro de um único dia útil muda o PU de um DI1 longo em dezenas de reais,
então o calendário precisa ser exato.

Os feriados nacionais são gerados por regra (datas fixas + datas móveis que
dependem da Páscoa), sem depender de arquivo externo.

Detalhe importante: a Lei 14.759/2023 transformou o 20 de novembro (Dia
Nacional de Zumbi e da Consciência Negra) em feriado nacional. A ANBIMA e a B3
passaram a considerá-lo a partir de 26/12/2023. Por isso, contagens feitas
com data de referência anterior a essa data usam o calendário antigo.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Union

import numpy as np
import pandas as pd

DataLike = Union[str, dt.date, dt.datetime, pd.Timestamp, np.datetime64]

DATA_TRANSICAO_CONSCIENCIA_NEGRA = dt.date(2023, 12, 26)
ANO_INICIAL = 1990
ANO_FINAL = 2100

# Letra do mês no código de negociação de futuros da B3 (ex.: DI1F27 = jan/2027)
MESES_VENCIMENTO: dict[str, int] = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}
LETRA_DO_MES = {mes: letra for letra, mes in MESES_VENCIMENTO.items()}


# ---------------------------------------------------------------------------
# Feriados
# ---------------------------------------------------------------------------
def pascoa(ano: int) -> dt.date:
    """Domingo de Páscoa pelo algoritmo de Meeus/Jones/Butcher (calendário gregoriano)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes = (h + l_ - 7 * m + 114) // 31
    dia = (h + l_ - 7 * m + 114) % 31 + 1
    return dt.date(ano, mes, dia)


def feriados_nacionais(ano: int, incluir_consciencia_negra: bool = True) -> list[dt.date]:
    """Feriados nacionais considerados pela ANBIMA para contagem de dias úteis.

    Args:
        ano: Ano desejado.
        incluir_consciencia_negra: Se True, inclui 20/11 a partir de 2024
            (feriado nacional pela Lei 14.759/2023).
    """
    p = pascoa(ano)
    feriados = [
        dt.date(ano, 1, 1),  # Confraternização Universal
        p - dt.timedelta(days=48),  # Carnaval (segunda)
        p - dt.timedelta(days=47),  # Carnaval (terça)
        p - dt.timedelta(days=2),  # Sexta-feira Santa
        dt.date(ano, 4, 21),  # Tiradentes
        dt.date(ano, 5, 1),  # Dia do Trabalho
        p + dt.timedelta(days=60),  # Corpus Christi
        dt.date(ano, 9, 7),  # Independência
        dt.date(ano, 10, 12),  # Nossa Senhora Aparecida
        dt.date(ano, 11, 2),  # Finados
        dt.date(ano, 11, 15),  # Proclamação da República
        dt.date(ano, 12, 25),  # Natal
    ]
    if incluir_consciencia_negra and ano >= 2024:
        feriados.append(dt.date(ano, 11, 20))  # Zumbi e Consciência Negra
    return sorted(feriados)


@lru_cache(maxsize=2)
def _calendario_numpy(incluir_consciencia_negra: bool) -> np.busdaycalendar:
    feriados = [
        d
        for ano in range(ANO_INICIAL, ANO_FINAL + 1)
        for d in feriados_nacionais(ano, incluir_consciencia_negra)
    ]
    return np.busdaycalendar(weekmask="1111100", holidays=np.array(feriados, dtype="datetime64[D]"))


CAL_ATUAL = _calendario_numpy(True)
CAL_ANTERIOR = _calendario_numpy(False)


# ---------------------------------------------------------------------------
# Conversões
# ---------------------------------------------------------------------------
def _para_datetime64(datas) -> np.ndarray:
    """Converte data(s) em qualquer formato comum para array numpy datetime64[D]."""
    if isinstance(datas, (pd.Series, pd.Index, np.ndarray, list, tuple)):
        convertidas = pd.to_datetime(pd.Series(list(datas)) if isinstance(datas, (list, tuple)) else datas)
        return np.asarray(convertidas, dtype="datetime64[D]")
    return np.asarray(pd.Timestamp(datas).to_datetime64(), dtype="datetime64[D]")


def _saida(resultado: np.ndarray, entrada):
    """Devolve escalar para entrada escalar e array/Series para entrada vetorial."""
    if isinstance(entrada, pd.Series):
        return pd.Series(resultado, index=entrada.index)
    if np.ndim(resultado) == 0:
        valor = resultado.item()
        if isinstance(valor, dt.datetime):
            return valor.date()
        return valor
    return resultado


def _eh_escalar(x) -> bool:
    return not isinstance(x, (pd.Series, pd.Index, np.ndarray, list, tuple))


def _para_date(valor: np.datetime64) -> dt.date:
    return pd.Timestamp(valor).date()


# ---------------------------------------------------------------------------
# Operações com dias úteis
# ---------------------------------------------------------------------------
def dias_uteis(inicio: DataLike, fim: DataLike):
    """Número de dias úteis no intervalo [inicio, fim) — padrão B3/ANBIMA.

    O dia inicial conta (se for útil) e o final não, que é exatamente a
    contagem usada para precificar o DI1 na data ``inicio`` com vencimento
    em ``fim``. Aceita escalares ou vetores (Series, arrays, listas).

    Examples:
        >>> dias_uteis("2026-09-23", "2027-01-04")
        68
    """
    ini = _para_datetime64(inicio)
    fim_ = _para_datetime64(fim)
    atual = np.busday_count(ini, fim_, busdaycal=CAL_ATUAL)
    anterior = np.busday_count(ini, fim_, busdaycal=CAL_ANTERIOR)
    regime_antigo = ini < np.datetime64(DATA_TRANSICAO_CONSCIENCIA_NEGRA)
    resultado = np.where(regime_antigo, anterior, atual)
    if _eh_escalar(inicio) and _eh_escalar(fim):
        return int(resultado)
    if isinstance(inicio, pd.Series):
        return pd.Series(resultado, index=inicio.index)
    if isinstance(fim, pd.Series):
        return pd.Series(resultado, index=fim.index)
    return resultado


def eh_dia_util(data: DataLike):
    """True se a data for dia útil (dia de semana e não feriado nacional)."""
    resultado = np.is_busday(_para_datetime64(data), busdaycal=CAL_ATUAL)
    return bool(resultado) if _eh_escalar(data) else _saida(resultado, data)


def deslocar(data: DataLike, n: int):
    """Desloca ``n`` dias úteis. Se a data não for útil, parte do próximo dia útil.

    ``deslocar(d, 0)`` devolve o próprio dia (se útil) ou o próximo dia útil.
    """
    resultado = np.busday_offset(_para_datetime64(data), n, roll="forward", busdaycal=CAL_ATUAL)
    if _eh_escalar(data):
        return _para_date(resultado)
    if isinstance(data, pd.Series):
        return pd.Series(pd.to_datetime(resultado), index=data.index)
    return pd.to_datetime(resultado)


def dia_util_anterior(data: DataLike, n: int = 1):
    """Dia útil ``n`` posições antes de ``data`` (a própria data não conta)."""
    resultado = np.busday_offset(_para_datetime64(data), -n, roll="backward", busdaycal=CAL_ATUAL)
    if _eh_escalar(data):
        # roll backward mantém a data se ela já for útil; para n>=1 isso está correto
        return _para_date(resultado)
    return pd.to_datetime(resultado)


def gerar_dias_uteis(inicio: DataLike, fim: DataLike) -> pd.DatetimeIndex:
    """Todos os dias úteis no intervalo fechado [inicio, fim]."""
    datas = pd.date_range(pd.Timestamp(inicio), pd.Timestamp(fim), freq="D")
    return datas[np.is_busday(datas.values.astype("datetime64[D]"), busdaycal=CAL_ATUAL)]


def eh_dia_de_pregao(data: DataLike) -> bool:
    """Dia útil com pregão na B3 (não há pregão em 24/12 e 31/12)."""
    d = pd.Timestamp(data).date()
    if (d.month, d.day) in {(12, 24), (12, 31)}:
        return False
    return eh_dia_util(d)


def gerar_dias_de_pregao(inicio: DataLike, fim: DataLike) -> pd.DatetimeIndex:
    """Dias com pregão na B3 no intervalo fechado [inicio, fim]."""
    datas = gerar_dias_uteis(inicio, fim)
    fora = (datas.month == 12) & np.isin(datas.day, [24, 31])
    return datas[~fora]


# ---------------------------------------------------------------------------
# Vencimentos do DI1
# ---------------------------------------------------------------------------
def vencimento_di1(codigo):
    """Data de vencimento de um contrato DI1 a partir do código de negociação.

    O DI1 vence no primeiro dia útil do mês indicado pela letra.

    Examples:
        >>> vencimento_di1("DI1F27")
        datetime.date(2027, 1, 4)
    """
    if isinstance(codigo, str):
        codigo = codigo.strip().upper()
        mes = MESES_VENCIMENTO[codigo[3]]
        ano = 2000 + int(codigo[4:6])
        return deslocar(dt.date(ano, mes, 1), 0)

    codigos = pd.Series(codigo).astype(str).str.upper().str.strip()
    meses = codigos.str[3].map(MESES_VENCIMENTO)
    anos = 2000 + codigos.str[4:6].astype(int)
    primeiros = pd.to_datetime(pd.DataFrame({"year": anos, "month": meses, "day": 1}))
    vencimentos = np.busday_offset(
        primeiros.values.astype("datetime64[D]"), 0, roll="forward", busdaycal=CAL_ATUAL
    )
    resultado = pd.Series(pd.to_datetime(vencimentos), index=codigos.index)
    if isinstance(codigo, pd.Series):
        resultado.index = codigo.index
    return resultado


def codigo_di1(vencimento: DataLike) -> str:
    """Código de negociação do DI1 para um mês de vencimento (ex.: 2027-01 -> DI1F27)."""
    ts = pd.Timestamp(vencimento)
    return f"DI1{LETRA_DO_MES[ts.month]}{ts.year % 100:02d}"
