import json
import sqlite3

import pytest

from agente_erp.agente import executar
from agente_erp.conferencia import numeros_do_texto, sem_lastro
from agente_erp.erp import gerar
from agente_erp.ferramentas import Ferramentas
from agente_erp.gabarito import conferir, perguntas
from agente_erp.llm import PedidoFerramenta, Turno, Uso, pedidos_no_texto


@pytest.fixture(scope="module")
def banco(tmp_path_factory):
    return gerar(tmp_path_factory.mktemp("erp") / "loja.db")


class ModeloRoteirizado:
    """Devolve turnos prontos, na ordem. Serve para testar o laço sem LLM."""

    nome = "roteiro"

    def __init__(self, *turnos: Turno):
        self.turnos = list(turnos)
        self.uso = Uso()
        self.historicos: list[list[Turno]] = []

    def responder(self, sistema, historico, ferramentas):
        self.historicos.append(list(historico))
        return self.turnos.pop(0)


def consulta(sql: str, id_: str = "c1") -> Turno:
    return Turno("assistant", pedidos=[PedidoFerramenta(id_, "consultar", {"sql": sql})])


# ---- guardrails das ferramentas


def test_consulta_de_leitura_funciona(banco):
    saida = json.loads(Ferramentas(banco).consultar("SELECT COUNT(*) AS n FROM TB_CAD_PRD"))
    assert saida["linhas"] == [[16]]


@pytest.mark.parametrize("sql", [
    "DELETE FROM TB_CAD_PRD",
    "UPDATE TB_CAD_PRD SET VL_VDA = 0",
    "DROP TABLE TB_CAD_PRD",
    "SELECT 1; DELETE FROM TB_CAD_PRD",
    "ATTACH DATABASE 'x.db' AS x",
])
def test_escrita_e_recusada_e_banco_fica_intacto(banco, sql):
    ferramentas = Ferramentas(banco)
    saida = ferramentas.executar("consultar", {"sql": sql})
    assert saida.startswith("ERRO") and ferramentas.chamadas[-1].recusada
    assert sqlite3.connect(banco).execute("SELECT COUNT(*) FROM TB_CAD_PRD").fetchone()[0] == 16


def test_autorizador_barra_escrita_escondida_num_with(banco):
    ferramentas = Ferramentas(banco)
    saida = ferramentas.executar("consultar", {"sql": "WITH x AS (SELECT 1) DELETE FROM TB_CAD_PRD"})
    assert saida.startswith("ERRO")


def test_resultado_grande_e_cortado(banco):
    saida = json.loads(Ferramentas(banco).consultar("SELECT ID_MOV FROM TB_MOV_CAB"))
    assert len(saida["linhas"]) == 50 and "aviso" in saida


# ---- conferência de números


def test_le_numeros_no_formato_brasileiro():
    assert numeros_do_texto("Faturou R$ 1.486.422,70 em 2025, com 2228 vendas") == [1486422.70, 2025, 2228]


def test_numero_sem_lastro_e_apontado():
    saidas = [json.dumps({"colunas": ["total"], "linhas": [[1486422.7]]})]
    assert sem_lastro("Foram R$ 1.486.422,70.", saidas, "Quanto faturou?") == []
    assert sem_lastro("Foram R$ 1.500.000,00.", saidas, "Quanto faturou?") == [1500000.0]


def test_numero_da_pergunta_tem_lastro():
    assert sem_lastro("Em 2025 foram R$ 10,00.", [json.dumps({"linhas": [[10.0]]})], "E em 2025?") == []


# ---- laço do agente


def test_agente_corrige_conta_feita_de_cabeca(banco):
    modelo = ModeloRoteirizado(
        consulta("SELECT ROUND(SUM(VL_TOT), 2) FROM TB_MOV_CAB WHERE TP_MOV = 1 AND ST_MOV <> 'C'"),
        Turno("assistant", texto="O faturamento foi de cerca de R$ 1.500.000,00."),
        Turno("assistant", texto="O faturamento de 2025 foi de R$ 1.486.422,70."),
    )
    e = executar("Qual foi o faturamento total da loja em 2025?", modelo, banco)
    assert e.confiavel and e.resposta.endswith("R$ 1.486.422,70.")
    pedido_de_correcao = modelo.historicos[2][-1].texto
    assert "1500000.00" in pedido_de_correcao


def test_resposta_sem_lastro_duas_vezes_nao_e_confiavel(banco):
    modelo = ModeloRoteirizado(
        Turno("assistant", texto="Foram 3000 vendas."),
        Turno("assistant", texto="Foram 3001 vendas."),
    )
    e = executar("Quantas vendas?", modelo, banco)
    assert not e.confiavel and e.sem_lastro == [3001.0]


# ---- gabarito


def test_gabarito_ignora_orcamentos_e_canceladas(banco):
    p = next(p for p in perguntas(banco) if p.id == "p03")
    con = sqlite3.connect(banco)
    total = con.execute("SELECT COUNT(*) FROM TB_MOV_CAB").fetchone()[0]
    assert 0 < p.resposta < total
    assert conferir(p, f"Foram {p.resposta} vendas.") and not conferir(p, f"Foram {total} vendas.")


def test_resposta_de_ausencia_pede_verificacao(banco):
    # "não há vendas" depois de um filtro errado (data em texto) era a falha mais comum do 7B
    modelo = ModeloRoteirizado(
        consulta("SELECT COUNT(*) AS n FROM TB_MOV_CAB WHERE strftime('%Y', DT_MOV) = '2025'"),
        Turno("assistant", texto="Não há vendas registradas em 2025."),
        consulta("SELECT COUNT(*) AS n FROM TB_MOV_CAB WHERE DT_MOV LIKE '2025%' AND TP_MOV = 1", "c2"),
        Turno("assistant", texto="Houve vendas em 2025, conforme a segunda consulta."),
    )
    e = executar("Quantas vendas em 2025?", modelo, banco)
    assert e.verificou_ausencia and e.consultas == 2
    assert "Antes de afirmar isso" in modelo.historicos[2][-1].texto


def test_ausencia_confirmada_depois_da_verificacao_e_aceita(banco):
    modelo = ModeloRoteirizado(
        Turno("assistant", texto="Não existe tabela de fornecedores."),
        Turno("assistant", texto="Confirmei: não existe tabela de fornecedores."),
    )
    e = executar("Quem é o maior fornecedor?", modelo, banco)
    assert e.confiavel and e.verificou_ausencia and e.passos == 2


def test_pedido_de_ferramenta_escrito_como_texto_e_reconhecido():
    texto = '<tool_call>\n{"name": "listar_tabelas"}\n</tool_call>'
    [p] = pedidos_no_texto(texto)
    assert (p.nome, p.entrada) == ("listar_tabelas", {})
    [p] = pedidos_no_texto('<tool_call>{"name": "consultar", "arguments": {"sql": "SELECT 1"}}</tool_call>')
    assert p.entrada == {"sql": "SELECT 1"}
    assert pedidos_no_texto("Faturou R$ 10,00.") == []
