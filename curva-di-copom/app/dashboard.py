"""Dashboard interativo: curva DI, Selic implícita por reunião do Copom e movimentos da curva.

Rode a partir da raiz do repositório:
    streamlit run app/dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from curva_di import comentario, copom, dados, graficos, movimentos, valor_relativo  # noqa: E402
from curva_di.analise import montar_analise  # noqa: E402
from curva_di.config import VERTICES_PADRAO  # noqa: E402
from curva_di.curva import CurvaDI  # noqa: E402

st.set_page_config(page_title="Curva DI & Copom", page_icon="📈", layout="wide")


def _tema() -> str:
    """Tema dos gráficos: o configurado em .streamlit/config.toml ou, se não houver, o do navegador."""
    tipo = st.get_option("theme.base")
    if tipo not in ("dark", "light"):
        try:
            tipo = st.context.theme.type
        except Exception:  # noqa: BLE001 - versões antigas do Streamlit
            tipo = "light"
    return "escuro" if tipo == "dark" else "claro"


TEMA = _tema()


def mostrar(fig) -> None:
    st.plotly_chart(fig, theme=None, config={"displaylogo": False})


def arred(df: pd.DataFrame, casas: int = 1) -> pd.DataFrame:
    """Arredonda só as colunas numéricas (e descarta metadados que o Streamlit não serializa)."""
    saida = df.copy()
    saida.attrs = {}
    numericas = saida.select_dtypes("number").columns
    saida[numericas] = saida[numericas].round(casas)
    return saida


def pct(x: float, casas: int = 2) -> str:
    return f"{x * 100:.{casas}f}%".replace(".", ",")


def bps(x: float, casas: int = 1) -> str:
    return f"{x:+.{casas}f} bps".replace(".", ",")


# ---------------------------------------------------------------------------
# Dados (com cache)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Lendo o histórico do DI1...")
def carregar_historico() -> pd.DataFrame:
    return dados.carregar_historico_di1(silencioso=True)


@st.cache_data(show_spinner="Calculando curva, Copom e movimentos...")
def analisar(data: pd.Timestamp, _historico: pd.DataFrame, versao: str):
    return montar_analise(data, historico=_historico)


@st.cache_data(show_spinner="Reconstruindo a precificação do Copom no histórico...")
def historico_copom(_historico: pd.DataFrame, _reunioes: pd.DataFrame, _selic_cdi, versao: str):
    hist = copom.historico_selic_implicita(_historico, _reunioes, _selic_cdi)
    return hist, copom.surpresas_copom(hist, _reunioes, _selic_cdi)


def atualizar_tudo() -> None:
    with st.status("Atualizando dados (B3 e Banco Central)...", expanded=True) as status:
        st.write("Curva DI (B3)...")
        dados.atualizar_historico_di1(verbose=False)
        st.write("Calendário do Copom, Selic, CDI e Focus (BCB)...")
        copom.carregar_reunioes_copom(atualizar=True)
        dados.carregar_selic_cdi(atualizar=True)
        dados.carregar_focus_selic(atualizar=True)
        status.update(label="Dados atualizados.", state="complete")
    st.cache_data.clear()


historico = carregar_historico()

with st.sidebar:
    st.header("Curva DI & Copom")
    if st.button("Atualizar dados", type="primary", width="stretch"):
        atualizar_tudo()
        st.rerun()

if historico.empty:
    st.title("Curva DI & Copom")
    st.info("Ainda não há dados locais. Clique em **Atualizar dados** na barra lateral "
            "(ou rode `python scripts/atualizar_dados.py`). A primeira carga baixa o histórico desde 2018.")
    st.stop()

datas = pd.DatetimeIndex(sorted(historico["data"].unique()))
versao = f"{datas[-1]:%Y%m%d}-{len(historico)}"

with st.sidebar:
    escolhida = st.date_input("Data de referência", value=datas[-1].date(), min_value=datas[0].date(),
                              max_value=datas[-1].date(), format="DD/MM/YYYY")
    comparar_com = st.selectbox("Comparar com", ["Pregão anterior", "1 semana antes", "1 mês antes",
                                                 "3 meses antes", "1 ano antes"], index=2)
    st.caption(f"Dados de {datas[0]:%d/%m/%Y} a {datas[-1]:%d/%m/%Y} · {len(datas)} pregões.")
    st.caption("Fontes: B3 (ajustes do DI1), Banco Central (Selic, CDI, Focus e calendário do Copom).")

a = analisar(pd.Timestamp(escolhida), historico, versao)
deslocamentos = {"Pregão anterior": None, "1 semana antes": 7, "1 mês antes": 30, "3 meses antes": 91,
                 "1 ano antes": 365}
dias = deslocamentos[comparar_com]
curva_comp = a.curva_anterior if dias is None else CurvaDI.do_historico(a.historico, a.data - pd.Timedelta(days=dias))

# ---------------------------------------------------------------------------
# Cabeçalho
# ---------------------------------------------------------------------------
st.title("Curva de juros DI e Selic implícita por reunião do Copom")
st.caption(f"Pregão de referência: **{a.data:%d/%m/%Y}** · comparação: {curva_comp.data_referencia:%d/%m/%Y}")

delta_dia = a.variacoes.iloc[-1] if not a.variacoes.empty else pd.Series(dtype=float)
c1, c2, c3, c4, c5 = st.columns(5)
if a.caminho is not None and not a.caminho.empty:
    prox = a.caminho.iloc[0]
    probs = copom.probabilidades_movimento(prox["variacao_bps"])
    principal = max(probs, key=probs.get)
    anterior = None
    if a.caminho_anterior is not None:
        mesma = a.caminho_anterior[a.caminho_anterior["reuniao"] == prox["reuniao"]]
        anterior = mesma["variacao_bps"].iloc[0] if not mesma.empty else None
    c1.metric("Selic vigente (implícita)", pct(a.caminho.attrs["selic_atual"]),
              help="CDI vigente lido na curva + spread de 0,10 p.p.")
    c2.metric(f"Copom {prox['data_decisao']:%d/%m}: precificado", bps(prox["variacao_bps"]),
              delta=bps(prox["variacao_bps"] - anterior) + " no dia" if anterior is not None else None,
              delta_color="off", help="Variação da Selic implícita na curva para a próxima reunião.")
    c3.metric("Cenário mais provável", f"{probs[principal] * 100:.0f}%",
              help=f"Probabilidade de {copom.descrever_movimento(principal)} (leitura por interpolação linear).")
    c3.caption(copom.descrever_movimento(principal))
else:
    c1.metric("Selic implícita", "—")
    c2.metric("Copom", "—", help="O calendário do Copom não cobre esta data. Atualize os dados do BCB.")
for coluna, v in [(c4, "1A"), (c5, "5A")]:
    coluna.metric(f"Taxa {v}", pct(a.taxas[v].iloc[-1]),
                  delta=bps(delta_dia.get(v, float("nan"))) + " no dia", delta_color="off")

aba_curva, aba_mov, aba_rv, aba_sobre = st.tabs(["Curva e Copom", "Movimentos da curva",
                                                 "Carry e valor relativo", "Metodologia"])

# ---------------------------------------------------------------------------
# Aba 1: curva e Copom
# ---------------------------------------------------------------------------
with aba_curva:
    anos = st.slider("Prazo máximo exibido (anos)", 1, 15, 10, key="anos_curva")
    mostrar(graficos.grafico_curva(a.curva, curva_comp, tema=TEMA, anos_max=anos))

    if a.caminho is not None and not a.caminho.empty:
        st.subheader("O que a curva precifica para o Copom")
        n = st.slider("Reuniões exibidas", 3, len(a.caminho), min(8, len(a.caminho)), key="n_reunioes")
        col_a, col_b = st.columns(2)
        with col_a:
            mostrar(graficos.grafico_copom_variacoes(a.caminho, tema=TEMA, n=n))
        with col_b:
            mostrar(graficos.grafico_copom_caminho(a.caminho, a.focus_do_dia, tema=TEMA, n=n))

        tabela = a.caminho.head(n).copy()
        tabela.attrs = {}
        tabela["probabilidades"] = [
            " · ".join(f"{p * 100:.0f}% {copom.descrever_movimento(k)}"
                       for k, p in sorted(copom.probabilidades_movimento(v).items(), key=lambda x: -x[1])
                       if p >= 0.01)
            for v in tabela["variacao_bps"]]
        if a.focus_do_dia is not None:
            tabela = tabela.merge(a.focus_do_dia[["reuniao", "mediana"]], on="reuniao", how="left")
            tabela["curva − Focus (bps)"] = (tabela["selic_implicita"] - tabela["mediana"]) * 1e4
            tabela["Focus (mediana)"] = tabela["mediana"] * 100
        tabela["Selic implícita (%)"] = tabela["selic_implicita"] * 100
        colunas = ["reuniao", "data_decisao", "variacao_bps", "acumulado_bps", "Selic implícita (%)",
                   "probabilidades", "contrato", "agrupada"]
        if "Focus (mediana)" in tabela:
            colunas[5:5] = ["Focus (mediana)", "curva − Focus (bps)"]
        st.dataframe(
            tabela[colunas], hide_index=True,
            column_config={
                "reuniao": "Reunião", "data_decisao": st.column_config.DateColumn("Decisão", format="DD/MM/YYYY"),
                "variacao_bps": st.column_config.NumberColumn("Variação (bps)", format="%+.1f"),
                "acumulado_bps": st.column_config.NumberColumn("Acumulado (bps)", format="%+.1f"),
                "Selic implícita (%)": st.column_config.NumberColumn(format="%.2f"),
                "Focus (mediana)": st.column_config.NumberColumn("Focus (%)", format="%.2f"),
                "curva − Focus (bps)": st.column_config.NumberColumn(format="%+.0f"),
                "probabilidades": "Probabilidades (aprox.)", "contrato": "Contrato usado",
                "agrupada": st.column_config.CheckboxColumn("Agrupada?", help=(
                    "Sem contrato para isolar a reunião: a taxa foi estimada junto com a reunião seguinte.")),
            })
        if a.focus_do_dia is None:
            st.caption("Focus indisponível: rode `python scripts/atualizar_dados.py` com internet para comparar "
                       "a curva com a mediana dos economistas.")
        st.caption(f"CDI vigente estimado a partir de: {a.caminho.attrs['fonte_cdi_atual']}.")

        with st.expander("Histórico: o que estava precificado vs. o que o Copom decidiu"):
            hist_impl, surpresas = historico_copom(a.historico, a.reunioes, a.selic_cdi, versao)
            if not surpresas.empty:
                mostrar(graficos.grafico_surpresas(surpresas, tema=TEMA))
                st.dataframe(arred(surpresas), hide_index=True,
                             column_config={"data_decisao": st.column_config.DateColumn(format="DD/MM/YYYY")})
                opcoes = list(a.caminho["reuniao"].head(8))
                reuniao = st.selectbox("Evolução da precificação até a reunião", opcoes)
                mostrar(graficos.grafico_precificacao_reuniao(hist_impl, reuniao, tema=TEMA))

    with st.expander("Taxas a termo e tabela de vencimentos"):
        mostrar(graficos.grafico_forwards(a.curva, tema=TEMA))
        v = a.curva.vertices.copy()
        comp = curva_comp.vertices.set_index("codigo")["taxa"]
        v["variação (bps)"] = (v["taxa"] - v["codigo"].map(comp)) * 1e4
        v["taxa (%)"] = v["taxa"] * 100
        st.dataframe(v[["codigo", "vencimento", "du", "taxa (%)", "variação (bps)", "pu", "contratos_abertos",
                        "liquido"]], hide_index=True,
                     column_config={"vencimento": st.column_config.DateColumn(format="DD/MM/YYYY"),
                                    "taxa (%)": st.column_config.NumberColumn(format="%.3f"),
                                    "variação (bps)": st.column_config.NumberColumn(format="%+.1f"),
                                    "pu": st.column_config.NumberColumn("PU", format="%.2f"),
                                    "contratos_abertos": st.column_config.NumberColumn("Contratos em aberto",
                                                                                       format="%d")})

# ---------------------------------------------------------------------------
# Aba 2: movimentos
# ---------------------------------------------------------------------------
with aba_mov:
    st.markdown(comentario.comentario_do_dia(a.taxas, a.data, a.caminho, a.caminho_anterior))
    col_a, col_b = st.columns([1, 1])
    with col_a:
        mostrar(graficos.grafico_variacao_dia(delta_dia, a.data, tema=TEMA))
    with col_b:
        periodo = st.segmented_control("Período", ["1 ano", "3 anos", "Tudo"], default="3 anos", key="periodo_hist")
        desde = {"1 ano": a.data - pd.DateOffset(years=1), "3 anos": a.data - pd.DateOffset(years=3),
                 "Tudo": None}[periodo or "3 anos"]
        mostrar(graficos.grafico_historico_vertices(a.taxas, tema=TEMA, desde=desde))

    st.subheader("Decomposição em fatores (PCA)")
    janela_pca = st.segmented_control("Janela da PCA", ["1 ano", "3 anos", "Tudo"], default="Tudo", key="janela_pca")
    janela = {"1 ano": 252, "3 anos": 756, "Tudo": None}[janela_pca or "Tudo"]
    pca = movimentos.pca_curva(a.variacoes, janela=janela)
    col_a, col_b = st.columns([3, 2])
    with col_a:
        mostrar(graficos.grafico_pca(pca, tema=TEMA))
    with col_b:
        st.dataframe(arred(pca.resumo(), 2), column_config={
            "variancia_explicada_%": "Variância explicada (%)", "acumulada_%": "Acumulada (%)",
            "desvio_diario_bps": "Desvio diário do fator"})
        fatores_hoje = pca.fatores.iloc[-1] / pca.desvio_fatores
        st.caption("Movimento de hoje em desvios-padrão de cada fator: " +
                   " · ".join(f"{k} {v:+.1f}σ".replace(".", ",") for k, v in fatores_hoje.items()))

    st.subheader("Regimes de movimento (1A vs. 5A)")
    tabela_regimes = movimentos.regimes(a.variacoes)
    col_a, col_b = st.columns([2, 3])
    with col_a:
        st.caption("Frequência nos últimos 12 meses")
        st.dataframe(arred(movimentos.frequencia_regimes(tabela_regimes)))
    with col_b:
        st.caption("Últimos 10 pregões")
        st.dataframe(arred(tabela_regimes.tail(10).iloc[::-1].reset_index()), hide_index=True,
                     column_config={"data": st.column_config.DateColumn("Data", format="DD/MM/YYYY")})
    with st.expander("O que cada regime costuma significar"):
        for nome, texto in movimentos.LEITURA_REGIME.items():
            st.markdown(f"- **{nome}**: {texto}.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Maiores movimentos do 5A")
        st.dataframe(movimentos.maiores_movimentos(a.variacoes, "5A", 10).reset_index(), hide_index=True,
                     column_config={"data": st.column_config.DateColumn("Data", format="DD/MM/YYYY")})
    with col_b:
        st.subheader("Reação da curva ao Copom")
        reacao = movimentos.reacao_copom(a.taxas, a.reunioes)
        if reacao.empty:
            st.caption("Sem reuniões no período dos dados.")
        else:
            st.dataframe(arred(reacao.iloc[::-1]), hide_index=True,
                         column_config={"reuniao": "Reunião",
                                        "data_decisao": st.column_config.DateColumn("Decisão", format="DD/MM/YYYY")})

# ---------------------------------------------------------------------------
# Aba 3: valor relativo
# ---------------------------------------------------------------------------
with aba_rv:
    horizonte = st.segmented_control("Horizonte", ["1 mês", "3 meses", "6 meses"], default="3 meses")
    h_du = {"1 mês": 21, "3 meses": 63, "6 meses": 126}[horizonte or "3 meses"]
    cr = valor_relativo.carry_roll(a.curva, horizonte_du=h_du, variacoes=a.variacoes,
                                   prazos={k: v for k, v in VERTICES_PADRAO.items() if v > h_du})
    col_a, col_b = st.columns([3, 2])
    with col_a:
        mostrar(graficos.grafico_carry(cr, tema=TEMA, horizonte=horizonte or "3 meses"))
    with col_b:
        st.dataframe(arred(cr, 2), column_config={
            "taxa_%": "Taxa (%)", "forward_%": "Forward (%)", "carry_bps": "Carry", "roll_down_bps": "Roll-down",
            "carry_roll_bps": "Carry + roll", "dv01_R$": "DV01 (R$/contrato)",
            "vol_horizonte_bps": "Vol no horizonte (bps)", "carry_roll/vol": "Carry+roll / vol"})
        st.caption("Positivo = favorável a quem **dá** taxa (aplicado em pré), com a curva parada.")

    st.subheader("Triagem de inclinações e butterflies")
    triagem = valor_relativo.triagem_valor_relativo(a.taxas, a.curva, horizonte_du=h_du)
    st.dataframe(arred(triagem, 2), column_config={
        "atual_bps": "Atual (bps)", "media_bps": "Média 12m", "desvio_bps": "Desvio 12m", "z_score": "Z-score",
        "percentil": "Percentil 12m", "sugestao": "Reversão à média sugere", "carry_roll_bps": "Carry+roll (bps)",
        "contratos_curto_por_longo": "Contratos curtos por longo (DV01 neutro)"})
    st.caption("Triagem estatística, não recomendação: spreads podem seguir esticados quando há motivo macro.")
    spread_escolhido = st.selectbox("Histórico do spread", list(movimentos.spreads(a.taxas).columns), index=2)
    mostrar(graficos.grafico_spread(movimentos.spreads(a.taxas)[spread_escolhido], spread_escolhido, tema=TEMA,
                                    desde=a.data - pd.DateOffset(years=3)))

# ---------------------------------------------------------------------------
# Aba 4: metodologia
# ---------------------------------------------------------------------------
with aba_sobre:
    metodologia = RAIZ / "docs" / "metodologia.md"
    st.markdown(metodologia.read_text(encoding="utf-8") if metodologia.exists() else "Veja o README.")
