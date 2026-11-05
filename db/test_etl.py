"""Uso, a partir da raiz do repositório: python -m unittest db.test_etl"""

import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from db.etl import CSV_NAME, DATA_DIR, build_database, parse_payment, parse_specs
from db.utils import normalize_text


def raw_rows(table):
    with open(DATA_DIR / CSV_NAME.format(table=table), encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


class TransformTest(unittest.TestCase):
    def test_normalize_text(self):
        self.assertEqual(normalize_text("Violões"), "violoes")
        self.assertEqual(normalize_text("Giannini GN-15 Aço"), "giannini gn15 aco")
        self.assertEqual(normalize_text("Gibson Les Paul Standard '50s"), "gibson les paul standard 50s")

    def test_parse_specs_separates_string_material_from_count(self):
        acoustic = parse_specs('{"top":"Spruce","strings":"steel","electronics":"yes","color":"Natural"}')
        self.assertEqual(acoustic["string_material"], "aço")
        self.assertEqual(acoustic["has_electronics"], 1)
        self.assertEqual(json.loads(acoustic["specs"]), {"top": "Spruce"})

        electric = parse_specs('{"body": "Ash", "strings": "4", "color": "Black"}')
        self.assertIsNone(electric["string_material"])
        self.assertIsNone(electric["has_electronics"])
        self.assertEqual(electric["color"], "Preto")
        self.assertEqual(json.loads(electric["specs"]), {"body": "Ash", "string_count": 4})

    def test_parse_payment(self):
        self.assertEqual(parse_payment("credit_12x"), {"payment_method": "credit", "installments": 12})
        self.assertEqual(parse_payment("pix"), {"payment_method": "pix", "installments": None})


class DatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp_dir.cleanup)
        cls.counts, cls.report = build_database(Path(cls.tmp_dir.name) / "test.db")
        cls.con = sqlite3.connect(Path(cls.tmp_dir.name) / "test.db")
        cls.addClassCleanup(cls.con.close)

    def scalar(self, query, *params):
        return self.con.execute(query, params).fetchone()[0]

    def test_every_source_row_is_loaded(self):
        for table, count in self.counts.items():
            with self.subTest(table=table):
                self.assertEqual(count, len(raw_rows(table)))
                self.assertEqual(self.scalar(f"SELECT COUNT(*) FROM {table}"), count)

    def test_foreign_keys_are_consistent(self):
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_empty_values_become_null(self):
        self.assertIsNone(self.scalar("SELECT tracking_code FROM orders WHERE order_id = 9"))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders WHERE notes = ''"), 0)

    def test_catalog_has_one_row_per_product(self):
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM v_products"), len(raw_rows("products")))

    def test_availability(self):
        expected = {
            "Giannini GF-3D Dreadnought Sunburst": "esgotado",
            "Shelby SN-7C 7 Cordas Nylon Natural": "descontinuado",
            "Ibanez Bass 2X Electric Bass": "descontinuado",
            "Kala KA-ABP-CTG Barítono Cedar": "em_breve",
            "Yamaha C40 Nylon Natural": "disponivel",
        }
        for name, availability in expected.items():
            with self.subTest(name=name):
                self.assertEqual(self.scalar("SELECT availability FROM v_products WHERE name = ?", name), availability)

    def test_price_ignores_inactive_promotions(self):
        row = self.con.execute(
            "SELECT price_brl, discount_percent, final_price_brl FROM v_products WHERE name_search LIKE '%takamine gd20%'"
        ).fetchone()
        self.assertEqual(row, (2199.0, None, 2199.0))

    def test_price_applies_active_promotion(self):
        row = self.con.execute(
            "SELECT price_brl, discount_percent, promotion, final_price_brl FROM v_products WHERE name LIKE 'Crafter HT-100%'"
        ).fetchone()
        self.assertEqual(row, (2399.0, 18.0, "Desconto Exclusivo", 1967.18))

    def test_challenge_question_available_acoustic_guitars_up_to_1000(self):
        raw_ids = {
            int(row["product_id"]) for row in raw_rows("products")
            if row["category_id"] == "5" and row["status"] == "active"
            and int(row["stock_quantity"]) > 0 and float(row["price_brl"]) <= 1000
        }
        found = {row[0] for row in self.con.execute(
            """SELECT product_id FROM v_products
               WHERE category_search = ? AND availability = 'disponivel' AND final_price_brl <= 1000""",
            (normalize_text("violões"),),
        )}
        self.assertEqual(found, raw_ids)
        self.assertNotIn(96, found)

    def test_quality_report_flags_known_issues(self):
        self.assertEqual(len(self.report["Total do pedido difere de quantidade x preço atual"]), 2)
        self.assertEqual(len(self.report["E-mail compartilhado por mais de um cliente"]), 1)


class ValidationTest(unittest.TestCase):
    def test_database_rejects_invalid_values(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        db_path = Path(tmp_dir.name) / "test.db"
        build_database(db_path)
        invalid_updates = {
            "preço negativo": "UPDATE products SET price_brl = -1 WHERE product_id = 81",
            "status desconhecido": "UPDATE orders SET status = 'lost' WHERE order_id = 1",
            "data inválida": "UPDATE orders SET order_date = '2026-02-31' WHERE order_id = 1",
            "segunda promoção vigente": "UPDATE promotions SET is_active = 1 WHERE promotion_id = 1 OR product_id = 102",
            "crédito sem parcelas": "UPDATE orders SET installments = NULL WHERE order_id = 2",
        }
        with closing(sqlite3.connect(db_path)) as con:
            con.execute("INSERT INTO promotions VALUES (99, 102, 5, 'Teste', 1)")
            for label, statement in invalid_updates.items():
                with self.subTest(label):
                    with self.assertRaises(sqlite3.IntegrityError):
                        con.execute(statement)


if __name__ == "__main__":
    unittest.main()
