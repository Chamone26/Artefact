"""
Lê os CSVs da loja, trata os dados com pandas e gera o banco SQLite usado pelo agente.

python -m db.etl
"""

import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Union

import pandas as pd

from db.utils import DB_PATH, normalize_text


DB_DIR = Path(__file__).parent
DATA_DIR = DB_DIR / "raw_data"
SCHEMA_PATH = DB_DIR / "schema.sql"

CSV_NAME = "{table}.csv"


NAME_FIXES = {"Giannini GN-15 Nylon Cedr Natural": "Giannini GN-15 Nylon Cedro Natural"}
COLOR_TRANSLATIONS = {"Black": "Preto", "Red": "Vermelho", "Blue": "Azul", "Wine Red": "Vinho"}
STRING_MATERIALS = {"nylon": "nylon", "steel": "aço"}
ELECTRONICS = {"yes": 1, "no": 0}

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

def extract(table: str) -> pd.DataFrame:
    """Lê o CSV de uma tabela e padroniza os espaços de seus campos.

    Os valores são mantidos como texto para que as funções de transformação
    controlem as conversões de tipo.

    Args:
        table: Nome da tabela e do arquivo CSV correspondente em ``raw_data``.

    Returns:
        DataFrame com os dados do CSV e espaços consecutivos reduzidos.
    """
    path = DATA_DIR / CSV_NAME.format(table=table)
    
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    
    # Padroniza espaços; campos vazios devem virar NULL para respeitar o schema.
    df = df.apply(lambda column: column.str.replace(r"\s+", " ", regex=True).str.strip())
    df = df.replace("", None)
    return df


def parse_specs(raw_specs: str) -> dict[str, object]:
    """Separa especificações em colunas filtráveis e JSON com os atributos restantes.

    Na origem, 'strings' guarda o material ('nylon') em violões e ukuleles, mas a quantidade ('6')
    nas demais categorias.

    Args:
        raw_specs: Objeto JSON de especificações do produto, serializado como texto.

    Returns:
        Mapeamento com ``color``, ``string_material``, ``has_electronics`` e
        ``specs`` serializado com as especificações que não foram separadas.
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


def parse_payment(raw_method: str) -> dict[str, Union[str, int, None]]:
    """Separa o método de pagamento e o número de parcelas, quando informado.

    Args:
        raw_method: Método original, como ``credit_6x`` ou ``pix``.

    Returns:
        Mapeamento com ``payment_method`` e ``installments``. Métodos que não
        correspondem ao formato ``credit_Nx`` são mantidos e recebem parcelas
        nulas.
    """
    match = re.fullmatch(r"credit_(\d+)x", raw_method)
    if match:
        return {"payment_method": "credit", "installments": int(match.group(1))}
    return {"payment_method": raw_method, "installments": None}


def transform_categories(df: pd.DataFrame) -> pd.DataFrame:
    """Converte categorias para os tipos do banco e cria o nome normalizado.

    Args:
        df: Dados brutos de categorias.

    Returns:
        DataFrame com ``category_id`` inteiro e a coluna ``name_search``.
    """
    return df.assign(
        category_id=df["category_id"].astype(int),
        name_search=df["name"].map(normalize_text),
    )


def transform_products(df: pd.DataFrame) -> pd.DataFrame:
    """Converte produtos e suas especificações para as colunas do banco.

    Aplica a correção de nome conhecida, extrai atributos de ``specs`` e
    calcula os campos auxiliares usados em buscas e filtros.

    Args:
        df: Dados brutos de produtos.

    Returns:
        DataFrame transformado com IDs e valores numéricos tipados, além dos
        campos ``name_search`` e atributos extraídos.
    """
    name = df["name"].replace(NAME_FIXES)
    specs = pd.DataFrame(df["specs"].map(parse_specs).tolist(), index=df.index)
    return df.drop(columns="specs").join(specs).assign(
        product_id=df["product_id"].astype(int),
        category_id=df["category_id"].astype(int),
        name=name,
        name_search=name.map(normalize_text),
        price_brl=df["price_brl"].astype(float),
        stock_quantity=df["stock_quantity"].astype(int),
        has_electronics=specs["has_electronics"].astype("Int64"),
    )


def transform_customers(df: pd.DataFrame) -> pd.DataFrame:
    """Converte IDs de clientes e cria versões normalizadas de telefone e e-mail.

    Args:
        df: Dados brutos de clientes.

    Returns:
        DataFrame com ``customer_id`` inteiro, ``phone_digits`` sem pontuação
        e e-mail convertido para minúsculas.
    """
    return df.assign(
        customer_id=df["customer_id"].astype(int),
        phone_digits=df["phone"].str.replace(r"\D", "", regex=True),
        email=df["email"].str.casefold(),
    )
 

def transform_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Converte pedidos e separa o método de pagamento de suas parcelas.

    Args:
        df: Dados brutos de pedidos.

    Returns:
        DataFrame com IDs e total numéricos, método de pagamento normalizado
        e ``installments`` inteiro anulável.
    """
    payment = pd.DataFrame(df["payment_method"].map(parse_payment).tolist(), index=df.index)
    return df.assign(
        order_id=df["order_id"].astype(int),
        customer_id=df["customer_id"].astype(int),
        total_brl=df["total_brl"].astype(float),
        payment_method=payment["payment_method"],
        installments=payment["installments"].astype("Int64"),
    )


def transform_order_items(df: pd.DataFrame) -> pd.DataFrame:
    """Converte todas as colunas dos itens de pedido para inteiros.

    Args:
        df: Dados brutos dos itens de pedido.

    Returns:
        DataFrame com todas as colunas convertidas para o tipo inteiro.
    """
    return df.astype(int)


def transform_promotions(df: pd.DataFrame) -> pd.DataFrame:
    """Converte IDs, percentual de desconto e indicador de atividade das promoções.

    Args:
        df: Dados brutos de promoções.

    Returns:
        DataFrame com IDs e ``is_active`` inteiros e ``discount_percent``
        convertido para ponto flutuante.
    """
    return df.astype({
        "promotion_id": int,
        "product_id": int,
        "discount_percent": float,
        "is_active": int,
    })


TRANSFORMS: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
    "categories": transform_categories,
    "products": transform_products,
    "customers": transform_customers,
    "orders": transform_orders,
    "order_items": transform_order_items,
    "promotions": transform_promotions,
}


def quality_report(con: sqlite3.Connection) -> dict[str, list[str]]:
    """Executa as verificações de qualidade e retorna apenas as que encontraram problemas.

    Args:
        con: Conexão SQLite com as tabelas carregadas.

    Returns:
        Mapeamento entre a descrição de cada verificação e suas ocorrências;
        verificações sem ocorrências são omitidas.
    """
    report = {title: [row[0] for row in con.execute(query)] for title, query in QUALITY_CHECKS.items()}
    return {title: findings for title, findings in report.items() if findings}


def build_database(db_path = DB_PATH) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Cria o banco SQLite a partir dos CSVs e valida a qualidade dos dados.

    O banco é montado em um arquivo temporário e substitui o destino somente
    após a carga e o relatório terminarem.

    Args:
        db_path: Caminho do arquivo SQLite a gerar. Por padrão, usa ``DB_PATH``.

    Returns:
        Tupla com as contagens de linhas carregadas por tabela e o relatório
        das verificações de qualidade.
    """

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


def main() -> None:
    """Gera o banco padrão e imprime as contagens e os avisos de qualidade."""
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
