"""Atualiza todos os dados do projeto (B3 e Banco Central) e salva em data/.

Uso:
    python scripts/atualizar_dados.py                # atualiza tudo até hoje
    python scripts/atualizar_dados.py --ate 2026-09-23
    python scripts/atualizar_dados.py --sem-espelho  # só boletins oficiais da B3
    python scripts/atualizar_dados.py --sem-bcb      # pula Selic, CDI, Focus e Copom

Os boletins da B3 costumam ser publicados no início da noite; rodando antes
disso, o dia corrente é simplesmente ignorado e entra na próxima execução.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from curva_di import copom, dados  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ate", help="Última data (AAAA-MM-DD). Padrão: hoje.")
    parser.add_argument("--sem-espelho", action="store_true", help="Não usa o espelho histórico.")
    parser.add_argument("--sem-bcb", action="store_true", help="Não baixa dados do Banco Central.")
    args = parser.parse_args()

    print("1/4  Curva DI (B3)")
    historico = dados.atualizar_historico_di1(ate=args.ate, usar_espelho=not args.sem_espelho)
    if historico.empty:
        print("     Nenhum dado do DI1 disponível. Verifique a conexão com a internet.")
        sys.exit(1)

    if args.sem_bcb:
        print("Dados do BCB ignorados (--sem-bcb).")
        return

    print("2/4  Calendário do Copom (BCB)")
    with warnings.catch_warnings(record=True) as avisos:
        warnings.simplefilter("always")
        reunioes = copom.carregar_reunioes_copom(atualizar=True)
    fonte = reunioes["fonte"].iloc[0] if not reunioes.empty else "-"
    print(f"     {len(reunioes)} reuniões ({'embutido' if avisos else fonte}), "
          f"até {reunioes['data_decisao'].max():%d/%m/%Y}.")

    print("3/4  Meta Selic e CDI (BCB/SGS)")
    selic_cdi = dados.carregar_selic_cdi(atualizar=True)
    if selic_cdi is not None:
        ultimo = selic_cdi.dropna().iloc[-1]
        print(f"     Meta Selic {ultimo['meta_selic'] * 100:.2f}% · CDI {ultimo['cdi'] * 100:.2f}% "
              f"em {selic_cdi.dropna().index[-1]:%d/%m/%Y}.")
    else:
        print("     Indisponível (as análises seguem usando só a curva DI).")

    print("4/4  Focus: Selic esperada por reunião (BCB)")
    focus = dados.carregar_focus_selic(atualizar=True)
    if focus is not None and not focus.empty:
        print(f"     Pesquisas de {focus['data'].min():%d/%m/%Y} a {focus['data'].max():%d/%m/%Y}.")
    else:
        print("     Indisponível (a comparação com o Focus fica de fora).")

    print("\nPronto. Próximos passos: abra notebooks/guia_do_projeto.ipynb ou rode `streamlit run app/dashboard.py`.")


if __name__ == "__main__":
    main()
