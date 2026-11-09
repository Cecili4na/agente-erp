# agente-erp

Um agente que responde perguntas de negócio ("quanto a loja faturou em março?") consultando o
banco de um ERP antigo, com nomes de tabela em siglas e as armadilhas que sistemas reais têm.
O agente escreve o próprio SQL. As proteções ficam no código, não no prompt.

```
$ agente-erp perguntar "Qual vendedor mais faturou em 2025?" --mostrar-sql
```

## O problema

Pequenos varejistas têm anos de dados num sistema de gestão que só o fornecedor entende. Um LLM
consegue escrever SQL, mas num banco assim ele erra de um jeito perigoso: com confiança. Neste
banco, por exemplo:

| Armadilha | O que acontece se o agente cair |
|---|---|
| Venda, orçamento e devolução na mesma tabela (`TP_MOV` = 1, 2, 3) | O faturamento de 2025 sai R$ 2,2 milhões em vez de R$ 1,49 milhão |
| Vendas canceladas continuam na tabela (`ST_MOV = 'C'`) | Contagens e somas infladas |
| `VL_BRU` (antes do desconto) ao lado de `VL_TOT` (o que vale) | Faturamento 3% maior |
| `TB_MOV_CAB_OLD`, cópia morta de um sistema anterior | Dados de 2019 misturados |
| Datas como texto `AAAAMMDD` | Filtros de mês e dia da semana quebram |

O banco é gerado por `erp.py` com semente fixa: quem rodar de novo obtém os mesmos dados.

## As proteções

**Na ferramenta de consulta** (`ferramentas.py`), valendo mesmo que o modelo tente outra coisa:

- banco aberto em modo somente leitura;
- autorizador do SQLite que nega qualquer ação que não seja leitura, antes de executar
  (pega até `WITH ... DELETE`);
- uma consulta por chamada, limite de 3 segundos e de 50 linhas por resultado.

**Na resposta final** (`conferencia.py`): todo número que o agente afirma precisa ter aparecido
no resultado de alguma consulta, ou na própria pergunta. "R$ 1.486.422,70" na resposta casa com
`1486422.7` no resultado. Se o agente faz conta de cabeça ou arredonda "para cerca de 1,5 milhão",
a resposta volta com a lista dos números sem lastro e ele tem uma chance de refazer com SQL. Se
falhar de novo, a resposta é marcada como não confiável.

## Avaliação

22 perguntas com a resposta certa calculada em **Python, sem SQL** (`gabarito.py`). Se o gabarito
usasse SQL, um erro meu de SQL poderia concordar com o mesmo erro do agente. Cada pergunta tem
anotada a armadilha que ela testa.

O agente roda em dois modos:

- **cego**: só as ferramentas; precisa descobrir sozinho o que `TP_MOV = 2` significa;
- **com notas**: recebe também meia página de notas de negócio, como um analista novo que ganhou
  a documentação do sistema.

Métricas: acerto, fração de respostas confiáveis, **acerto entre as confiáveis** (o quanto a
conferência separa resposta certa de errada), consultas por pergunta e tokens.

> Resultados por modelo: em andamento.

## Rodando

```bash
uv sync
uv run agente-erp gerar-banco

# com um modelo (um dos dois):
export ANTHROPIC_API_KEY=...                                                    # Claude
export LLM_BASE_URL=http://localhost:11434/v1 LLM_MODELO=qwen2.5:7b-instruct    # Ollama, vLLM

uv run agente-erp perguntar "Quanto a loja faturou em março de 2025?" --mostrar-sql
uv run agente-erp avaliar            # os dois modos
```

Testes (sem modelo, sem internet): `uv run pytest`. Cobrem os guardrails (cinco tentativas de
escrita, inclusive escondidas), a leitura de números em formato brasileiro, o laço do agente com um
modelo roteirizado e o gabarito.

## Limites

- A conferência garante que cada número veio de uma consulta, não que a consulta estava certa.
  Um agente que esquece de filtrar orçamentos passa na conferência com o número errado. É por isso
  que a avaliação mede o acerto contra o gabarito, e não só a conferência.
- SQLite com dados sintéticos. Num banco de produção, a ferramenta deveria usar um usuário só de
  leitura no próprio servidor, além das proteções daqui.
