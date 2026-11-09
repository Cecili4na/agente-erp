"""Roda o agente nas 22 perguntas, nos dois modos, e compara com o gabarito.

Por modo, mede:
- acerto: a resposta contém o valor ou o nome certo;
- acerto entre as confiáveis: o quanto dá para confiar numa resposta que passou na conferência;
- respostas confiáveis: passaram na conferência de números;
- consultas por pergunta e tokens: custo;
- consultas recusadas pelos guardrails.

A pergunta que interessa: quanto a documentação de negócio (`NOTAS`) muda o acerto, e se a
conferência de números separa as respostas certas das erradas.

Uso: python -m agente_erp.avaliar [cego|com_notas]
"""

import json
import sys
from pathlib import Path

from agente_erp.agente import executar
from agente_erp.erp import BANCO, gerar
from agente_erp.gabarito import conferir, perguntas
from agente_erp.llm import do_ambiente

RAIZ = Path(__file__).resolve().parents[2]
RESULTADOS = RAIZ / "resultados"


def avaliar_modo(modo: str) -> dict:
    if not BANCO.exists():
        gerar()
    modelo = do_ambiente()
    linhas = []
    for p in perguntas(BANCO):
        e = executar(p.texto, modelo, BANCO, modo)
        certo = conferir(p, e.resposta)
        linhas.append({
            "id": p.id, "pergunta": p.texto, "gabarito": p.resposta, "armadilha": p.armadilha,
            "resposta": e.resposta, "certo": certo, "confiavel": e.confiavel, "passos": e.passos,
            "consultas": e.consultas, "recusadas": e.recusadas,
            "sql": [c.entrada.get("sql") for c in e.chamadas if c.ferramenta == "consultar"],
        })
        print(f"{p.id} {'certo' if certo else 'ERRO '} {'' if e.confiavel else '(não confiável)'} {e.resposta[:80]}",
              flush=True)

    n = len(linhas)
    confiaveis = [x for x in linhas if x["confiavel"]]
    resumo = {
        "modelo": modelo.nome,
        "modo": modo,
        "acerto": round(sum(x["certo"] for x in linhas) / n, 3),
        "respostas_confiaveis": round(len(confiaveis) / n, 3),
        "acerto_entre_confiaveis": round(sum(x["certo"] for x in confiaveis) / max(len(confiaveis), 1), 3),
        "consultas_por_pergunta": round(sum(x["consultas"] for x in linhas) / n, 1),
        "consultas_recusadas": sum(x["recusadas"] for x in linhas),
        "tokens_entrada": modelo.uso.entrada,
        "tokens_saida": modelo.uso.saida,
    }
    RESULTADOS.mkdir(exist_ok=True)
    nome = f"{modelo.nome.replace('/', '_').replace(':', '_')}_{modo}"
    (RESULTADOS / f"{nome}.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in linhas) + "\n")
    (RESULTADOS / f"{nome}_resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2))
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return resumo


def main() -> None:
    for modo in sys.argv[1:] or ["cego", "com_notas"]:
        avaliar_modo(modo)


if __name__ == "__main__":
    main()
