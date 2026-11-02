"""API HTTP de dados da loja.

Uso, a partir da raiz do repositório: uvicorn api.main:app --reload
"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from api.schemas import Category, CustomerOrdersLookup, Order, OrderLookup, Product, ProductSearch, ProductSearchResult
from api.store import Store

app = FastAPI(title="Empório da Música: API de dados")


def get_store():
    return Store()


StoreDependency = Annotated[Store, Depends(get_store)]


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
