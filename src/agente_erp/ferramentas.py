"""As ferramentas que o agente pode chamar, com as proteções aplicadas no código.

A regra é não confiar no modelo para se comportar: a proteção vale mesmo se ele tentar outra coisa.

- O banco abre em modo somente leitura (`mode=ro`). Escrever falha no próprio SQLite.
- Um autorizador do SQLite libera só leitura e funções; qualquer outra ação é negada antes de rodar.
- Uma consulta por chamada; nada de `;` encadeando comandos.
- Tempo máximo por consulta e número máximo de linhas devolvidas, para uma consulta ruim não
  travar o banco nem encher o contexto do modelo.

Cada chamada fica registrada; o registro serve para a conferência de números da resposta final.
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

LIMITE_LINHAS = 50
LIMITE_SEGUNDOS = 3.0

PERMITIDAS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
# PRAGMA de leitura usado por descrever_tabela; o modelo não consegue chamá-lo pela consulta
# porque `consultar` exige SELECT ou WITH no começo
PRAGMA_LEITURA = {"table_info"}

DEFINICOES = [
    {
        "name": "listar_tabelas",
        "description": "Lista as tabelas do banco com o número de linhas de cada uma.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "descrever_tabela",
        "description": "Mostra as colunas de uma tabela, com tipo, e 3 linhas de exemplo.",
        "input_schema": {
            "type": "object",
            "properties": {"tabela": {"type": "string"}},
            "required": ["tabela"],
        },
    },
    {
        "name": "consultar",
        "description": (
            "Executa uma única consulta SQL de leitura (SELECT ou WITH) no banco SQLite e devolve até "
            f"{LIMITE_LINHAS} linhas. Faça as contas no SQL: a resposta final só pode trazer números "
            "que apareceram no resultado de alguma consulta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
]


class ConsultaRecusada(Exception):
    pass


@dataclass
class Chamada:
    ferramenta: str
    entrada: dict
    saida: str
    recusada: bool = False


@dataclass
class Ferramentas:
    banco: Path
    chamadas: list[Chamada] = field(default_factory=list)

    def _conectar(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.banco}?mode=ro", uri=True)

        def autorizar(acao, arg1, arg2, *_):
            if acao in PERMITIDAS or (acao == sqlite3.SQLITE_PRAGMA and arg1 in PRAGMA_LEITURA):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        con.set_authorizer(autorizar)
        inicio = time.monotonic()
        # a cada 10 mil instruções da máquina virtual do SQLite, confere o relógio
        con.set_progress_handler(lambda: int(time.monotonic() - inicio > LIMITE_SEGUNDOS), 10_000)
        return con

    def executar(self, nome: str, entrada: dict) -> str:
        try:
            saida = getattr(self, nome)(**entrada)
            recusada = False
        except (ConsultaRecusada, sqlite3.Error, TypeError, AttributeError) as erro:
            saida = f"ERRO: {erro}"
            recusada = isinstance(erro, ConsultaRecusada) or "not authorized" in str(erro)
        self.chamadas.append(Chamada(nome, entrada, saida, recusada))
        return saida

    def listar_tabelas(self) -> str:
        with self._conectar() as con:
            nomes = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return json.dumps({n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in nomes})

    def descrever_tabela(self, tabela: str) -> str:
        with self._conectar() as con:
            existentes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tabela not in existentes:
                raise ConsultaRecusada(f"tabela inexistente: {tabela}")
            colunas = [{"coluna": r[1], "tipo": r[2]} for r in con.execute(f'PRAGMA table_info("{tabela}")')]
            exemplos = con.execute(f'SELECT * FROM "{tabela}" LIMIT 3').fetchall()
            return json.dumps({"colunas": colunas, "exemplos": exemplos}, ensure_ascii=False)

    def consultar(self, sql: str) -> str:
        comando = sql.strip().rstrip(";").strip()
        if ";" in comando:
            raise ConsultaRecusada("só é permitida uma consulta por chamada")
        if not comando.lower().startswith(("select", "with")):
            raise ConsultaRecusada("só são permitidas consultas de leitura (SELECT ou WITH)")
        with self._conectar() as con:
            cursor = con.execute(comando)
            colunas = [d[0] for d in cursor.description]
            linhas = cursor.fetchmany(LIMITE_LINHAS + 1)
        cortado = len(linhas) > LIMITE_LINHAS
        resultado = {"colunas": colunas, "linhas": linhas[:LIMITE_LINHAS]}
        if cortado:
            resultado["aviso"] = f"resultado cortado em {LIMITE_LINHAS} linhas; agregue ou filtre mais"
        return json.dumps(resultado, ensure_ascii=False)
