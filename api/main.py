"""API HTTP de dados da loja.

Uso, a partir da raiz do repositório: uvicorn api.main:app --reload
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from api.escalations import EscalationLog
from api.store import Store
from contracts.schemas import (
    Category,
    CustomerOrdersLookup,
    EscalationReceipt,
    EscalationRequest,
    Order,
    OrderLookup,
    PolicySearch,
    PolicySearchResult,
    Product,
    ProductSearch,
    ProductSearchResult,
)
from rag.search import PolicyIndex

app = FastAPI(title="Empório da Música: API de dados")


def get_store():
    return Store()


@lru_cache
def get_policy_index():
    """O índice é carregado uma vez e fica em memória, pois não muda enquanto a API está no ar."""
    return PolicyIndex.load()


@lru_cache
def get_escalation_log():
    return EscalationLog()


StoreDependency = Annotated[Store, Depends(get_store)]
PolicyIndexDependency = Annotated[PolicyIndex, Depends(get_policy_index)]
EscalationLogDependency = Annotated[EscalationLog, Depends(get_escalation_log)]


@app.get("/products")
def search_products(search: Annotated[ProductSearch, Query()], store: StoreDependency) -> ProductSearchResult:
    return store.search_products(search)


@app.get("/promotions")
def list_active_promotions(store: StoreDependency) -> list[Product]:
    return store.search_products(ProductSearch(on_promotion=True, limit=20)).products


@app.get("/categories")
def list_categories(store: StoreDependency) -> list[Category]:
    return store.list_categories()


# As consultas de pedido usam POST para o telefone e o e-mail não aparecerem em URLs e logs de acesso.
@app.post("/orders/lookup")
def get_order(lookup: OrderLookup, store: StoreDependency) -> Order:
    order = store.get_order(lookup)
    if order is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado para os dados informados.")
    return order


@app.post("/orders/search")
def list_customer_orders(lookup: CustomerOrdersLookup, store: StoreDependency) -> list[Order]:
    return store.list_customer_orders(lookup)


# POST pelo mesmo motivo dos pedidos: a consulta pode trazer texto do cliente, que não deve ir para logs de URL.
@app.post("/policies/search")
def search_policies(search: PolicySearch, index: PolicyIndexDependency) -> PolicySearchResult:
    return PolicySearchResult(sections=index.search(search.query, search.limit))


@app.post("/escalations", status_code=201)
def create_escalation(request: EscalationRequest, log: EscalationLogDependency) -> EscalationReceipt:
    return log.register(request)
