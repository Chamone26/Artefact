"""Grafo LangGraph do agente e a classe Agent, usada por qualquer interface (hoje, a CLI).

    START -> agent -> (pediu tool?) -- sim --> tools -> agent
                                    -- não --> END

Conceitos do LangGraph usados aqui, explicados em docs/agente.md:
- Estado: a lista de mensagens (AgentState), que cada nó recebe e atualiza.
- Nós: funções que recebem o estado e devolvem só o que mudou.
- Aresta condicional: tools_condition olha a última mensagem e decide o próximo nó.
- Checkpointer: salva o estado por thread_id, o que dá a memória de cada sessão.
"""

import logging
from dataclasses import dataclass, field

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.managed import RemainingSteps
from langgraph.prebuilt import ToolNode, tools_condition

from agent.api_client import StoreApiClient
from agent.prompt import build_system_prompt
from agent.tools import build_tools, message_text

logger = logging.getLogger(__name__)

MAX_RESPONSE_TOKENS = 4096
MODEL_TIMEOUT_SECONDS = 60
MODEL_MAX_RETRIES = 2

# Para chamar uma tool, são necessários o nó tools e o nó agent, que lê o resultado. O terceiro passo
# é folga: o LangGraph levanta GraphRecursionError se o grafo termina com zero passos restantes.
MIN_STEPS_TO_USE_TOOLS = 3

# stop_reason em que a resposta veio incompleta: suas tool calls não podem ser executadas.
INCOMPLETE_STOP_REASONS = {"max_tokens", "refusal"}

# Dados pessoais que não podem aparecer nos registros das chamadas.
SENSITIVE_ARGS = {"phone", "email"}

STEP_LIMIT_REPLY = (
    "Essa consulta ficou mais longa do que eu esperava e não consegui concluir. "
    "Pode reformular a pergunta ou me dizer exatamente o que precisa?"
)
INCOMPLETE_REPLY = "Não consegui concluir essa resposta. Pode reformular sua mensagem?"
MODEL_ERROR_REPLY = "Estou com uma instabilidade agora e não consegui responder. Pode tentar de novo em instantes?"


class AgentState(MessagesState):
    """MessagesState traz `messages`, em que os nós acrescentam mensagens em vez de substituir a lista."""

    # Valor gerenciado pelo LangGraph: quantos passos restam até o recursion_limit. Com ele, o agente
    # encerra com uma resposta normal, em vez de deixar o grafo falhar com GraphRecursionError e salvar
    # no histórico uma tool call sem resultado, que a API do modelo rejeitaria na mensagem seguinte.
    remaining_steps: RemainingSteps


def handle_tool_error(error: Exception) -> str:
    """Devolve ao LLM a falha de uma tool (entrada inválida, API fora do ar) sem derrubar o agente."""
    logger.warning("Falha em tool: %s", type(error).__name__)
    return f"Erro ao executar a tool: {error}"


def build_graph(model, tools, system_prompt, checkpointer=None):
    """Monta e compila o grafo."""
    model_with_tools = model.bind_tools(tools)

    def agent_node(state):
        # O system prompt é enviado a cada chamada e não fica salvo no estado, para o histórico guardar
        # só a conversa e o prompt poder mudar sem invalidar sessões.
        response = model_with_tools.invoke([SystemMessage(system_prompt), *state["messages"]])

        # Nos dois casos abaixo, a resposta não entra no histórico: o fallback a substitui. Uma tool call
        # sem resultado salva no histórico faria a API rejeitar a mensagem seguinte da conversa.
        if response.response_metadata.get("stop_reason") in INCOMPLETE_STOP_REASONS:
            logger.warning("Resposta incompleta: %s", response.response_metadata["stop_reason"])
            return {"messages": [AIMessage(INCOMPLETE_REPLY)]}
        if response.tool_calls and state["remaining_steps"] < MIN_STEPS_TO_USE_TOOLS:
            logger.warning("Limite de passos atingido.")
            return {"messages": [AIMessage(STEP_LIMIT_REPLY)]}
        return {"messages": [response]}

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    # ToolNode executa as tool calls da última mensagem, em paralelo se houver mais de uma, e devolve
    # um ToolMessage para cada. handle_tool_errors transforma exceções em mensagens de erro para o LLM.
    builder.add_node("tools", ToolNode(tools, handle_tool_errors=handle_tool_error))
    builder.add_edge(START, "agent")
    # tools_condition vai para "tools" se a última mensagem tem tool calls; caso contrário, encerra.
    builder.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)


@dataclass
class ToolCallRecord:
    name: str
    args: dict
    is_error: bool = False


@dataclass
class AgentReply:
    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


def redact(args):
    return {key: "***" if key in SENSITIVE_ARGS else value for key, value in args.items()}


def collect_tool_calls(messages):
    """Resume as tools chamadas no último turno, ou seja, depois da última mensagem do cliente."""
    last_customer_index = max(i for i, message in enumerate(messages) if isinstance(message, HumanMessage))
    turn = messages[last_customer_index + 1:]
    failed_ids = {m.tool_call_id for m in turn if isinstance(m, ToolMessage) and m.status == "error"}
    return [
        ToolCallRecord(call["name"], redact(call["args"]), call["id"] in failed_ids)
        for message in turn if isinstance(message, AIMessage)
        for call in message.tool_calls
    ]


class Agent:
    """Interface do agente para as camadas de cima. Não usa print nem input: quem conversa é a interface."""

    def __init__(self, graph, recursion_limit):
        self._graph = graph
        self._recursion_limit = recursion_limit

    def respond(self, session_id, message):
        """Processa uma mensagem do cliente. Cada session_id tem um histórico próprio."""
        config = {"configurable": {"thread_id": session_id}, "recursion_limit": self._recursion_limit}
        try:
            result = self._graph.invoke({"messages": [HumanMessage(message)]}, config)
        except anthropic.APIError:
            # Chave inválida, limite de uso ou falha de rede. O cliente recebe uma mensagem amigável,
            # e o detalhe técnico vai para o log do desenvolvedor.
            logger.exception("Falha ao chamar o modelo.")
            return AgentReply(MODEL_ERROR_REPLY)
        messages = result["messages"]
        return AgentReply(message_text(messages[-1]), collect_tool_calls(messages))


def create_agent(settings):
    """Monta o agente real. Falha já na inicialização se a API de dados estiver fora do ar."""
    api = StoreApiClient.from_url(settings.api_url)
    tools = build_tools(api, api.list_categories())
    model = ChatAnthropic(
        model=settings.model,
        api_key=settings.anthropic_api_key,
        max_tokens=MAX_RESPONSE_TOKENS,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
    )
    # InMemorySaver guarda as conversas em memória: elas se perdem ao reiniciar o processo.
    graph = build_graph(model, tools, build_system_prompt(settings.today), InMemorySaver())
    return Agent(graph, settings.recursion_limit)
