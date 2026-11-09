"""Linha de comando.

    agente-erp gerar-banco
    agente-erp perguntar "Quanto a loja faturou em março?" [--cego] [--mostrar-sql]
    agente-erp avaliar [cego|com_notas]
"""

import argparse
import sys

from agente_erp import avaliar
from agente_erp.erp import BANCO, gerar


def main() -> None:
    parser = argparse.ArgumentParser(prog="agente-erp")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("gerar-banco")
    p = sub.add_parser("perguntar")
    p.add_argument("pergunta")
    p.add_argument("--cego", action="store_true", help="sem as notas de negócio")
    p.add_argument("--mostrar-sql", action="store_true")
    a = sub.add_parser("avaliar")
    a.add_argument("modos", nargs="*", default=["cego", "com_notas"])
    args = parser.parse_args()

    if args.comando == "gerar-banco":
        print(gerar())
    elif args.comando == "perguntar":
        from agente_erp.agente import executar
        from agente_erp.llm import do_ambiente

        if not BANCO.exists():
            gerar()
        e = executar(args.pergunta, do_ambiente(), BANCO, "cego" if args.cego else "com_notas")
        if args.mostrar_sql:
            for c in e.chamadas:
                print(f"-- {c.ferramenta} {c.entrada}\n   {c.saida[:200]}\n")
        print(e.resposta if e.confiavel else f"(resposta não confiável: números sem lastro {e.sem_lastro})\n{e.resposta}")
    else:
        sys.argv = [sys.argv[0], *args.modos]
        avaliar.main()


if __name__ == "__main__":
    main()
