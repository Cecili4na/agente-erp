# Guia de estudo deste projeto

Agentes com ferramentas e guardrails. Para cada parte: o que estudar e as perguntas que podem cair.

## 1. O que é um agente — `agente.py`

**Estudar:** "Building effective agents" (Anthropic, gratuito); a documentação de tool use da
Anthropic ou de function calling da OpenAI.

- Qual a diferença entre um agente e uma chamada única ao LLM?
  > O agente decide os próprios passos: chama uma ferramenta, lê o resultado, decide a próxima ação,
  > até responder. Numa chamada única, o caminho é fixo.
- Como o laço termina?
  > Quando o modelo responde sem pedir ferramenta, ou ao atingir o máximo de passos (12). Sem esse
  > limite, um agente confuso pode consultar para sempre e gastar tokens.
- O que é tool calling por baixo?
  > O modelo recebe a descrição das ferramentas em JSON Schema e, em vez de texto, pode devolver um
  > pedido estruturado: nome da ferramenta e argumentos. O código executa e devolve o resultado como
  > uma nova mensagem. O modelo nunca executa nada.

## 2. Guardrails — `ferramentas.py`

- Por que não basta escrever no prompt "não altere o banco"?
  > Porque o prompt é um pedido, não uma garantia. Uma pergunta maliciosa ou um erro do modelo
  > passam por cima. As proteções têm que estar onde o modelo não manda: no banco e no código.
- Quais são as camadas aqui?
  > Conexão somente leitura; autorizador do SQLite que nega toda ação de escrita antes de
  > executar; uma consulta por chamada; limite de tempo e de linhas.
- Por que o autorizador, se a conexão já é somente leitura?
  > Defesa em profundidade. Se uma camada falhar (alguém trocar o modo de conexão), a outra segura.
  > E o autorizador dá um erro claro antes de tentar.
- Por que limitar linhas?
  > Para uma consulta sem filtro não despejar 3 mil linhas no contexto do modelo. Isso custa caro e
  > piora a resposta. O aviso de corte ensina o agente a agregar no SQL.

## 3. Conferência de números — `conferencia.py`

- O que ela garante e o que não garante?
  > Garante que cada número da resposta veio de uma consulta. Não garante que a consulta estava
  > certa. Por isso a avaliação usa um gabarito independente.
- Por que obrigar o agente a fazer contas no SQL?
  > LLMs erram aritmética e arredondam "para ficar bonito". Uma subtração feita no SQL é exata e
  > fica registrada.
- Qual a ligação com o seu TCC?
  > É a mesma ideia: a IA só pode citar valores já calculados, e cada frase é conferida antes de
  > sair. Aqui aplicada a um agente que escreve SQL, em vez de um texto de relatório.

## 4. Avaliação — `gabarito.py`, `avaliar.py`

**Estudar:** "Your AI product needs evals" (Hamel Husain, gratuito).

- Por que o gabarito é em Python e não em SQL?
  > Independência. Se fosse em SQL, eu poderia cometer o mesmo erro que o agente e os dois
  > concordariam.
- O que mede "acerto entre as confiáveis"?
  > Se a conferência serve para alguma coisa. Se as respostas confiáveis acertam muito mais que as
  > não confiáveis, dá para mostrar só as confiáveis ao usuário com segurança.
- Por que comparar os modos "cego" e "com notas"?
  > Para medir o valor do contexto. Se meia página de notas sobe muito o acerto, a lição para
  > produção é investir em documentar o sistema, não em trocar de modelo.

## 5. Engenharia

- Como testar um agente sem pagar API?
  > Com um modelo roteirizado que devolve turnos prontos. Assim os testes cobrem o laço, a correção
  > e os guardrails, rodam em décimos de segundo e não dependem de internet.
- Como você trocaria de provedor de LLM?
  > `llm.py` converte o formato de cada provedor para três tipos comuns (turno, pedido de
  > ferramenta, resultado). O agente só conhece esses tipos.
