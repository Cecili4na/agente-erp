"""Perguntas de avaliação com a resposta certa calculada em Python, sem SQL.

O gabarito não usa SQL de propósito: se usasse, um erro de SQL meu poderia concordar com o mesmo
erro do agente. Aqui os dados são lidos crus e as regras de negócio aplicadas à mão.

Cada pergunta tem uma "armadilha" anotada: o erro que um agente desatento cometeria.
"""

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class Pergunta:
    id: str
    texto: str
    resposta: float | str
    tipo: str  # "valor" (reais), "numero" (contagem) ou "nome"
    armadilha: str


def _carregar(banco: Path):
    con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    cab = con.execute("SELECT ID_MOV, DT_MOV, ID_CLI, ID_VDR, TP_MOV, ST_MOV, VL_BRU, VL_DSC, VL_TOT FROM TB_MOV_CAB").fetchall()
    ite = con.execute("SELECT ID_MOV, ID_PRD, QT_ITE FROM TB_MOV_ITE").fetchall()
    prd = dict(con.execute("SELECT ID_PRD, DS_PRD FROM TB_CAD_PRD"))
    prd_grp = dict(con.execute("SELECT ID_PRD, ID_GRP FROM TB_CAD_PRD"))
    grp = dict(con.execute("SELECT ID_GRP, DS_GRP FROM TB_CAD_GRP"))
    vdr = dict(con.execute("SELECT ID_VDR, NM_VDR FROM TB_CAD_VDR"))
    cid = dict(con.execute("SELECT ID_CLI, DS_CID FROM TB_CAD_CLI"))
    con.close()
    return cab, ite, prd, prd_grp, grp, vdr, cid


def perguntas(banco: Path) -> list[Pergunta]:
    cab, ite, prd, prd_grp, grp, vdr, cid = _carregar(banco)
    vendas = [c for c in cab if c[4] == 1 and c[5] != "C"]  # venda válida: tipo 1, não cancelada
    ids_vendas = {c[0] for c in vendas}
    mes = lambda c: c[1][4:6]
    soma = lambda linhas: round(sum(c[8] for c in linhas), 2)

    por_vendedor = defaultdict(float)
    por_cidade = defaultdict(float)
    por_mes = defaultdict(float)
    for c in vendas:
        por_vendedor[vdr[c[3]]] += c[8]
        por_cidade[cid[c[2]]] += c[8]
        por_mes[mes(c)] += c[8]
    qtd_produto, qtd_grupo = Counter(), Counter()
    for id_mov, id_prd, qt in ite:
        if id_mov in ids_vendas:
            qtd_produto[prd[id_prd]] += qt
            qtd_grupo[grp[prd_grp[id_prd]]] += qt
    pastilha = next(n for n in prd.values() if n.startswith("PASTILHA"))
    sabados = [c for c in vendas if date(int(c[1][:4]), int(mes(c)), int(c[1][6:])).weekday() == 5]

    return [
        Pergunta("p01", "Qual foi o faturamento total da loja em 2025?", soma(vendas), "valor",
                 "somar orçamentos, devoluções e canceladas junto"),
        Pergunta("p02", "Quanto a loja faturou em março de 2025?", soma([c for c in vendas if mes(c) == "03"]), "valor",
                 "filtrar o mês numa data guardada como texto"),
        Pergunta("p03", "Quantas vendas a loja fez em 2025?", len(vendas), "numero",
                 "contar orçamentos e canceladas como venda"),
        Pergunta("p04", "Qual foi o ticket médio das vendas em 2025?", round(soma(vendas) / len(vendas), 2), "valor",
                 "fazer a média por fora, sem SQL, ou incluir canceladas"),
        Pergunta("p05", "Quantos orçamentos estão em aberto?", sum(c[4] == 2 and c[5] == "A" for c in cab), "numero",
                 "não saber que orçamento mora na tabela de movimentos"),
        Pergunta("p06", "Qual o valor total dos orçamentos em aberto?", soma([c for c in cab if c[4] == 2 and c[5] == "A"]),
                 "valor", "usar o valor bruto"),
        Pergunta("p07", "Quantas vendas foram canceladas em 2025?", sum(c[4] == 1 and c[5] == "C" for c in cab), "numero",
                 "contar orçamentos e devoluções canceladas junto"),
        Pergunta("p08", "Qual vendedor mais faturou em 2025?", max(por_vendedor, key=por_vendedor.get), "nome",
                 "ranquear incluindo orçamentos"),
        Pergunta("p09", "Quanto a vendedora Patrícia faturou em 2025?", round(por_vendedor["PATRÍCIA"], 2), "valor",
                 "nome em maiúsculas e com acento no banco"),
        Pergunta("p10", "Qual categoria de produto vendeu mais unidades em 2025?", max(qtd_grupo, key=qtd_grupo.get),
                 "nome", "juntar três tabelas sem chave estrangeira declarada"),
        Pergunta("p11", "Qual produto vendeu mais unidades em 2025?", max(qtd_produto, key=qtd_produto.get), "nome",
                 "contar itens de orçamentos"),
        Pergunta("p12", "Quantas unidades de pastilha de freio dianteira foram vendidas em 2025?",
                 qtd_produto[pastilha], "numero", "buscar o produto pelo nome exato"),
        Pergunta("p13", "Quanto a loja deu de desconto nas vendas de 2025?", round(sum(c[7] for c in vendas), 2), "valor",
                 "incluir descontos de orçamentos"),
        Pergunta("p14", "Qual foi o mês de maior faturamento em 2025?", max(por_mes, key=por_mes.get), "nome",
                 "responder o nome do mês sem conferir"),
        Pergunta("p15", "Quantos clientes diferentes compraram em 2025?", len({c[2] for c in vendas}), "numero",
                 "contar quem só pediu orçamento"),
        Pergunta("p16", "Qual cidade gerou mais faturamento em 2025?", max(por_cidade, key=por_cidade.get), "nome",
                 "juntar com o cadastro de clientes"),
        Pergunta("p17", "Qual o valor total das devoluções em 2025?",
                 soma([c for c in cab if c[4] == 3 and c[5] != "C"]), "valor", "não saber que devolução é TP_MOV = 3"),
        Pergunta("p18", "Quanto a loja faturou no primeiro trimestre de 2025?",
                 soma([c for c in vendas if mes(c) in {"01", "02", "03"}]), "valor", "intervalo de datas em texto"),
        Pergunta("p19", "Qual foi o valor da maior venda de 2025?", max(c[8] for c in vendas), "valor",
                 "pegar um orçamento grande"),
        Pergunta("p20", "Quanto o faturamento de dezembro de 2025 superou o de novembro de 2025?",
                 round(por_mes["12"] - por_mes["11"], 2), "valor", "fazer a subtração de cabeça"),
        Pergunta("p21", "Quantas vendas foram feitas aos sábados em 2025?", len(sabados), "numero",
                 "converter data em texto para dia da semana"),
        Pergunta("p22", "Quantos produtos ativos a loja tem cadastrados?", len(prd), "numero", "nenhuma: controle fácil"),
    ]


def conferir(p: Pergunta, resposta: str) -> bool:
    """A resposta do agente acerta o gabarito? Valores com tolerância de 1 centavo."""
    from agente_erp.conferencia import numeros_do_texto

    if p.tipo == "nome":
        alvo = str(p.resposta)
        meses = {"01": "janeiro", "02": "fevereiro", "03": "março", "04": "abril", "05": "maio", "06": "junho",
                 "07": "julho", "08": "agosto", "09": "setembro", "10": "outubro", "11": "novembro", "12": "dezembro"}
        alvo = meses.get(alvo, alvo)
        return alvo.lower() in resposta.lower()
    tolerancia = 0.011 if p.tipo == "valor" else 0.0
    return any(abs(n - float(p.resposta)) <= tolerancia for n in numeros_do_texto(resposta))
