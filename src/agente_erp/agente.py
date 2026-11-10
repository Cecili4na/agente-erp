"""O laço do agente: pensar, chamar ferramenta, ler o resultado, repetir, responder.

O laço tem quatro freios:
- um número máximo de passos (o agente não fica consultando para sempre);
- a conferência de números na resposta final: se algum número não tem lastro nas consultas,
  o agente recebe a lista e tem uma chance de corrigir;
- a conferência de ausência: "não há dados" também é uma afirmação e precisa ser verificada.
  Na primeira avaliação, o 7B desistia assim na maioria das perguntas, muitas vezes depois de
  um filtro errado que devolvia vazio. Ele recebe uma chance de olhar as linhas reais antes;
- se ainda assim falhar, a resposta é marcada como não confiável e não é entregue como certa.

Há dois modos, para medir quanto o contexto de negócio ajuda:
- "cego": o agente só tem as ferramentas e precisa descobrir sozinho o que cada sigla significa;
- "com_notas": recebe também as notas de negócio (`NOTAS`), como um analista novo que ganhou a
  documentação do sistema no primeiro dia.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from agente_erp.conferencia import sem_lastro
from agente_erp.ferramentas import DEFINICOES, Ferramentas
from agente_erp.llm import Modelo, ResultadoFerramenta, Turno

MAX_PASSOS = 12
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]
HOJE = date.today()

# respostas do tipo "não há vendas em 2025", "não é possível calcular", "nenhuma venda"
NEGATIVA = re.compile(
    r"\bn[ãa]o (h[áa]|existem?|consta|foi poss[íi]vel|[ée] poss[íi]vel|possui|cont[ée]m)\b|\bnenhum[a]?\b",
    re.IGNORECASE,
)
VERIFICAR_AUSENCIA = (
    "Você concluiu que não há dados ou que não dá para responder. Antes de afirmar isso, confira: "
    "veja algumas linhas reais das tabelas envolvidas (SELECT * ... LIMIT 3) e verifique se os filtros "
    "batem com o formato real das colunas. Uma consulta vazia costuma ser filtro errado, não falta de "
    "dados. Depois responda de novo."
)

SISTEMA = f"""Hoje é {HOJE.day} de {MESES[HOJE.month - 1]} de {HOJE.year}.

Você é um analista de dados que responde perguntas de negócio de uma loja de autopeças
consultando o banco SQLite do sistema de gestão dela, um ERP antigo com nomes de tabela em siglas.

Como trabalhar:
- Explore o banco com as ferramentas antes de responder. Não presuma o significado de uma coluna:
  olhe exemplos.
- Faça todas as contas no SQL. A resposta final só pode conter números que apareceram no resultado
  de alguma consulta.
- Responda em português, em uma ou duas frases, com o valor pedido. Valores em reais com duas casas
  no formato brasileiro (R$ 1.234,56).
- Se a pergunta não puder ser respondida com os dados, diga isso."""

NOTAS = """
Notas de negócio do sistema (escritas por quem conhece o ERP):
- TB_MOV_CAB guarda vendas, orçamentos e devoluções juntos. TP_MOV: 1 = venda, 2 = orçamento,
  3 = devolução. Faturamento é só TP_MOV = 1.
- ST_MOV: A = aberto, F = finalizado, C = cancelado. Vendas canceladas não contam.
- VL_BRU é o valor antes do desconto, VL_DSC é o desconto e VL_TOT é o valor final. Faturamento usa VL_TOT.
- DT_MOV é texto no formato AAAAMMDD.
- TB_MOV_CAB_OLD é de um sistema antigo desativado em 2019. Não use.
- TB_MOV_ITE tem os itens de cada movimento (QT_ITE = quantidade, VL_TOT do item = antes do desconto do cabeçalho)."""


@dataclass
class Execucao:
    pergunta: str
    resposta: str
    confiavel: bool
    passos: int
    consultas: int
    recusadas: int
    sem_lastro: list[float] = field(default_factory=list)
    chamadas: list = field(default_factory=list)
    verificou_ausencia: bool = False


def executar(pergunta: str, modelo: Modelo, banco: Path, modo: str = "com_notas") -> Execucao:
    ferramentas = Ferramentas(banco)
    sistema = SISTEMA + (NOTAS if modo == "com_notas" else "")
    historico = [Turno("user", texto=pergunta)]
    correcao_usada = False
    ausencia_verificada = False
    problemas: list[float] = []
    resposta = ""

    for passo in range(1, MAX_PASSOS + 1):
        turno = modelo.responder(sistema, historico, DEFINICOES)
        historico.append(turno)

        if turno.pedidos:
            resultados = [ResultadoFerramenta(p.id, ferramentas.executar(p.nome, p.entrada)) for p in turno.pedidos]
            historico.append(Turno("user", resultados=resultados))
            continue

        resposta = turno.texto.strip()
        problemas = sem_lastro(resposta, [c.saida for c in ferramentas.chamadas], pergunta)
        if problemas and not correcao_usada:
            correcao_usada = True
            lista = ", ".join(f"{n:.2f}" for n in problemas)
            historico.append(Turno("user", texto=(
                f"Sua resposta tem números que não aparecem em nenhum resultado de consulta: {lista}. "
                "Calcule esses valores com SQL e responda de novo."
            )))
            continue
        if not problemas and not ausencia_verificada and NEGATIVA.search(resposta):
            ausencia_verificada = True
            historico.append(Turno("user", texto=VERIFICAR_AUSENCIA))
            continue
        break
    else:
        resposta = resposta or "Não cheguei a uma resposta dentro do limite de passos."
        problemas = problemas or [float("nan")]

    return Execucao(
        pergunta=pergunta,
        resposta=resposta,
        confiavel=not problemas,
        passos=passo,
        consultas=sum(c.ferramenta == "consultar" for c in ferramentas.chamadas),
        recusadas=sum(c.recusada for c in ferramentas.chamadas),
        sem_lastro=problemas,
        chamadas=ferramentas.chamadas,
        verificou_ausencia=ausencia_verificada,
    )
