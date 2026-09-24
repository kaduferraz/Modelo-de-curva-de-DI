# Metodologia

Este documento explica, passo a passo, cada cálculo do projeto. As convenções valem para todo o código: taxas em decimal ao ano na base 252 dias úteis, variações em pontos-base (1 bp = 0,01 p.p.) e dias úteis contados como a B3 conta, com o dia inicial incluído e o dia do vencimento excluído.

## 1. O contrato DI1

O DI1 é o contrato futuro de taxa média de DI de um dia da B3. No vencimento, que cai no primeiro dia útil do mês indicado pelo código (F = jan, G = fev, …, Z = dez), o contrato vale R$ 100.000. Antes disso, ele é negociado em taxa, e a taxa é convertida em preço (PU):

$$PU = \frac{100.000}{(1 + taxa)^{du/252}}$$

Todo dia, a posição é ajustada pela diferença entre o PU de ajuste e o PU do dia anterior corrigido pelo CDI. Por isso, quem **toma taxa** (vendido em PU) ganha se a taxa subir mais do que o CDI embutido, e quem **dá taxa** (comprado em PU) ganha se ela cair.

A sensibilidade do contrato a 1 bp de taxa é o **DV01**:

$$DV01 = PU \cdot \frac{du/252}{1 + taxa} \cdot 0{,}0001$$

**Validação.** Com o calendário do projeto, a taxa recalculada a partir do PU de ajuste bate com a taxa publicada pela B3 (arredondada em 3 casas) em 99,99% dos contratos com mais de 5 dias úteis, de 2018 a 2026. As poucas diferenças aparecem em contratos a 1 ou 2 dias do vencimento, em que o arredondamento do PU domina a conta.

## 2. Calendário de dias úteis

Os feriados nacionais são gerados por regra: datas fixas mais Carnaval, Sexta-feira Santa e Corpus Christi, calculados a partir da Páscoa. O 20 de novembro virou feriado nacional pela Lei 14.759/2023, e a ANBIMA e a B3 passaram a considerá-lo a partir de 26/12/2023. Contagens com data de referência anterior usam o calendário antigo, e isso reproduz exatamente as taxas históricas da B3.

## 3. A curva: interpolação flat forward

Cada contrato é um vértice da curva. Entre dois vértices, o padrão brasileiro é o **flat forward**, que supõe taxa a termo constante entre eles. Na prática, o logaritmo do fator de capitalização é interpolado linearmente em dias úteis:

$$\ln F(du) = \frac{du}{252}\ln(1 + y(du)) \quad \text{é linear entre os vértices}$$

A **taxa a termo** entre dois prazos sai da razão dos fatores:

$$(1 + f_{1,2})^{(du_2 - du_1)/252} = \frac{(1 + y_2)^{du_2/252}}{(1 + y_1)^{du_1/252}}$$

Contratos com menos de 100 mil contratos em aberto aparecem nos gráficos como "pouco negociados". O ajuste deles é definido pela B3 a partir da curva, e não por negociação relevante.

## 4. Selic implícita por reunião do Copom

O CDI só muda quando a Selic muda, e a nova taxa vale a partir do dia útil seguinte à decisão, porque o comunicado sai depois do fechamento do mercado. Chamando de $r_0$ o CDI vigente e de $r_i$ o CDI depois da reunião $i$, cada contrato com vencimento $T$ satisfaz:

$$\ln F(T) = \sum_i \frac{n_i(T)}{252}\ln(1 + r_i)$$

Aqui, $n_i(T)$ é o número de dias úteis do intervalo entre as reuniões $i$ e $i+1$ que caem antes de $T$. O cálculo segue quatro passos:

1. **CDI vigente ($r_0$):** vem do contrato que vence mais tarde antes da próxima reunião, porque ele embute só o CDI atual. Se nenhum contrato vence antes, o projeto usa a série do CDI do BCB ou o último valor identificado desde a reunião anterior.
2. **Bootstrap:** para cada intervalo entre reuniões, usa o contrato que vence mais tarde dentro dele e resolve $r_i$, porque os $r_j$ anteriores já são conhecidos.
3. **Reuniões agrupadas:** se o único contrato do intervalo vence poucos dias depois da reunião, um erro de 1 bp no ajuste vira um erro enorme em $r_i$. O fator de amplificação é $du_T / \text{dias de exposição}$. Quando ele passa de 8, a reunião é estimada junto com a seguinte, com a mesma taxa para as duas, e a tabela marca `agrupada = True`.
4. **Selic implícita:** é o CDI implícito mais o spread Selic–CDI de 0,10 p.p. A variação entre reuniões consecutivas é o movimento precificado.

**Probabilidades.** Com o Copom se movendo em passos de 25 bps, uma variação implícita de −18 bps equivale a cerca de 72% de chance de corte de 25 bps e 28% de manutenção, por interpolação linear entre os dois passos vizinhos. É uma leitura aproximada, porque ignora o prêmio de risco embutido na curva.

**Validação.** Em cada reunião de 2024 a setembro de 2026, a mudança do CDI lida na curva no pregão seguinte coincide com a decisão anunciada, com desvio de até cerca de 1,5 bp, usando só dados da B3. A diferença média entre o que estava precificado na véspera e o que foi decidido foi de cerca de 3 bps.

## 5. Movimentos da curva

**Prazo constante.** Os contratos têm vencimento fixo e "envelhecem" a cada dia. Para comparar dias diferentes, a curva de cada dia é interpolada nos prazos fixos de 3M, 6M, 1A, 2A, 3A, 5A e 10A (63 a 2.520 dias úteis).

**PCA.** A análise de componentes principais é feita sobre a matriz de covariância das variações diárias em bps, sem padronizar os vértices. Os três primeiros fatores têm leitura econômica:

| Fator | O que faz | Participação típica na variância |
|---|---|---|
| Nível | desloca a curva inteira | ~90% |
| Inclinação | gira a curva: curto e longo em direções opostas | ~7% |
| Curvatura | move a barriga em relação às pontas | ~2% |

**Regimes.** Cada dia é classificado pela variação do 1A e do 5A. Variações abaixo de 1 bp contam como zero.

| Regime | Definição | Leitura típica |
|---|---|---|
| Bear steepening | taxas sobem, longo sobe mais | prêmio de risco (fiscal, inflação longa) |
| Bear flattening | taxas sobem, curto sobe mais | mercado precifica mais aperto monetário |
| Bull steepening | taxas caem, curto cai mais | mercado antecipa cortes |
| Bull flattening | taxas caem, longo cai mais | alívio de prêmio, demanda por duration |
| Twist | curto e longo em direções opostas | mudança de inclinação sem mudança de nível |

**Z-score e percentil.** Os dois medem o valor atual de um spread contra a média e o desvio dos últimos 252 pregões.

**Reação ao Copom.** É a variação de cada vértice entre o fechamento do dia da decisão e o fechamento do pregão seguinte.

## 6. Carry, roll-down e valor relativo

As definições abaixo valem para quem dá taxa no prazo $m$, com horizonte $h$ e supondo a curva parada:

- **Carry:** $f(h, m) - y(m)$, ou seja, quanto a taxa a termo que começa em $h$ está acima da taxa spot.
- **Roll-down:** $y(m) - y(m-h)$, ou seja, o contrato passa a ser precificado por um ponto mais curto da curva.
- **Carry + roll:** $f(h, m) - y(m-h)$, que é quanto a taxa pode subir até o horizonte antes de a posição dada perder dinheiro.

**Spreads.** A inclinação $a$–$b$ é $y(b) - y(a)$. O butterfly $a/b/c$ é $2y(b) - y(a) - y(c)$, e um valor positivo indica barriga "barata". A triagem sugere a posição de reversão à média quando $|z| \geq 1$ e informa o carry + roll dessa posição e a razão de contratos que neutraliza o DV01.

Tudo isso é triagem estatística, não recomendação de investimento.

## 7. Limitações conhecidas

- **Spread Selic–CDI:** o projeto supõe 0,10 p.p. fixo. Na prática, o spread varia alguns centésimos.
- **Prêmio de risco:** a Selic implícita inclui prêmio de risco e de liquidez, então não é uma expectativa "pura" do mercado.
- **Vencimentos pouco negociados:** o ajuste desses contratos segue um modelo da B3. Por isso, a precificação reunião a reunião fica menos confiável além de cerca de 12 meses, enquanto o acumulado continua robusto.
- **Pregões sem boletim:** feriados municipais de São Paulo antes de 2022 e os últimos dias úteis do ano ficam sem boletim. O atualizador simplesmente pula essas datas.
