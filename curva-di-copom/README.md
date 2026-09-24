# Curva DI e Selic implícita por reunião do Copom

Ferramenta em Python que monta a **curva de juros prefixada brasileira** a partir dos contratos DI1 da B3, extrai **quanto de corte ou alta da Selic o mercado precifica em cada reunião do Copom** e analisa **como e por que a curva se move**: PCA, regimes bull/bear e steepening/flattening, z-scores, carry e roll-down.

Tudo roda com dados públicos e gratuitos (B3 e Banco Central). O projeto inclui um **dashboard interativo**, um **notebook-guia** que explica cada conta e **testes automatizados**.

> **English summary.** Python toolkit for the Brazilian rates market. It builds the DI futures curve (flat-forward interpolation, business-day calendar reproducing 99.99% of B3 settlement rates), bootstraps the **meeting-by-meeting Selic path implied by the curve**, compares it with the BCB Focus survey, and analyzes curve dynamics (PCA of level/slope/curvature, bull/bear steepening/flattening regimes, z-scores, carry & roll-down, slope and butterfly screening). It ships with a Streamlit dashboard, a guided Jupyter notebook and a pytest suite.

![Curva DI](docs/img/curva.png)

## O que o projeto responde

| Pergunta | Onde |
|---|---|
| Como está a curva hoje, vértice a vértice, e quanto ela andou? | `curva.py` · aba *Curva e Copom* |
| Quanto de corte ou alta está precificado em cada reunião do Copom? Com que probabilidade? | `copom.py` |
| O mercado está mais otimista ou mais pessimista que os economistas (Focus)? | `copom.py` + `dados.py` |
| O movimento de hoje foi de nível, de inclinação ou de curvatura? É grande para o histórico? | `movimentos.py` · aba *Movimentos* |
| Onde está o melhor carry + roll? Algum spread está esticado? | `valor_relativo.py` · aba *Carry e valor relativo* |

![Selic implícita por reunião](docs/img/copom.png)

## Destaques e validação

- **Calendário exato.** Os feriados são gerados por regra, incluindo a mudança do 20 de novembro em 2023. A taxa recalculada a partir do PU bate com a taxa de ajuste publicada pela B3 em **99,99%** dos contratos desde 2018 (vencimentos com 5+ dias úteis).
- **Selic implícita validada com o próprio histórico.** Em todas as reuniões de 2024 a setembro de 2026, a mudança do CDI lida na curva no pregão seguinte coincide com a decisão anunciada, com desvio de até ~1,5 bp, usando só dados da B3. A diferença média entre o que estava precificado na véspera e o que foi decidido foi de ~3 bps.
- **Proteção contra ruído.** Vencimentos que dariam só alguns dias de exposição a uma reunião amplificariam erros de ajuste em dezenas de bps. Nesses casos, a reunião é estimada junto com a seguinte e marcada como tal.
- **PCA com leitura econômica.** Nível, inclinação e curvatura explicam cerca de 90%, 7% e 2% dos movimentos diários da curva.

![O que a curva precificava vs. o que o Copom decidiu](docs/img/surpresas.png)

## Como usar

**1. Instalar** (Python 3.10+):

```bash
git clone https://github.com/<seu-usuario>/curva-di-copom.git
cd curva-di-copom
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Baixar os dados.** A primeira execução leva cerca de 1 minuto. Depois, cada atualização baixa só os pregões novos:

```bash
python scripts/atualizar_dados.py
```

**3. Explorar:**

```bash
jupyter lab notebooks/guia_do_projeto.ipynb    # guia completo, com explicações e gráficos
streamlit run app/dashboard.py                  # dashboard interativo
python scripts/gerar_figuras.py                 # atualiza as figuras deste README
pytest                                          # testes
```

**4. Usar como biblioteca:**

```python
from curva_di import CurvaDI, carregar_historico_di1, carregar_reunioes_copom, selic_implicita

historico = carregar_historico_di1()
curva = CurvaDI.do_historico(historico)            # último pregão
curva.taxa(252), curva.forward(252, 504)           # taxa de 1 ano e forward 1A→2A

caminho = selic_implicita(curva, carregar_reunioes_copom())
caminho[["reuniao", "variacao_bps", "selic_implicita"]]
```

## Estrutura do repositório

```
curva-di-copom/
├── src/curva_di/
│   ├── calendario.py      # feriados, dias úteis (padrão B3/ANBIMA), vencimentos do DI1
│   ├── dados.py           # coleta: boletim da B3, espelho histórico, BCB (SGS e Focus); cache em data/
│   ├── curva.py           # PU, taxa, DV01, forwards, flat forward, CurvaDI, vértices de prazo constante
│   ├── copom.py           # calendário do Copom, Selic implícita por reunião, probabilidades, surpresas
│   ├── movimentos.py      # variações, spreads, PCA, regimes, maiores movimentos, reação ao Copom
│   ├── valor_relativo.py  # carry, roll-down e triagem de inclinações e butterflies
│   ├── comentario.py      # comentário de mercado automático
│   ├── graficos.py        # gráficos Plotly (paleta validada para daltonismo)
│   ├── analise.py         # junta tudo para uma data (dashboard e figuras)
│   └── config.py          # caminhos, fontes e parâmetros
├── app/dashboard.py       # dashboard Streamlit
├── notebooks/guia_do_projeto.ipynb
├── scripts/               # atualizar_dados.py e gerar_figuras.py
├── tests/                 # pytest (rodam no GitHub Actions a cada push)
├── .github/workflows/     # integração contínua
├── docs/metodologia.md    # todas as fórmulas, passo a passo
└── data/                  # dados baixados (fora do git)
```

## Metodologia (resumo)

1. **Curva:** cada vencimento do DI1 é um vértice, e a curva é interpolada por flat forward, com taxa a termo constante entre vértices.
2. **Selic por reunião:** como o CDI só muda nas decisões do Copom, cada contrato é uma média ponderada dos CDIs entre reuniões. O projeto faz um bootstrap reunião a reunião e soma 0,10 p.p. (spread Selic–CDI) para chegar à Selic implícita.
3. **Movimentos:** a curva de cada dia é interpolada em prazos fixos (3M a 10A). Sobre as variações diárias, o projeto roda PCA e classifica cada dia em um regime pelo 1A e pelo 5A.
4. **Carry e roll-down:** mostram, para quem dá taxa com a curva parada, a forward menos a spot (carry) e o ganho de "descer" a curva (roll-down).

Detalhes e fórmulas em [`docs/metodologia.md`](docs/metodologia.md).

![PCA](docs/img/pca.png)

## Fontes de dados

| Fonte | Conteúdo |
|---|---|
| [B3 — boletim de preços](https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/boletim-diario/boletim-diario-do-mercado/) | Ajustes diários de todos os vencimentos do DI1 |
| [pyield-data](https://github.com/crdcj/pyield-data) | Espelho do histórico dos boletins da B3 desde 2018, usado só na carga inicial |
| [BCB — SGS](https://dadosabertos.bcb.gov.br/dataset/432-taxa-de-juros---meta-selic-definida-pelo-copom) | Meta Selic (432) e CDI (4389) |
| [BCB — Focus](https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/aplicacao) | Expectativa de Selic por reunião do Copom |
| [BCB — Copom](https://www.bcb.gov.br/publicacoes/atascopom) | Datas das reuniões (atas e agenda) |

As partes do BCB são opcionais: a curva, a Selic implícita e toda a análise de movimentos funcionam só com os dados da B3.

## Limitações e próximos passos

- A Selic implícita inclui **prêmio de risco**, então não é uma expectativa "pura". O spread Selic–CDI é tratado como fixo em 0,10 p.p.
- Além de cerca de 12 meses, os vencimentos são pouco negociados e a leitura reunião a reunião perde precisão. O acumulado continua robusto.
- A triagem de valor relativo é estatística, não recomendação de investimento.
- **Próximos passos:** inflação implícita (NTN-B e DAP), backtest das regras de reversão à média e estudo de eventos para IPCA e anúncios fiscais.

## Autor

**Carlos Eduardo Ferraz**, estudante de Engenharia de Produção na Escola Politécnica da USP.

Licença MIT.
