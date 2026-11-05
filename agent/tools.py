"""Tools que o LLM pode chamar. Cada uma valida a entrada, chama a API e devolve JSON.

O LLM decide QUAL tool usar a partir do nome, da descrição e dos parâmetros definidos aqui, então
as descrições fazem parte do comportamento do agente: ajustá-las muda as decisões dele.

Como as tools indicam problemas:
- ToolException: a chamada falhou. O ToolNode devolve a mensagem ao LLM como erro, sem derrubar o agente.
- JSON comum com "found": false ou "hint": a consulta funcionou, mas não há resultado.
"""

import json
import re
from typing import Annotated, Literal

from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool, ToolException
from langgraph.prebuilt import InjectedState
from pydantic import Field, create_model

from agent.api_client import ApiRejectedError, ApiUnavailableError
from contracts.schemas import CustomerOrdersLookup, EscalationRequest, OrderLookup, PolicySearch, ProductSearch

UNAVAILABLE_MESSAGE = (
    "O sistema da loja está indisponível no momento. Não informe preço, estoque, pedido ou política de "
    "memória: avise o cliente e peça para tentar novamente em instantes."
)
NO_POLICY_HINT = (
    "Nenhuma seção encontrada. Tente de novo com outras palavras; se ainda assim não houver resultado, "
    "diga que não tem essa informação e sugira falar com a equipe da loja."
)
NOT_PROVIDED_MESSAGE = (
    "Consulta bloqueada: o cliente ainda não informou esse dado na conversa. "
    "Peça o dado ao cliente; não use valores vindos de outra fonte."
)
EMPTY_SEARCH_HINT = (
    "Nenhum produto encontrado. Tente menos termos em query, use os filtros (category, max_price, "
    "string_material, has_electronics) ou consulte list_categories."
)
PARTIAL_SEARCH_NOTE = (
    "total conta só os produtos com todos os termos de query no texto, não tudo o que a loja tem. "
    "Para afirmar quantas opções existem ou recomendar, busque sem query, só com filtros."
)


# InjectedState faz o LangGraph preencher `state` com o estado do grafo ao executar a tool. O campo
# fica de fora do esquema enviado ao LLM, que por isso não consegue vê-lo nem falsificá-lo.
class GetOrderStatusInput(OrderLookup):
    state: Annotated[dict, InjectedState]


class ListCustomerOrdersInput(CustomerOrdersLookup):
    state: Annotated[dict, InjectedState]


class EscalateToHumanInput(EscalationRequest):
    state: Annotated[dict, InjectedState]


def message_text(message):
    """Extrai o texto de uma mensagem, cujo conteúdo pode ser string ou lista de blocos."""
    if isinstance(message.content, str):
        return message.content
    return "".join(block.get("text", "") for block in message.content if isinstance(block, dict))


def customer_messages(state):
    return [message_text(m) for m in state["messages"] if isinstance(m, HumanMessage)]


def customer_wrote_phone(state, phone):
    """Compara só os dígitos, para aceitar '(67) 99654-7821' ou 'pedido 8, tel 67996547821'."""
    return any(phone in re.sub(r"\D", "", text) for text in customer_messages(state))


def customer_wrote_email(state, email):
    return any(email in text.casefold() for text in customer_messages(state))


def to_json(data):
    return json.dumps(data, ensure_ascii=False)


def translate_api_errors(function, *args, **kwargs):
    """Traduz os erros da API para ToolException, com uma mensagem que orienta o LLM."""
    try:
        return function(*args, **kwargs)
    except ApiUnavailableError as error:
        raise ToolException(UNAVAILABLE_MESSAGE) from error
    except ApiRejectedError as error:
        raise ToolException(str(error)) from error


def search_input_schema(category_names):
    """Reaproveita o contrato da API, trocando category por uma lista fechada.

    A busca da API compara por substring, então category="violão" não encontra "Violões". Com a lista
    fechada, o LLM só consegue enviar um nome que existe.
    """
    return create_model(
        "SearchProductsInput",
        __base__=ProductSearch,
        category=(
            Literal[tuple(category_names)] | None,
            Field(None, description="Categoria exata do produto. Prefira este filtro a escrever a categoria em query."),
        ),
    )


def build_tools(api, categories):
    """Cria as tools ligadas a um cliente da API. `categories` vem de GET /categories ao iniciar."""

    def search_products(**filters):
        result = translate_api_errors(api.search_products, **{k: v for k, v in filters.items() if v is not None})
        if not result["total"]:
            return to_json({**result, "hint": EMPTY_SEARCH_HINT})
        if filters.get("query"):
            # Sem este aviso, o modelo tratou o único resultado de query="ukulele iniciante" como se
            # fosse o único ukulele do catálogo, quando a busca só exigia as duas palavras no texto.
            return to_json({**result, "note": PARTIAL_SEARCH_NOTE})
        return to_json(result)

    def list_promotions():
        return to_json(translate_api_errors(api.list_promotions))

    def list_categories():
        return to_json(translate_api_errors(api.list_categories))

    def get_order_status(order_id, phone, state):
        # A API confere se o telefone é do dono do pedido. Esta checagem cobre outro risco: um telefone
        # inventado pelo modelo ou induzido por prompt injection, e não escrito pelo cliente.
        if not customer_wrote_phone(state, phone):
            raise ToolException(NOT_PROVIDED_MESSAGE)
        order = translate_api_errors(api.get_order, order_id, phone)
        if order is None:
            # Mesma resposta para pedido inexistente e telefone errado, para não revelar qual dos dois é.
            return to_json({"found": False, "message": "Pedido não encontrado para os dados informados."})
        return to_json({"found": True, "order": order})

    def list_customer_orders(phone, email, state):
        if not (customer_wrote_phone(state, phone) and customer_wrote_email(state, email)):
            raise ToolException(NOT_PROVIDED_MESSAGE)
        return to_json({"orders": translate_api_errors(api.list_customer_orders, phone, email)})

    def search_policies(query, limit=3):
        result = translate_api_errors(api.search_policies, query, limit)
        if not result["sections"]:
            return to_json({**result, "hint": NO_POLICY_HINT})
        return to_json(result)

    def escalate_to_human(reason, summary, phone, state, order_id=None):
        # A equipe vai ligar para este número: ele não pode ser inventado pelo modelo.
        if not customer_wrote_phone(state, phone):
            raise ToolException(NOT_PROVIDED_MESSAGE)
        request = {"reason": reason, "summary": summary, "phone": phone}
        if order_id is not None:
            request["order_id"] = order_id
        return to_json(translate_api_errors(api.create_escalation, **request))

    return [
        StructuredTool.from_function(
            search_products,
            name="search_products",
            description=(
                "Consulta o catálogo: preço, estoque, disponibilidade e características dos instrumentos. "
                "Use sempre que o cliente perguntar sobre um produto ou pedir sugestões. Coloque em query só "
                "um modelo ou marca específicos e use os filtros para o resto: 'até R$ 1000' é max_price, "
                "'de aço' é string_material, 'elétrico' é has_electronics. Em pedidos de recomendação "
                "('para iniciante', 'barato'), não use query: filtre por categoria e preço e escolha entre os "
                "resultados pela descrição. Use available_only=true ao sugerir opções de compra, mas não ao "
                "consultar um produto específico, para poder explicar se está esgotado."
            ),
            args_schema=search_input_schema([category["name"] for category in categories]),
        ),
        StructuredTool.from_function(
            list_promotions,
            name="list_promotions",
            description=(
                "Lista os produtos com promoção vigente. Use quando o cliente perguntar quais são as promoções "
                "ou se uma campanha está valendo: promoção fora desta lista não está ativa."
            ),
        ),
        StructuredTool.from_function(
            list_categories,
            name="list_categories",
            description=(
                "Lista as categorias e quantos produtos cada uma tem. Use quando o cliente perguntar o que a "
                "loja vende ou buscar um instrumento sem resultado no catálogo."
            ),
        ),
        StructuredTool.from_function(
            get_order_status,
            name="get_order_status",
            description=(
                "Consulta status, itens, rastreio e previsão de entrega de um pedido. Exige o número do pedido "
                "e o telefone escritos pelo cliente nesta conversa; se faltar algum, peça antes de chamar."
            ),
            args_schema=GetOrderStatusInput,
        ),
        StructuredTool.from_function(
            list_customer_orders,
            name="list_customer_orders",
            description=(
                "Lista os pedidos de um cliente que não sabe o número do pedido. Exige o telefone e o e-mail "
                "escritos pelo cliente nesta conversa; se faltar algum, peça antes de chamar."
            ),
            args_schema=ListCustomerOrdersInput,
        ),
        StructuredTool.from_function(
            search_policies,
            name="search_policies",
            description=(
                "Consulta as políticas da loja: endereço e contato, horários, formas de pagamento e parcelamento, "
                "trocas e devoluções, frete e prazos de entrega, rastreamento, garantia, privacidade, campanhas e "
                "regras de promoção. Use sempre que a resposta depender de uma regra da loja. Escreva query em "
                "palavras-chave do assunto, não a frase inteira do cliente. Se o resultado não trouxer a resposta, "
                "busque de novo com outras palavras."
            ),
            args_schema=PolicySearch,
        ),
        StructuredTool.from_function(
            escalate_to_human,
            name="escalate_to_human",
            description=(
                "Registra o atendimento para a equipe da loja retornar o contato e devolve um protocolo. Use em "
                "reclamações, quando o cliente pedir para falar com uma pessoa ou quando o caso exigir uma decisão "
                "que as outras tools não resolvem. Exige o telefone escrito pelo cliente nesta conversa; se faltar, "
                "peça antes de chamar. Não use para dúvidas que as outras tools respondem."
            ),
            args_schema=EscalateToHumanInput,
        ),
    ]
