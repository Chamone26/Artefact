"""Grava as conversas de exemplo a partir de execuções reais do agente. Consome créditos da API.

As respostas são salvas como o modelo as escreveu, sem edição, e variam a cada execução.
Os telefones são da base fictícia da loja. Os encaminhamentos gravam em api/escalations.jsonl.
"""

import sys
import uuid
from pathlib import Path

from agent.config import Settings
from agent.graph import create_agent

EXAMPLES_DIR = Path(__file__).parent

CONVERSATIONS = [
    {
        "file": "01_catalogo.md",
        "title": "Consulta ao catálogo",
        "about": "Filtro por categoria e preço, seguido de um refinamento que depende da mensagem anterior.",
        "messages": [
            "Quais opções de violões disponíveis custando até R$1000?",
            "Desses, quais têm cordas de nylon?",
        ],
    },
    {
        "file": "02_preco_e_promocao.md",
        "title": "Preço, estoque e promoção",
        "about": "Preço de um modelo específico, promoção encerrada e produto com promoção vigente.",
        "messages": [
            "Quanto custa o Takamine GD20?",
            "Ele tem em estoque? Vi que estava com 12% de desconto na Oferta Especial.",
            "E o Ohana CK-20, está em promoção?",
        ],
    },
    {
        "file": "03_informacoes_da_loja.md",
        "title": "Informações gerais da loja",
        "about": "Respostas vindas da busca nas políticas: endereço, horário e formas de pagamento.",
        "messages": [
            "Qual o endereço da loja?",
            "Vocês abrem no sábado?",
            "Dá para parcelar uma compra de R$ 800 em quantas vezes?",
        ],
    },
    {
        "file": "04_devolucao_de_pedido.md",
        "title": "Devolução de um pedido (caso não trivial)",
        "about": (
            "Combina três fontes: a política de devolução, a verificação do telefone e os dados do pedido. "
            "A data de referência do agente é 2026-03-25, logo depois do último pedido da base."
        ),
        "messages": [
            "Me arrependi da minha compra, posso devolver meu pedido?",
            "É o pedido 1, meu telefone é (67) 98432-1098",
        ],
    },
    {
        "file": "05_fora_do_escopo_e_reclamacao.md",
        "title": "Fora do escopo, acessório e reclamação",
        "about": "Assunto alheio à loja, produto que a loja não vende e encaminhamento de uma reclamação à equipe.",
        "messages": [
            "Qual a capital da França?",
            "Vocês vendem palheta?",
            "Poxa, meu ukulele chegou com um risco enorme, estou bem chateado.",
            "Meu telefone é (67) 99654-7821, não tenho o número do pedido aqui",
        ],
    },
]


def format_tool_call(call):
    args = ", ".join(f"{key}={value!r}" for key, value in call.args.items())
    return f"`{call.name}({args})`" + (" (erro)" if call.is_error else "")


def record(agent, conversation):
    lines = [f"# {conversation['title']}", "", conversation["about"], ""]
    session_id = str(uuid.uuid4())
    for message in conversation["messages"]:
        reply = agent.respond(session_id, message)
        lines += [f"**Cliente:** {message}", ""]
        if reply.tool_calls:
            lines += ["Tools chamadas: " + "; ".join(format_tool_call(call) for call in reply.tool_calls), ""]
        lines += ["**Agente:**", "", reply.text, ""]
    return "\n".join(lines)


def main():
    settings = Settings.from_env()
    agent = create_agent(settings)
    for conversation in CONVERSATIONS:
        path = EXAMPLES_DIR / conversation["file"]
        path.write_text(record(agent, conversation), encoding="utf-8")
        print(f"Gravada: {path.name}")


if __name__ == "__main__":
    main()
