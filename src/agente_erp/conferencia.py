"""Conferência dos números da resposta final.

Todo número que o agente afirma tem que ter aparecido no resultado de alguma consulta, ou na
própria pergunta (um ano, um mês). Isso impede o modelo de fazer conta de cabeça ou de inventar um
valor plausível. Se ele precisa de uma diferença ou de uma média, tem que pedir ao SQL.

Os números são comparados como valores, não como texto: "R$ 1.486.422,70" na resposta casa com
1486422.7 no resultado da consulta. Arredondamento para duas casas é tolerado.
"""

import json
import re

# 1.486.422,70 · 1486422,70 · 1486422.70 · 42 · 3,5
NUMERO_PTBR = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?|\d+\.\d+)(?![\w])")


def para_float(texto: str) -> float:
    if "," in texto:
        return float(texto.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", texto):  # 1.486 sem vírgula é milhar em pt-BR
        return float(texto.replace(".", ""))
    return float(texto)


def numeros_do_texto(texto: str) -> list[float]:
    return [para_float(m) for m in NUMERO_PTBR.findall(texto)]


def numeros_das_saidas(saidas: list[str]) -> set[float]:
    """Todos os números que aparecem nos resultados das consultas, em qualquer nível do JSON."""
    vistos: set[float] = set()

    def visitar(valor):
        if isinstance(valor, bool):
            return
        if isinstance(valor, (int, float)):
            vistos.add(float(valor))
        elif isinstance(valor, str):
            vistos.update(numeros_do_texto(valor))
        elif isinstance(valor, (list, tuple)):
            for v in valor:
                visitar(v)
        elif isinstance(valor, dict):
            for v in valor.values():
                visitar(v)

    for saida in saidas:
        try:
            visitar(json.loads(saida))
        except json.JSONDecodeError:
            continue
    return vistos


def sem_lastro(resposta: str, saidas: list[str], pergunta: str) -> list[float]:
    """Números da resposta que não vieram nem das consultas nem da pergunta."""
    disponiveis = numeros_das_saidas(saidas) | set(numeros_do_texto(pergunta))
    return [
        n for n in numeros_do_texto(resposta)
        if not any(abs(n - d) <= 0.005 or abs(n - round(d, 2)) <= 0.005 for d in disponiveis)
    ]
