"""Consultas somente leitura ao banco, usadas pelas rotas HTTP e, depois, pelas tools do agente."""

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from contracts.schemas import Category, Order, OrderItem, Product, ProductSearchResult
from db.utils import DB_PATH, normalize_text

AVAILABILITY_ORDER = {"disponivel": 0, "em_breve": 1, "esgotado": 2, "descontinuado": 3}
ORDER_STATUS_LABELS = {
    "pending": "Pendente",
    "confirmed": "Confirmado",
    "shipped": "Enviado",
    "delivered": "Entregue",
    "cancelled": "Cancelado",
}

ORDER_QUERY = """
    SELECT o.*, c.name AS customer_name
    FROM orders o JOIN customers c USING (customer_id)
    WHERE c.phone_digits = :phone AND {condition}
    ORDER BY o.order_date DESC, o.order_id DESC
"""


def to_product(row):
    columns = {column: row[column] for column in Product.model_fields if column not in ("specs", "has_electronics")}
    has_electronics = None if row["has_electronics"] is None else bool(row["has_electronics"])
    return Product(**columns, specs=json.loads(row["specs"]), has_electronics=has_electronics)


class Store:
    def __init__(self, db_path=DB_PATH):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.exists():
            raise FileNotFoundError(f"Banco não encontrado em {self.db_path}. Gere-o com: python -m db.etl")

    def _connect(self):
        con = sqlite3.connect(f"{self.db_path.as_uri()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return closing(con)

    def search_products(self, search):
        conditions = ["1 = 1"]
        params = {}
        if search.min_price is not None:
            conditions.append("final_price_brl >= :min_price")
            params["min_price"] = search.min_price
        if search.max_price is not None:
            conditions.append("final_price_brl <= :max_price")
            params["max_price"] = search.max_price
        if search.string_material is not None:
            conditions.append("string_material = :string_material")
            params["string_material"] = search.string_material
        if search.has_electronics is not None:
            conditions.append("has_electronics = :has_electronics")
            params["has_electronics"] = int(search.has_electronics)
        if search.available_only:
            conditions.append("availability = 'disponivel'")
        if search.on_promotion:
            conditions.append("discount_percent IS NOT NULL")

        with self._connect() as con:
            rows = con.execute(f"SELECT * FROM v_products WHERE {' AND '.join(conditions)}", params).fetchall()

        category = normalize_text(search.category or "")
        terms = normalize_text(search.query or "").split()
        products = []
        for row in rows:
            if category and category not in normalize_text(row["category"]):
                continue
            searchable_text = normalize_text(" ".join(filter(None, (
                row["name"], row["category"], row["description"],
                row["color"], row["string_material"],
            ))))
            if terms and not all(term in searchable_text for term in terms):
                continue
            products.append(row)

        products.sort(key=lambda row: (
            AVAILABILITY_ORDER[row["availability"]], row["final_price_brl"], row["product_id"],
        ))
        return ProductSearchResult(total=len(products), products=[to_product(row) for row in products[:search.limit]])

    def list_categories(self):
        with self._connect() as con:
            rows = con.execute("""
                SELECT c.category_id, c.name, c.description, COUNT(p.product_id) AS product_count
                FROM categories c LEFT JOIN products p USING (category_id)
                GROUP BY c.category_id ORDER BY c.name
            """).fetchall()
        return [Category(**dict(row)) for row in rows]

    def get_order(self, lookup):
        """Só devolve o pedido se o telefone for do dono; caso contrário, é como se ele não existisse."""
        orders = self._find_orders("o.order_id = :order_id", phone=lookup.phone, order_id=lookup.order_id)
        return orders[0] if orders else None

    def list_customer_orders(self, lookup):
        """Exige telefone e e-mail do mesmo cliente, pois sem número do pedido há mais dados expostos."""
        return self._find_orders("c.email = :email", phone=lookup.phone, email=lookup.email)

    def _find_orders(self, condition, **params):
        with self._connect() as con:
            rows = con.execute(ORDER_QUERY.format(condition=condition), params).fetchall()
            return [self._to_order(con, row) for row in rows]

    @staticmethod
    def _to_order(con, row):
        items = con.execute(
            "SELECT product_id, product_name, quantity FROM v_order_items WHERE order_id = ? ORDER BY product_id",
            (row["order_id"],),
        ).fetchall()
        fields = {column: row[column] for column in Order.model_fields if column in row.keys()}
        return Order(
            **fields,
            customer_first_name=re.split(r"\s+", row["customer_name"])[0],
            status_label=ORDER_STATUS_LABELS[row["status"]],
            items=[OrderItem(**dict(item)) for item in items],
        )
