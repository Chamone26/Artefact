"""Uso, a partir da raiz do repositório: python -m unittest api.test_api"""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app, get_policy_index, get_store
from api.store import Store
from db.etl import build_database
from rag.ingest import build_index
from rag.search import PolicyIndex

# Pedido 15 pertence à cliente 18; o pedido 10, ao cliente 11, cujo e-mail é compartilhado com o cliente 43.
ORDER_15_PHONE = "67999012345"
SHARED_EMAIL = "bruno.martins@jmail.com"
CUSTOMER_11_PHONE = "(67) 98543-2109"
CUSTOMER_43_PHONE = "(67) 99456-3456"


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp_dir.cleanup)
        cls.db_path = Path(tmp_dir.name) / "test.db"
        build_database(cls.db_path)
        sections_path = Path(tmp_dir.name) / "sections.json"
        build_index(sections_path)
        policy_index = PolicyIndex.load(sections_path)
        app.dependency_overrides[get_store] = lambda: Store(cls.db_path)
        app.dependency_overrides[get_policy_index] = lambda: policy_index
        cls.addClassCleanup(app.dependency_overrides.clear)
        cls.client = TestClient(app)

    def search(self, **params):
        response = self.client.get("/products", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def names(self, **params):
        return [product["name"] for product in self.search(**params)["products"]]


class ProductSearchTest(ApiTestCase):
    def test_search_normalizes_accents_and_hyphens_but_does_not_correct_typos(self):
        for query in ("Takamine GD20", "takamine gd-20"):
            with self.subTest(query=query):
                self.assertEqual(self.names(query=query), ["Takamine GD20 Dreadnought Natural"])
        self.assertEqual(self.names(query="tacamine gd20"), [])
        self.assertEqual(self.names(query="GD 20"), ["Takamine GD20 Dreadnought Natural"])

    def test_model_codes_do_not_match_approximately(self):
        self.assertEqual(self.names(query="Takamine GD30"), [])
        self.assertEqual(self.names(query="Martin D-28")[0], "Martin D-28 Dreadnought Natural")
        self.assertEqual(self.names(query="Martin D-28E"), ["Martin D-28E Elétrico Aço Natural"])

    def test_price_comes_with_inactive_promotion_ignored(self):
        product = self.search(query="Takamine GD20")["products"][0]
        self.assertEqual(product["final_price_brl"], 2199.0)
        self.assertIsNone(product["discount_percent"])
        self.assertEqual(product["availability"], "disponivel")

    def test_challenge_question_available_acoustic_guitars_up_to_1000(self):
        result = self.search(category="violões", max_price=1000, available_only=True, limit=20)
        prices = [product["final_price_brl"] for product in result["products"]]
        self.assertEqual(result["total"], 12)
        self.assertEqual(prices, sorted(prices))
        self.assertLessEqual(max(prices), 1000)
        self.assertNotIn("Giannini GF-3D Dreadnought Sunburst", [p["name"] for p in result["products"]])

    def test_price_filter_uses_promotional_price(self):
        names = self.names(query="Ohana CK-20", max_price=450)
        self.assertEqual(names, ["Ohana CK-20 Concert Natural"])  # 549 de tabela, 439,20 com promoção

    def test_unavailable_products_can_still_be_found_and_are_labeled(self):
        expected = {
            "Shelby SN-7C": "descontinuado",
            "Giannini GF-3D": "esgotado",
            "Kala KA-ABP-CTG": "em_breve",
        }
        for query, availability in expected.items():
            with self.subTest(query=query):
                self.assertEqual(self.search(query=query)["products"][0]["availability"], availability)
                self.assertEqual(self.names(query=query, available_only=True), [])

    def test_available_products_come_first(self):
        availability = [p["availability"] for p in self.search(query="Giannini", limit=20)["products"]]
        self.assertEqual(availability, sorted(availability, key=lambda value: value != "disponivel"))

    def test_filters(self):
        products = self.search(category="violões", string_material="aço", has_electronics=True, limit=20)["products"]
        self.assertEqual(len(products), 7)
        self.assertTrue(all(p["string_material"] == "aço" and p["has_electronics"] for p in products))
        self.assertEqual(self.search(query="yamaha", category="violões")["total"], 7)

    def test_brand_is_not_a_filter_or_a_field(self):
        self.assertEqual(self.client.get("/products", params={"brand": "yamaha"}).status_code, 422)
        self.assertNotIn("brand", self.search(query="yamaha")["products"][0])

    def test_query_matches_substrings_in_category_and_description(self):
        self.assertEqual(self.search(query="ukuleles", limit=20)["total"], 15)
        self.assertEqual(self.search(query="ukulele", limit=20)["total"], 15)
        self.assertGreater(self.search(query="violão para iniciantes")["total"], 0)

    def test_query_matches_literal_substrings(self):
        self.assertEqual(self.names(query="Fender Strato"), ["Fender Stratocaster American Pro II"])
        self.assertTrue(any(name.startswith("Kalani ") for name in self.names(query="Kala", limit=20)))

    def test_every_term_must_match(self):
        self.assertEqual(self.search(query="takamine saxofone")["total"], 0)

    def test_limit_keeps_total(self):
        result = self.search(category="violões", limit=3)
        self.assertEqual(len(result["products"]), 3)
        self.assertEqual(result["total"], 35)

    def test_query_text_is_not_executed_as_sql(self):
        self.assertEqual(self.search(query="'; DROP TABLE products; --")["total"], 0)
        self.assertEqual(self.search(category="violões")["total"], 35)

    def test_rejects_invalid_parameters(self):
        for params in ({"min_price": 10, "max_price": 5}, {"limit": 100}, {"max_price": -1}, {"unknown": 1}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/products", params=params).status_code, 422)


class CatalogTest(ApiTestCase):
    def test_promotions_are_only_the_active_ones(self):
        promotions = self.client.get("/promotions").json()
        self.assertEqual(
            {p["name"]: p["discount_percent"] for p in promotions},
            {
                "Crafter HT-100 Folk Aço Natural": 18.0,
                "Taylor 110e Dreadnought Natural": 8.0,
                "Ohana CK-20 Concert Natural": 20.0,
                "Kalani KAL-700T Tenor Natural": 10.0,
            },
        )

    def test_categories_show_the_empty_ones(self):
        counts = {c["name"]: c["product_count"] for c in self.client.get("/categories").json()}
        self.assertEqual(len(counts), 9)
        self.assertEqual(counts["Violões"], 35)
        self.assertEqual(counts["Cordas Orquestrais"], 0)


class OrderAccessTest(ApiTestCase):
    def lookup(self, order_id, phone):
        return self.client.post("/orders/lookup", json={"order_id": order_id, "phone": phone})

    def test_owner_sees_order_with_any_phone_format(self):
        for phone in (ORDER_15_PHONE, "(67) 99901-2345", "+55 67 99901-2345"):
            with self.subTest(phone=phone):
                response = self.lookup(15, phone)
                self.assertEqual(response.status_code, 200, response.text)
                order = response.json()
                self.assertEqual(order["status_label"], "Pendente")
                self.assertEqual(order["installments"], 12)
                self.assertEqual(len(order["items"]), 2)

    def test_wrong_phone_is_indistinguishable_from_missing_order(self):
        other_customer = self.lookup(15, CUSTOMER_11_PHONE)
        missing_order = self.lookup(9999, ORDER_15_PHONE)
        self.assertEqual(other_customer.status_code, 404)
        self.assertEqual(other_customer.json(), missing_order.json())

    def test_order_does_not_expose_contact_data(self):
        response = self.lookup(15, ORDER_15_PHONE)
        body = response.text
        self.assertEqual(response.json()["customer_first_name"], "Aline")
        self.assertNotIn("Monteiro", body)
        self.assertNotIn(ORDER_15_PHONE, body)
        self.assertNotIn("@", body)
        self.assertNotIn("customer_id", body)

    def test_customer_orders_require_phone_and_email_of_the_same_person(self):
        own = self.client.post("/orders/search", json={"phone": CUSTOMER_11_PHONE, "email": SHARED_EMAIL.upper()})
        self.assertEqual([order["order_id"] for order in own.json()], [10])
        shared_email = self.client.post("/orders/search", json={"phone": CUSTOMER_43_PHONE, "email": SHARED_EMAIL})
        self.assertEqual(shared_email.json(), [])

    def test_order_history_is_newest_first(self):
        # Cliente 3 tem os pedidos 1 (2025-10-15) e 19 (2026-02-22).
        with closing(sqlite3.connect(self.db_path)) as con:
            phone, email = con.execute("SELECT phone, email FROM customers WHERE customer_id = 3").fetchone()
        orders = self.client.post("/orders/search", json={"phone": phone, "email": email}).json()
        self.assertEqual([order["order_id"] for order in orders], [19, 1])

    def test_rejects_invalid_input(self):
        self.assertEqual(self.lookup(15, "123").status_code, 422)
        self.assertEqual(self.lookup(0, ORDER_15_PHONE).status_code, 422)
        self.assertEqual(self.client.post("/orders/lookup", json={"order_id": 15}).status_code, 422)
        invalid_email = {"phone": ORDER_15_PHONE, "email": "sem-arroba"}
        self.assertEqual(self.client.post("/orders/search", json=invalid_email).status_code, 422)


class PolicySearchRouteTest(ApiTestCase):
    def search_policies(self, **body):
        return self.client.post("/policies/search", json=body)

    def test_returns_the_relevant_section(self):
        response = self.search_policies(query="arrependimento devolução")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sections"][0]["section"], "4.1")

    def test_respects_limit(self):
        self.assertEqual(len(self.search_policies(query="garantia", limit=1).json()["sections"]), 1)

    def test_no_match_returns_an_empty_list(self):
        self.assertEqual(self.search_policies(query="xilofone quântico").json(), {"sections": []})

    def test_rejects_invalid_input(self):
        for body in ({}, {"query": ""}, {"query": "x", "limit": 50}, {"query": "x", "extra": 1}):
            with self.subTest(body=body):
                self.assertEqual(self.search_policies(**body).status_code, 422)


class StoreTest(unittest.TestCase):
    def test_missing_database_has_clear_error(self):
        with self.assertRaisesRegex(FileNotFoundError, "python -m db.etl"):
            Store("nao_existe.db")

    def test_connection_cannot_write(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            build_database(db_path)
            with Store(db_path)._connect() as con, self.assertRaises(sqlite3.OperationalError):
                con.execute("DELETE FROM products")


if __name__ == "__main__":
    unittest.main()
