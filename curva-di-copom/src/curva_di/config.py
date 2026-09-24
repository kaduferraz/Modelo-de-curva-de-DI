"""Configurações centrais do projeto: caminhos, fontes de dados e parâmetros."""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
# src/curva_di/config.py -> parents[2] é a raiz do repositório
RAIZ_PROJETO = Path(__file__).resolve().parents[2]

# A pasta de dados pode ser trocada com a variável de ambiente CURVA_DI_DADOS
PASTA_DADOS = Path(os.environ.get("CURVA_DI_DADOS", RAIZ_PROJETO / "data"))
ARQUIVO_HISTORICO_DI1 = PASTA_DADOS / "di1_historico.parquet"
ARQUIVO_BCB = PASTA_DADOS / "bcb_series.parquet"
ARQUIVO_FOCUS = PASTA_DADOS / "focus_selic.parquet"
ARQUIVO_COPOM = PASTA_DADOS / "copom_reunioes.csv"
PASTA_FIGURAS = RAIZ_PROJETO / "docs" / "img"

# ---------------------------------------------------------------------------
# Fontes de dados (todas públicas e gratuitas)
# ---------------------------------------------------------------------------
# Boletim de preços simplificado da B3 (SPRD): um arquivo por pregão, com os
# ajustes de todos os derivativos. {data} no formato AAMMDD.
URL_B3_BOLETIM = "https://www.b3.com.br/pesquisapregao/download?filelist=SPRD{data}.zip"

# Espelho público do histórico de futuros da B3 (desde 2018), mantido pelo
# projeto open source PYield (github.com/crdcj/PYield). Usado só para montar o
# histórico inicial rapidamente; as atualizações diárias vêm direto da B3.
URL_ESPELHO_HISTORICO = (
    "https://github.com/crdcj/pyield-data/releases/latest/download/b3_futures.parquet"
)

# Banco Central: séries temporais (SGS), expectativas Focus e Copom
URL_BCB_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
URL_BCB_FOCUS_SELIC = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoSelic"
)
URL_BCB_COPOM_ATAS = "https://www.bcb.gov.br/api/servico/sitebcb/copom/atas"
URL_BCB_COPOM_AGENDA = (
    "https://www.bcb.gov.br/api/exportarics/sitebcb/agendaics"
    "?lista=Reuni%C3%B5es%20do%20Copom"
)

# Códigos SGS usados
SGS_META_SELIC = 432  # Meta Selic definida pelo Copom (% a.a.)
SGS_CDI_ANUAL = 4389  # CDI anualizado base 252 (% a.a.)

TIMEOUT_HTTP = 30  # segundos
CABECALHOS_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# Parâmetros de mercado
# ---------------------------------------------------------------------------
VALOR_FACE_DI1 = 100_000.0  # PU no vencimento
BASE_DU = 252

# Diferença típica entre a meta Selic e o CDI (a Selic over opera ~0,10 p.p.
# abaixo da meta e o CDI acompanha a over). Usada para converter CDI implícito
# em Selic implícita.
SPREAD_SELIC_CDI = 0.0010

# Contratos com pelo menos esse número de contratos em aberto são tratados
# como "líquidos" nos gráficos (os demais têm ajuste definido pela B3 a partir
# da curva, sem negociação relevante).
MIN_CONTRATOS_ABERTOS_LIQUIDO = 100_000

# Filtro de liquidez usado ao extrair a Selic implícita por reunião. O padrão
# (0) usa todos os vencimentos mensais: a B3 ajusta todos diariamente e, com a
# regra de amplificação máxima (copom.MAX_AMPLIFICACAO), o resultado é mais
# estável do que descartando vencimentos.
MIN_CONTRATOS_ABERTOS_COPOM = 0

# Vértices de prazo constante (em dias úteis) usados na análise de movimentos
VERTICES_PADRAO: dict[str, int] = {
    "3M": 63,
    "6M": 126,
    "1A": 252,
    "2A": 504,
    "3A": 756,
    "5A": 1260,
    "10A": 2520,
}

# Janela padrão (dias úteis) para z-scores e estatísticas "históricas"
JANELA_PADRAO = 252
