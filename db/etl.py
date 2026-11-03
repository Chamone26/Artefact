"""Lê os CSVs da loja, trata os dados com pandas e gera o banco SQLite usado pelo agente.

Uso, a partir da raiz do repositório: python -m db.etl
"""

import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from db.text import normalize_text

DB_DIR = Path(__file__).parent
DATA_DIR = DB_DIR / "raw_data"
SCHEMA_PATH = DB_DIR / "schema.sql"
DB_PATH = DB_DIR / "emporio.db"
CSV_NAME = "desafio_tecnico_ai_eng - {table}.csv"

# Colunas esperadas em cada CSV, na ordem de carga (tabelas referenciadas primeiro).
SOURCE_COLUMNS = {
    "categories": {"category_id", "name", "description"},
    "products": {"product_id", "price_brl", "name", "category_id", "description",
                 "stock_quantity", "status", "specs", "created_at"},
    "customers": {"customer_id", "name", "phone", "email", "city"},
    "orders": {"order_id", "customer_id", "order_date", "status", "total_brl", "payment_method",
               "tracking_code", "estimated_delivery", "notes"},
    "order_items": {"order_id", "quantity", "product_id"},
    "promotions": {"promotion_id", "product_id", "discount_percent", "description", "is_active"},
}

NAME_FIXES = {"Giannini GN-15 Nylon Cedr Natural": "Giannini GN-15 Nylon Cedro Natural"}
NAME_PREFIXES = ("Bateria Acústica ", "Teclado Sintetizador ")  # vêm antes da marca no nome
MULTI_WORD_BRANDS = ("Music Man",)
COLOR_TRANSLATIONS = {"Black": "Preto", "Red": "Vermelho", "Blue": "Azul", "Wine Red": "Vinho"}
STRING_MATERIALS = {"nylon": "nylon", "steel": "aço"}
ELECTRONICS = {"yes": 1, "no": 0}

# Inconsistências da origem que não dá para corrigir sem inventar dado: o banco mantém o valor
# original e o ETL apenas as reporta.
QUALITY_CHECKS = {
    "Total do pedido difere de quantidade x preço atual": """
        SELECT o.order_id || ': total ' || o.total_brl || ', calculado ' || ROUND(SUM(i.quantity * p.price_brl), 2)
        FROM orders o JOIN order_items i USING (order_id) JOIN products p USING (product_id)
        GROUP BY o.order_id HAVING ABS(o.total_brl - SUM(i.quantity * p.price_brl)) >= 0.01""",
    "E-mail compartilhado por mais de um cliente": """
        SELECT email || ': clientes ' || GROUP_CONCAT(customer_id, ', ')
        FROM customers GROUP BY email HAVING COUNT(*) > 1""",
    "Produto 'em breve' que já consta em pedidos": """
        SELECT p.name || ': pedido ' || i.order_id
        FROM products p JOIN order_items i USING (product_id) WHERE p.status = 'coming_soon'""",
    "Produto descontinuado com estoque": """
        SELECT name || ': estoque ' || stock_quantity
        FROM products WHERE status = 'discontinued' AND stock_quantity > 0""",
    "Categoria sem produtos": """
        SELECT name FROM categories
        WHERE category_id NOT IN (SELECT category_id FROM products)""",
    "Nome do produto contradiz as especificações": """
        SELECT name || ': material ' || string_material || ', eletrônica ' || has_electronics
        FROM products
        WHERE (name LIKE '%Aço%' AND string_material <> 'aço')
           OR (name LIKE '%Nylon%' AND string_material <> 'nylon')
           OR (name LIKE '%Elétrico%' AND has_electronics = 0)""",
}


def extract(table):
    """Lê tudo como texto: os tipos são convertidos nas transformações, que falham se houver valor inválido."""
    path = DATA_DIR / CSV_NAME.format(table=table)
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    if set(df.columns) != SOURCE_COLUMNS[table]:
        raise ValueError(f"{path.name}: colunas inesperadas {list(df.columns)}")
    # Padroniza espaços e troca texto vazio por valor ausente, que vira NULL no banco.
    df = df.apply(lambda column: column.str.replace(r"\s+", " ", regex=True).str.strip())
    return df.mask(df == "")


def parse_brand(name):
    for prefix in NAME_PREFIXES:
        name = name.removeprefix(prefix)
    for brand in MULTI_WORD_BRANDS:
        if name.startswith(brand):
            return brand
    return name.split()[0]


def parse_specs(raw_specs):
    """Separa os atributos usados em filtros; o restante continua em JSON.

    Na origem, 'strings' guarda o material ('nylon') em violões e ukuleles, mas a quantidade ('6')
    nas demais categorias.
    """
    specs = json.loads(raw_specs)
    color = specs.pop("color", None)
    columns = {
        "color": COLOR_TRANSLATIONS.get(color, color),
        "string_material": None,
        "has_electronics": None,
    }
    strings = specs.pop("strings", None)
    if strings in STRING_MATERIALS:
        columns["string_material"] = STRING_MATERIALS[strings]
    elif strings is not None:
        specs["string_count"] = int(strings)
    if "electronics" in specs:
        columns["has_electronics"] = ELECTRONICS[specs.pop("electronics")]
    columns["specs"] = json.dumps(specs, ensure_ascii=False, sort_keys=True)
    return columns


def parse_payment(raw_method):
    """Separa 'credit_6x' em método ('credit') e parcelas (6)."""
    match = re.fullmatch(r"credit_(\d+)x", raw_method)
    if match:
        return {"payment_method": "credit", "installments": int(match.group(1))}
    return {"payment_method": raw_method, "installments": None}


def transform_categories(df):
    return df.assign(
        category_id=df["category_id"].astype(int),
        name_search=df["name"].map(normalize_text),
    )


def transform_products(df):
    name = df["name"].replace(NAME_FIXES)
    specs = pd.DataFrame(df["specs"].map(parse_specs).tolist(), index=df.index)
    return df.drop(columns="specs").join(specs).assign(
        product_id=df["product_id"].astype(int),
        category_id=df["category_id"].astype(int),
        name=name,
        name_search=name.map(normalize_text),
        brand=name.map(parse_brand),
        price_brl=df["price_brl"].astype(float),
        stock_quantity=df["stock_quantity"].astype(int),
        has_electronics=specs["has_electronics"].astype("Int64"),
    )


def transform_customers(df):
    return df.assign(
        customer_id=df["customer_id"].astype(int),
        phone_digits=df["phone"].str.replace(r"\D", "", regex=True),
        email=df["email"].str.casefold(),
    )


def transform_orders(df):
    payment = pd.DataFrame(df["payment_method"].map(parse_payment).tolist(), index=df.index)
    return df.assign(
        order_id=df["order_id"].astype(int),
        customer_id=df["customer_id"].astype(int),
        total_brl=df["total_brl"].astype(float),
        payment_method=payment["payment_method"],
        installments=payment["installments"].astype("Int64"),
    )


def transform_order_items(df):
    return df.astype(int)


def transform_promotions(df):
    return df.astype({
        "promotion_id": int,
        "product_id": int,
        "discount_percent": float,
        "is_active": int,
    })


TRANSFORMS = {
    "categories": transform_categories,
    "products": transform_products,
    "customers": transform_customers,
    "orders": transform_orders,
    "order_items": transform_order_items,
    "promotions": transform_promotions,
}


def quality_report(con):
    report = {title: [row[0] for row in con.execute(query)] for title, query in QUALITY_CHECKS.items()}
    return {title: findings for title, findings in report.items() if findings}


def build_database(db_path=DB_PATH):
    """Gera o banco em um arquivo temporário, para uma falha não deixar um banco pela metade."""
    db_path = Path(db_path)
    tmp_path = db_path.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(tmp_path)) as con:
            con.execute("PRAGMA foreign_keys = ON")
            con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            counts = {}
            for table, transform in TRANSFORMS.items():
                df = transform(extract(table))
                # if_exists="append" preserva as tabelas e restrições criadas pelo schema.sql.
                df.to_sql(table, con, if_exists="append", index=False)
                counts[table] = len(df)
            report = quality_report(con)
        os.replace(tmp_path, db_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return counts, report


def main():
    counts, report = build_database()
    print(f"Banco gerado em {DB_PATH}")
    for table, count in counts.items():
        print(f"  {table}: {count} linhas")
    print("\nAvisos de qualidade (valores mantidos como na origem):")
    for title, findings in report.items():
        print(f"  {title}:")
        for finding in findings:
            print(f"    - {finding}")


if __name__ == "__main__":
    main()
