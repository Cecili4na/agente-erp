"""Gera o banco de um ERP de varejo com cara de sistema legado.

Nomes de tabela e coluna em siglas, sem chave estrangeira declarada, e armadilhas que existem em
sistemas reais e derrubam quem consulta sem entender o negócio:

1. Venda, orçamento e devolução moram na mesma tabela (TB_MOV_CAB.TP_MOV = 1, 2, 3).
   Somar tudo sem filtrar infla o faturamento.
2. Vendas canceladas continuam na tabela (ST_MOV = 'C').
3. VL_BRU é o valor antes do desconto; o que vale é VL_TOT.
4. TB_MOV_CAB_OLD é uma tabela morta, com o mesmo formato, de um sistema anterior.
5. Datas guardadas como texto 'AAAAMMDD', como em muitos sistemas antigos.

Os dados são determinísticos (semente fixa): quem rodar de novo obtém o mesmo banco.
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BANCO = RAIZ / "data" / "loja.db"
SEMENTE = 7

ESQUEMA = """
CREATE TABLE TB_CAD_GRP (ID_GRP INTEGER PRIMARY KEY, DS_GRP TEXT);
CREATE TABLE TB_CAD_PRD (ID_PRD INTEGER PRIMARY KEY, DS_PRD TEXT, ID_GRP INTEGER, VL_VDA REAL, VL_CUS REAL, FL_ATV TEXT);
CREATE TABLE TB_CAD_CLI (ID_CLI INTEGER PRIMARY KEY, NM_CLI TEXT, DS_CID TEXT, DT_CAD TEXT);
CREATE TABLE TB_CAD_VDR (ID_VDR INTEGER PRIMARY KEY, NM_VDR TEXT);
CREATE TABLE TB_MOV_CAB (
    ID_MOV INTEGER PRIMARY KEY, DT_MOV TEXT, ID_CLI INTEGER, ID_VDR INTEGER,
    TP_MOV INTEGER, ST_MOV TEXT, VL_BRU REAL, VL_DSC REAL, VL_TOT REAL
);
CREATE TABLE TB_MOV_ITE (ID_MOV INTEGER, NR_ITE INTEGER, ID_PRD INTEGER, QT_ITE REAL, VL_UNI REAL, VL_CUS REAL, VL_TOT REAL);
CREATE TABLE TB_MOV_CAB_OLD AS SELECT * FROM TB_MOV_CAB WHERE 0;
CREATE TABLE TB_PAR_SIS (CD_PAR TEXT, VL_PAR TEXT);
"""

GRUPOS = {
    "Freios": [("Pastilha de freio dianteira", 89.9), ("Disco de freio ventilado", 189.0), ("Fluido de freio DOT4 500ml", 32.5)],
    "Motor": [("Óleo 5W30 sintético 1L", 54.9), ("Filtro de óleo", 28.0), ("Vela de ignição", 39.9), ("Correia dentada", 129.0)],
    "Suspensão": [("Amortecedor dianteiro", 289.0), ("Bieleta", 64.9), ("Bandeja de suspensão", 219.0)],
    "Elétrica": [("Bateria 60Ah", 459.0), ("Lâmpada H4", 24.9), ("Alternador recondicionado", 690.0)],
    "Acessórios": [("Tapete de borracha", 79.9), ("Palheta limpador", 36.9), ("Capa de volante", 49.9)],
}
VENDEDORES = ["Marcos", "Patrícia", "Joana", "Ricardo"]
CIDADES = ["Campina Grande", "João Pessoa", "Patos", "Queimadas", "Lagoa Seca"]
NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gabriela", "Hugo", "Íris", "José", "Larissa", "Mateus"]
SOBRENOMES = ["Silva", "Souza", "Oliveira", "Lima", "Costa", "Almeida", "Ferreira", "Araújo"]


def _movimentos(cur, tabela: str, inicio: date, dias: int, primeiro_id: int, rng: random.Random, produtos, n_cli):
    id_mov = primeiro_id
    for d in range(dias):
        dia = inicio + timedelta(days=d)
        if dia.weekday() == 6:  # domingo fechado
            continue
        # sábado movimenta menos; dezembro movimenta mais
        base = 6 if dia.weekday() == 5 else 11
        base += 4 if dia.month == 12 else 0
        for _ in range(rng.randint(base - 3, base + 3)):
            tipo = rng.choices([1, 2, 3], weights=[70, 25, 5])[0]
            status = "C" if rng.random() < 0.06 else ("A" if tipo == 2 and rng.random() < 0.5 else "F")
            itens = rng.sample(produtos, k=rng.randint(1, 4))
            bruto, linhas = 0.0, []
            for n, (id_prd, preco, custo) in enumerate(itens, start=1):
                qtd = rng.choice([1, 1, 1, 2, 2, 4])
                total = round(qtd * preco, 2)
                bruto += total
                linhas.append((id_mov, n, id_prd, qtd, preco, custo, total))
            bruto = round(bruto, 2)
            desconto = round(bruto * rng.choice([0, 0, 0, 0.05, 0.10]), 2)
            cur.execute(
                f"INSERT INTO {tabela} VALUES (?,?,?,?,?,?,?,?,?)",
                (id_mov, dia.strftime("%Y%m%d"), rng.randint(1, n_cli), rng.randint(1, len(VENDEDORES)),
                 tipo, status, bruto, desconto, round(bruto - desconto, 2)),
            )
            if tabela == "TB_MOV_CAB":
                cur.executemany("INSERT INTO TB_MOV_ITE VALUES (?,?,?,?,?,?,?)", linhas)
            id_mov += 1
    return id_mov


def gerar(caminho: Path = BANCO) -> Path:
    rng = random.Random(SEMENTE)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.unlink(missing_ok=True)
    con = sqlite3.connect(caminho)
    cur = con.cursor()
    cur.executescript(ESQUEMA)

    produtos = []
    id_prd = 1
    for id_grp, (grupo, itens) in enumerate(GRUPOS.items(), start=1):
        cur.execute("INSERT INTO TB_CAD_GRP VALUES (?,?)", (id_grp, grupo.upper()))
        for nome, preco in itens:
            custo = round(preco * rng.uniform(0.55, 0.7), 2)
            cur.execute("INSERT INTO TB_CAD_PRD VALUES (?,?,?,?,?,?)", (id_prd, nome.upper(), id_grp, preco, custo, "S"))
            produtos.append((id_prd, preco, custo))
            id_prd += 1

    n_cli = 180
    for i in range(1, n_cli + 1):
        nome = f"{rng.choice(NOMES)} {rng.choice(SOBRENOMES)}".upper()
        cadastro = date(2022, 1, 1) + timedelta(days=rng.randint(0, 1000))
        cur.execute("INSERT INTO TB_CAD_CLI VALUES (?,?,?,?)", (i, nome, rng.choice(CIDADES), cadastro.strftime("%Y%m%d")))
    for i, nome in enumerate(VENDEDORES, start=1):
        cur.execute("INSERT INTO TB_CAD_VDR VALUES (?,?)", (i, nome.upper()))

    # tabela morta: um ano do sistema antigo, nunca deve entrar na conta
    _movimentos(cur, "TB_MOV_CAB_OLD", date(2019, 1, 1), 365, 1, rng, produtos, n_cli)
    _movimentos(cur, "TB_MOV_CAB", date(2025, 1, 1), 365, 100_001, rng, produtos, n_cli)

    cur.executemany("INSERT INTO TB_PAR_SIS VALUES (?,?)", [("VERSAO", "4.2.17"), ("EMP_CNPJ", "00.000.000/0001-00")])
    con.commit()
    con.close()
    return caminho


if __name__ == "__main__":
    print(gerar())
