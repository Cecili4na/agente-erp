"""Modelos com chamada de ferramentas (tool calling), num formato comum.

Cada provedor tem seu jeito de representar "o modelo quer chamar a ferramenta X com estes
argumentos" e "aqui está o resultado". Este módulo converte tudo para três tipos simples
(`Turno`, `PedidoFerramenta`, `ResultadoFerramenta`), e o agente só conhece esses tipos.

Escolha do provedor por variável de ambiente:
- ANTHROPIC_API_KEY: Claude, pela API da Anthropic.
- LLM_BASE_URL + LLM_MODELO: qualquer servidor compatível com a API da OpenAI (Ollama, vLLM).
"""

import json
import os
from dataclasses import dataclass, field
from typing import Protocol

import httpx


@dataclass
class PedidoFerramenta:
    id: str
    nome: str
    entrada: dict


@dataclass
class ResultadoFerramenta:
    id: str
    saida: str


@dataclass
class Turno:
    papel: str  # "user" ou "assistant"
    texto: str = ""
    pedidos: list[PedidoFerramenta] = field(default_factory=list)
    resultados: list[ResultadoFerramenta] = field(default_factory=list)


@dataclass
class Uso:
    entrada: int = 0
    saida: int = 0


class Modelo(Protocol):
    nome: str
    uso: Uso

    def responder(self, sistema: str, historico: list[Turno], ferramentas: list[dict]) -> Turno: ...


class Anthropic:
    def __init__(self, modelo: str | None = None):
        import anthropic

        self.nome = modelo or os.environ.get("LLM_MODELO", "claude-haiku-5-5")
        self.uso = Uso()
        self._cliente = anthropic.Anthropic()

    @staticmethod
    def _mensagem(t: Turno) -> dict:
        blocos: list[dict] = []
        if t.texto:
            blocos.append({"type": "text", "text": t.texto})
        blocos += [{"type": "tool_use", "id": p.id, "name": p.nome, "input": p.entrada} for p in t.pedidos]
        blocos += [{"type": "tool_result", "tool_use_id": r.id, "content": r.saida} for r in t.resultados]
        return {"role": t.papel, "content": blocos}

    def responder(self, sistema, historico, ferramentas):
        r = self._cliente.messages.create(
            model=self.nome,
            max_tokens=1500,
            temperature=0,
            system=sistema,
            tools=ferramentas,
            messages=[self._mensagem(t) for t in historico],
        )
        self.uso.entrada += r.usage.input_tokens
        self.uso.saida += r.usage.output_tokens
        return Turno(
            "assistant",
            texto="".join(b.text for b in r.content if b.type == "text"),
            pedidos=[PedidoFerramenta(b.id, b.name, b.input) for b in r.content if b.type == "tool_use"],
        )


class CompativelOpenAI:
    def __init__(self, base_url: str, modelo: str):
        self.nome = modelo
        self.uso = Uso()
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._cabecalhos = {"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', 'local')}"}

    @staticmethod
    def _mensagens(sistema: str, historico: list[Turno]) -> list[dict]:
        saida = [{"role": "system", "content": sistema}]
        for t in historico:
            if t.resultados:
                saida += [{"role": "tool", "tool_call_id": r.id, "content": r.saida} for r in t.resultados]
                continue
            m: dict = {"role": t.papel, "content": t.texto or None}
            if t.pedidos:
                m["tool_calls"] = [
                    {"id": p.id, "type": "function",
                     "function": {"name": p.nome, "arguments": json.dumps(p.entrada, ensure_ascii=False)}}
                    for p in t.pedidos
                ]
            saida.append(m)
        return saida

    def responder(self, sistema, historico, ferramentas):
        funcoes = [
            {"type": "function", "function": {"name": f["name"], "description": f["description"],
                                              "parameters": f["input_schema"]}}
            for f in ferramentas
        ]
        r = httpx.post(
            self._url,
            headers=self._cabecalhos,
            timeout=180,
            json={"model": self.nome, "temperature": 0, "messages": self._mensagens(sistema, historico),
                  "tools": funcoes},
        )
        r.raise_for_status()
        corpo = r.json()
        self.uso.entrada += corpo.get("usage", {}).get("prompt_tokens", 0)
        self.uso.saida += corpo.get("usage", {}).get("completion_tokens", 0)
        msg = corpo["choices"][0]["message"]
        pedidos = [
            PedidoFerramenta(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"] or "{}"))
            for c in msg.get("tool_calls") or []
        ]
        return Turno("assistant", texto=msg.get("content") or "", pedidos=pedidos)


def do_ambiente() -> Modelo:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Anthropic()
    if os.environ.get("LLM_BASE_URL"):
        return CompativelOpenAI(os.environ["LLM_BASE_URL"], os.environ.get("LLM_MODELO", "qwen2.5:7b-instruct"))
    raise RuntimeError(
        "Nenhum modelo configurado. Defina ANTHROPIC_API_KEY, ou LLM_BASE_URL e LLM_MODELO "
        "para um servidor compatível com a API da OpenAI."
    )
