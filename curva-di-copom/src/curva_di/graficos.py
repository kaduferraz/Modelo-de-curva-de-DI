"""Gráficos (Plotly) usados no notebook, no dashboard e nas figuras do README.

Padrão visual: marcas finas (linhas de 2 px), grade discreta, um único eixo
por gráfico, legenda sempre que houver mais de uma série e cores com função
fixa (azul = série principal, laranja = comparação, verde-água = terceira
série; vermelho/azul para alta/queda de taxa). A paleta foi validada para
daltonismo nos modos claro e escuro.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .calendario import CAL_ATUAL
from .copom import probabilidades_movimento
from .curva import CurvaDI
from .movimentos import ResultadoPCA

TEMAS = {
    "claro": {
        "superficie": "#fcfcfb", "texto": "#0b0b0b", "texto2": "#52514e", "mudo": "#898781",
        "grade": "#e1e0d9", "eixo": "#c3c2b7",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
        "alta": "#e34948", "queda": "#2a78d6", "neutro": "#c3c2b7", "faixa": "rgba(42,120,214,0.10)",
    },
    "escuro": {
        "superficie": "#1a1a19", "texto": "#ffffff", "texto2": "#c3c2b7", "mudo": "#898781",
        "grade": "#2c2c2a", "eixo": "#383835",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500"],
        "alta": "#e66767", "queda": "#3987e5", "neutro": "#4a4a47", "faixa": "rgba(57,135,229,0.16)",
    },
}
FONTE = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"


def _tema(tema: str) -> dict:
    return TEMAS.get(tema, TEMAS["claro"])


def _layout(fig: go.Figure, titulo: str, tema: str, titulo_y: str = "", titulo_x: str = "",
            altura: int = 440, hover: str = "x unified", subtitulo: str | None = None,
            eixo_data: bool = False) -> go.Figure:
    t = _tema(tema)
    titulo_cfg = {"text": f"<b>{titulo}</b>", "x": 0, "xref": "paper", "xanchor": "left",
                  "y": 0.98, "yref": "container", "yanchor": "top",
                  "font": {"size": 16, "color": t["texto"]}}
    if subtitulo:
        titulo_cfg["subtitle"] = {"text": subtitulo, "font": {"size": 12, "color": t["texto2"]}}
    # Legenda embaixo do gráfico (não disputa espaço com título e subtítulo ao quebrar linha)
    tem_legenda = sum(1 for tr in fig.data if tr.showlegend is not False) > 1
    fig.update_layout(
        title=titulo_cfg,
        font={"family": FONTE, "size": 12, "color": t["texto2"]},
        paper_bgcolor=t["superficie"], plot_bgcolor=t["superficie"],
        height=altura + (48 if tem_legenda else 0),
        margin={"l": 64, "r": 24, "t": 84 if subtitulo else 60, "b": (104 if tem_legenda else 56) + (18 if titulo_x else 0)},
        hovermode=hover,
        hoverlabel={"font": {"family": FONTE, "size": 12}},
        legend={"orientation": "h", "yref": "container", "yanchor": "bottom", "y": 0.02,
                "xanchor": "left", "x": 0, "font": {"color": t["texto2"]}, "bgcolor": "rgba(0,0,0,0)"},
    )
    eixo = {"gridcolor": t["grade"], "gridwidth": 1, "linecolor": t["eixo"], "zerolinecolor": t["eixo"],
            "tickfont": {"color": t["mudo"]}, "title": {"font": {"color": t["texto2"]}}}
    fig.update_xaxes(**eixo, title_text=titulo_x, showline=True)
    if eixo_data:  # datas no formato brasileiro (o Plotly usa nomes de meses em inglês)
        fig.update_xaxes(tickformat="%m/%Y", hoverformat="%d/%m/%Y")
    fig.update_yaxes(**eixo, title_text=titulo_y, showline=False)
    return fig


def _cores_sinal(valores, tema: str) -> list[str]:
    t = _tema(tema)
    return [t["alta"] if v > 0 else t["queda"] if v < 0 else t["neutro"] for v in valores]


# ---------------------------------------------------------------------------
# Curva
# ---------------------------------------------------------------------------
def grafico_curva(curva: CurvaDI, comparacao: CurvaDI | None = None, tema: str = "claro",
                  anos_max: float | None = None) -> go.Figure:
    """Curva DI do dia: contratos observados + curva interpolada (flat forward)."""
    t = _tema(tema)
    fig = go.Figure()
    v = curva.vertices.copy()
    if anos_max:
        v = v[v["du"] <= anos_max * 252]
    grade = curva.curva_interpolada(passo_du=2, du_max=int(v["du"].max()))
    datas_grade = pd.to_datetime(np.busday_offset(np.datetime64(curva.data_referencia.date()),
                                                  grade["du"].to_numpy(), roll="forward", busdaycal=CAL_ATUAL))

    if comparacao is not None:
        vc = comparacao.vertices
        if anos_max:
            vc = vc[vc["du"] <= anos_max * 252]
        fig.add_trace(go.Scatter(
            x=vc["vencimento"], y=vc["taxa"] * 100, mode="lines+markers",
            name=f"Curva em {comparacao.data_referencia:%d/%m/%Y}",
            line={"color": t["series"][1], "width": 2}, marker={"size": 6},
            customdata=np.stack([vc["codigo"], vc["du"]], axis=-1),
            hovertemplate="%{customdata[0]} · %{y:.3f}%<extra>" + f"{comparacao.data_referencia:%d/%m}</extra>",
        ))

    fig.add_trace(go.Scatter(
        x=datas_grade, y=grade["taxa"] * 100, mode="lines", name=f"Curva em {curva.data_referencia:%d/%m/%Y} (flat forward)",
        line={"color": t["series"][0], "width": 2}, hoverinfo="skip",
    ))
    for liquido, nome, simbolo in [(True, "Vencimentos líquidos", "circle"),
                                   (False, "Pouco negociados (ajuste de modelo)", "circle-open")]:
        parte = v[v["liquido"] == liquido] if "liquido" in v else (v if liquido else v.iloc[0:0])
        if parte.empty:
            continue
        oi = parte["contratos_abertos"].fillna(0) / 1000 if "contratos_abertos" in parte else np.zeros(len(parte))
        fig.add_trace(go.Scatter(
            x=parte["vencimento"], y=parte["taxa"] * 100, mode="markers", name=nome,
            marker={"size": 9, "symbol": simbolo, "color": t["series"][0],
                    "line": {"width": 2, "color": t["series"][0] if not liquido else t["superficie"]}},
            customdata=np.stack([parte["codigo"], parte["du"], oi], axis=-1),
            hovertemplate=("<b>%{customdata[0]}</b> · %{y:.3f}%<br>%{customdata[1]} dias úteis"
                           "<br>%{customdata[2]:,.0f} mil contratos em aberto<extra></extra>"),
        ))
    return _layout(fig, "Curva de juros DI — estrutura a termo prefixada", tema,
                   titulo_y="Taxa (% a.a., base 252)", titulo_x="Vencimento", hover="closest", eixo_data=True,
                   subtitulo="Taxas de ajuste dos contratos DI1 na B3, interpoladas por flat forward")


def grafico_forwards(curva: CurvaDI, tema: str = "claro", anos_max: float = 6) -> go.Figure:
    """Taxas a termo entre vencimentos consecutivos (degraus) versus a curva spot."""
    t = _tema(tema)
    fw = curva.tabela_forwards()
    fw = fw[fw["du"] <= anos_max * 252]
    inicio = [curva.data_referencia] + list(fw["vencimento"].iloc[:-1])
    xs = inicio + [fw["vencimento"].iloc[-1]]
    ys = list(fw["forward"] * 100) + [fw["forward"].iloc[-1] * 100]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=fw["vencimento"], y=fw["taxa"] * 100, name="Taxa spot (até o vencimento)",
                             mode="lines+markers", line={"color": t["series"][0], "width": 2}, marker={"size": 6},
                             hovertemplate="spot %{y:.3f}%<extra></extra>"))
    fig.add_trace(go.Scatter(x=xs, y=ys, name="Taxa a termo (entre vencimentos)", mode="lines",
                             line={"color": t["series"][1], "width": 2, "shape": "hv"},
                             hovertemplate="forward %{y:.3f}%<extra></extra>"))
    return _layout(fig, "Taxas a termo implícitas na curva", tema, titulo_y="% a.a.", titulo_x="Vencimento",
                   subtitulo="Cada degrau é o CDI médio precificado entre dois vencimentos", eixo_data=True)


# ---------------------------------------------------------------------------
# Copom
# ---------------------------------------------------------------------------
MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _rotulo_reuniao(linha) -> str:
    d = linha["data_decisao"]
    return f"{MESES_PT[d.month - 1]}/{d:%y}"


def grafico_copom_variacoes(caminho: pd.DataFrame, tema: str = "claro", n: int = 8) -> go.Figure:
    """Movimento da Selic precificado para cada reunião (bps)."""
    dados = caminho.head(n)
    rotulos = [_rotulo_reuniao(r) for _, r in dados.iterrows()]
    textos = [f"{v:+.0f}" for v in dados["variacao_bps"]]
    probs_txt = []
    for v in dados["variacao_bps"]:
        probs = probabilidades_movimento(v)
        probs_txt.append(" · ".join(f"{p * 100:.0f}% em {k:+.0f} bps"
                                    for k, p in sorted(probs.items()) if p >= 0.01))
    fig = go.Figure(go.Bar(
        x=rotulos, y=dados["variacao_bps"], marker={"color": _cores_sinal(dados["variacao_bps"], tema),
                                                    "cornerradius": 4},
        text=textos, textposition="outside", cliponaxis=False,
        textfont={"color": _tema(tema)["texto2"]},
        customdata=np.stack([probs_txt, dados["selic_implicita"] * 100, dados["contrato"]], axis=-1),
        hovertemplate=("<b>%{y:+.1f} bps</b><br>%{customdata[0]}<br>Selic implícita: %{customdata[1]:.2f}%"
                       "<br>contrato: %{customdata[2]}<extra></extra>"),
        name="Variação implícita",
    ))
    fig.add_hline(y=0, line={"color": _tema(tema)["eixo"], "width": 1})
    ref = caminho.attrs.get("data_referencia")
    sub = f"Copom · curva DI de {ref:%d/%m/%Y}" if ref is not None else None
    fig.update_layout(bargap=0.45)
    return _layout(fig, "Movimento precificado por reunião", tema,
                   titulo_y="bps (vs. reunião anterior)", hover="closest", subtitulo=sub)


def grafico_copom_caminho(caminho: pd.DataFrame, focus_reunioes: pd.DataFrame | None = None,
                          tema: str = "claro", n: int = 8) -> go.Figure:
    """Caminho da Selic implícito na curva (degraus) versus a mediana do Focus."""
    t = _tema(tema)
    dados = caminho.head(n)
    ref = caminho.attrs.get("data_referencia", dados["data_decisao"].iloc[0] - pd.Timedelta(days=30))
    selic_hoje = caminho.attrs.get("selic_atual", dados["selic_implicita"].iloc[0])
    xs = [ref] + list(dados["data_efetiva"])
    ys = [selic_hoje * 100] + list(dados["selic_implicita"] * 100)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name="Selic implícita na curva DI",
                             line={"color": t["series"][0], "width": 2, "shape": "hv"}, marker={"size": 8},
                             hovertemplate="%{y:.2f}%<extra>curva</extra>"))
    if focus_reunioes is not None and not focus_reunioes.empty:
        f = dados.merge(focus_reunioes[["reuniao", "mediana"]], on="reuniao", how="inner")
        if not f.empty:
            fig.add_trace(go.Scatter(x=f["data_efetiva"], y=f["mediana"] * 100, mode="markers",
                                     name="Mediana do Focus", marker={"size": 10, "symbol": "diamond",
                                                                      "color": t["series"][1]},
                                     hovertemplate="%{y:.2f}%<extra>Focus</extra>"))
    return _layout(fig, "Caminho implícito da Selic", tema, titulo_y="Meta Selic (% a.a.)",
                   subtitulo="Curva DI vs. Focus · degraus nas datas em que a decisão vale", eixo_data=True)


def grafico_precificacao_reuniao(historico_implicito: pd.DataFrame, reuniao: str, tema: str = "claro") -> go.Figure:
    """Como a precificação de uma reunião específica evoluiu ao longo do tempo."""
    t = _tema(tema)
    dados = historico_implicito[historico_implicito["reuniao"] == reuniao].sort_values("data")
    fig = go.Figure(go.Scatter(x=dados["data"], y=dados["acumulado_bps"], mode="lines",
                               line={"color": t["series"][0], "width": 2}, name="Acumulado até a reunião",
                               hovertemplate="%{y:+.0f} bps<extra></extra>"))
    fig.add_hline(y=0, line={"color": t["eixo"], "width": 1})
    return _layout(fig, f"Precificação acumulada até a reunião {reuniao}", tema,
                   titulo_y="bps vs. CDI vigente em cada data", eixo_data=True,
                   subtitulo="Quanto de alta (+) ou corte (−) a curva embutia até essa reunião, dia a dia")


def grafico_surpresas(surpresas: pd.DataFrame, tema: str = "claro") -> go.Figure:
    """Precificado na véspera vs. decidido, para cada reunião."""
    t = _tema(tema)
    rotulos = [f"{r['reuniao']}" for _, r in surpresas.iterrows()]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=rotulos, y=surpresas["precificado_bps"], name="Precificado na véspera",
                         marker={"color": t["series"][0], "cornerradius": 4},
                         hovertemplate="precificado %{y:+.1f} bps<extra></extra>"))
    fig.add_trace(go.Bar(x=rotulos, y=surpresas["decidido_bps"], name="Decidido pelo Copom",
                         marker={"color": t["series"][1], "cornerradius": 4},
                         hovertemplate="decidido %{y:+.0f} bps<extra></extra>"))
    fig.add_hline(y=0, line={"color": t["eixo"], "width": 1})
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    return _layout(fig, "O que a curva precificava vs. o que o Copom decidiu", tema,
                   titulo_y="Variação da Selic (bps)",
                   subtitulo="Precificado = leitura da curva DI no fechamento do dia da decisão")


# ---------------------------------------------------------------------------
# Movimentos
# ---------------------------------------------------------------------------
def grafico_historico_vertices(taxas: pd.DataFrame, colunas=("1A", "5A", "10A"), tema: str = "claro",
                               desde=None) -> go.Figure:
    t = _tema(tema)
    dados = taxas.loc[pd.Timestamp(desde):] if desde is not None else taxas
    fig = go.Figure()
    for i, c in enumerate(colunas):
        fig.add_trace(go.Scatter(x=dados.index, y=dados[c] * 100, name=c, mode="lines",
                                 line={"color": t["series"][i % 4], "width": 2},
                                 hovertemplate=f"{c}: " + "%{y:.2f}%<extra></extra>"))
    return _layout(fig, "Taxas de prazo constante", tema, titulo_y="% a.a.", eixo_data=True,
                   subtitulo="Sempre o mesmo prazo (interpolado), não o mesmo contrato")


def grafico_variacao_dia(delta: pd.Series, data, tema: str = "claro") -> go.Figure:
    """Variação de cada vértice no dia (bps). Vermelho = taxa subiu; azul = caiu."""
    fig = go.Figure(go.Bar(x=list(delta.index), y=delta.values,
                           marker={"color": _cores_sinal(delta.values, tema), "cornerradius": 4},
                           text=[f"{v:+.1f}" for v in delta.values], textposition="outside", cliponaxis=False,
                           textfont={"color": _tema(tema)["texto2"]},
                           hovertemplate="%{x}: %{y:+.1f} bps<extra></extra>", name="Variação"))
    fig.add_hline(y=0, line={"color": _tema(tema)["eixo"], "width": 1})
    fig.update_layout(bargap=0.45)
    return _layout(fig, f"Variação em {pd.Timestamp(data):%d/%m/%Y}", tema,
                   titulo_y="bps", hover="closest", subtitulo="Vermelho: taxa subiu · Azul: taxa caiu")


def grafico_pca(pca: ResultadoPCA, tema: str = "claro") -> go.Figure:
    """Cargas dos componentes principais por vértice."""
    t = _tema(tema)
    fig = go.Figure()
    for i, comp in enumerate(pca.cargas.columns):
        fig.add_trace(go.Scatter(
            x=list(pca.cargas.index), y=pca.cargas[comp], mode="lines+markers",
            name=f"{comp} ({pca.variancia_explicada[comp] * 100:.1f}% da variância)",
            line={"color": t["series"][i % 4], "width": 2}, marker={"size": 8},
            hovertemplate=f"{comp} · " + "%{x}: %{y:.2f}<extra></extra>"))
    fig.add_hline(y=0, line={"color": t["eixo"], "width": 1})
    return _layout(fig, "PCA: os três fatores que movem a curva", tema, titulo_y="Carga (peso do vértice)",
                   titulo_x="Vértice", hover="closest",
                   subtitulo="Nível desloca tudo · Inclinação gira a curva · Curvatura mexe a barriga")


def grafico_spread(serie: pd.Series, nome: str, janela: int = 252, tema: str = "claro", desde=None) -> go.Figure:
    """Histórico de um spread com média e faixa de ±1 desvio da janela móvel."""
    t = _tema(tema)
    media = serie.rolling(janela, min_periods=janela // 2).mean()
    desvio = serie.rolling(janela, min_periods=janela // 2).std()
    if desde is not None:
        serie, media, desvio = (x.loc[pd.Timestamp(desde):] for x in (serie, media, desvio))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=media.index, y=media + desvio, mode="lines", line={"width": 0},
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=media.index, y=media - desvio, mode="lines", line={"width": 0},
                             fill="tonexty", fillcolor=t["faixa"], name="Média ± 1 desvio (12m)",
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=media.index, y=media, mode="lines", name="Média móvel (12m)",
                             line={"color": t["mudo"], "width": 1.5}, hovertemplate="média %{y:.0f} bps<extra></extra>"))
    fig.add_trace(go.Scatter(x=serie.index, y=serie, mode="lines", name=nome,
                             line={"color": t["series"][0], "width": 2},
                             hovertemplate=f"{nome}: " + "%{y:.0f} bps<extra></extra>"))
    fig.add_hline(y=0, line={"color": t["eixo"], "width": 1})
    return _layout(fig, f"Spread {nome}", tema, titulo_y="bps", eixo_data=True)


def grafico_carry(tabela_carry: pd.DataFrame, tema: str = "claro", horizonte: str = "3 meses") -> go.Figure:
    t = _tema(tema)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=list(tabela_carry.index), y=tabela_carry["carry_bps"], name="Carry",
                         marker={"color": t["series"][0], "cornerradius": 4},
                         hovertemplate="carry %{y:+.1f} bps<extra></extra>"))
    fig.add_trace(go.Bar(x=list(tabela_carry.index), y=tabela_carry["roll_down_bps"], name="Roll-down",
                         marker={"color": t["series"][2], "cornerradius": 4},
                         hovertemplate="roll-down %{y:+.1f} bps<extra></extra>"))
    fig.add_hline(y=0, line={"color": t["eixo"], "width": 1})
    fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08)
    return _layout(fig, "Carry e roll-down (dar taxa)", tema,
                   titulo_y="bps de taxa", titulo_x="Vértice", hover="x unified",
                   subtitulo=f"Horizonte de {horizonte}, curva parada")


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
def salvar_png(fig: go.Figure, caminho: str | Path, largura: int = 1100, altura: int | None = None,
               escala: float = 2) -> bool:
    """Salva a figura como PNG (requer ``kaleido`` e um Chrome instalado). Retorna True se salvou."""
    try:
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        fig.write_image(str(caminho), width=largura, height=altura or fig.layout.height or 440, scale=escala)
        return True
    except Exception as erro:  # noqa: BLE001
        print(f"Não foi possível salvar {caminho}: {erro}")
        return False
