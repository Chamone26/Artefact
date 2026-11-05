-- Banco somente leitura do agente: é reconstruído do zero por db/etl.py.
-- STRICT faz o SQLite rejeitar valores do tipo errado, o que ele aceitaria por padrão.

CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    name_search TEXT NOT NULL,  -- sem acento e em minúsculas, para busca
    description TEXT NOT NULL
) STRICT;

CREATE TABLE products (
    product_id      INTEGER PRIMARY KEY,
    category_id     INTEGER NOT NULL REFERENCES categories (category_id),
    name            TEXT NOT NULL UNIQUE,
    name_search     TEXT NOT NULL,  -- sem acento, hífen e maiúsculas, para busca
    description     TEXT NOT NULL,
    price_brl       REAL NOT NULL CHECK (price_brl > 0),
    stock_quantity  INTEGER NOT NULL CHECK (stock_quantity >= 0),
    status          TEXT NOT NULL CHECK (status IN ('active', 'discontinued', 'coming_soon')),
    color           TEXT,
    string_material TEXT CHECK (string_material IN ('nylon', 'aço')),  -- só violões e ukuleles
    has_electronics INTEGER CHECK (has_electronics IN (0, 1)),         -- só violões e ukuleles
    specs           TEXT NOT NULL CHECK (json_valid(specs)),           -- demais atributos, variam por categoria
    created_at      TEXT NOT NULL CHECK (date(created_at) IS created_at)
) STRICT;

CREATE TABLE customers (
    customer_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    phone        TEXT NOT NULL,
    phone_digits TEXT NOT NULL UNIQUE,  -- identifica o cliente; o e-mail não é único na origem
    email        TEXT NOT NULL,
    city         TEXT NOT NULL
) STRICT;

CREATE TABLE orders (
    order_id           INTEGER PRIMARY KEY,
    customer_id        INTEGER NOT NULL REFERENCES customers (customer_id),
    order_date         TEXT NOT NULL CHECK (date(order_date) IS order_date),
    status             TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'shipped', 'delivered', 'cancelled')),
    total_brl          REAL NOT NULL CHECK (total_brl > 0),
    payment_method     TEXT NOT NULL CHECK (payment_method IN ('pix', 'debit', 'credit', 'boleto')),
    installments       INTEGER CHECK (installments > 0),  -- só no crédito
    tracking_code      TEXT CHECK (tracking_code GLOB 'BR?????????BR'),
    estimated_delivery TEXT CHECK (date(estimated_delivery) IS estimated_delivery),
    notes              TEXT,
    CHECK ((payment_method = 'credit') = (installments IS NOT NULL))
) STRICT;

CREATE TABLE order_items (
    order_id   INTEGER NOT NULL REFERENCES orders (order_id),
    product_id INTEGER NOT NULL REFERENCES products (product_id),
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (order_id, product_id)
) STRICT;

CREATE TABLE promotions (
    promotion_id     INTEGER PRIMARY KEY,
    product_id       INTEGER NOT NULL REFERENCES products (product_id),
    discount_percent REAL NOT NULL CHECK (discount_percent > 0 AND discount_percent < 100),
    description      TEXT NOT NULL,
    is_active        INTEGER NOT NULL CHECK (is_active IN (0, 1))
) STRICT;

-- Garante que v_products tenha no máximo uma promoção vigente por produto.
CREATE UNIQUE INDEX one_active_promotion_per_product ON promotions (product_id) WHERE is_active = 1;

-- Catálogo pronto para consulta: disponibilidade e preço final ficam definidos em um só lugar.
CREATE VIEW v_products AS
SELECT
    p.product_id,
    p.name,
    p.name_search,
    p.category_id,
    c.name AS category,
    c.name_search AS category_search,
    p.description,
    p.color,
    p.string_material,
    p.has_electronics,
    p.specs,
    p.status,
    p.stock_quantity,
    CASE
        WHEN p.status = 'discontinued' THEN 'descontinuado'
        WHEN p.status = 'coming_soon' THEN 'em_breve'
        WHEN p.stock_quantity > 0 THEN 'disponivel'
        ELSE 'esgotado'
    END AS availability,
    p.price_brl,
    pr.discount_percent,
    pr.description AS promotion,
    ROUND(p.price_brl * (1 - COALESCE(pr.discount_percent, 0) / 100.0), 2) AS final_price_brl
FROM products p
JOIN categories c USING (category_id)
LEFT JOIN promotions pr ON pr.product_id = p.product_id AND pr.is_active = 1;

CREATE VIEW v_order_items AS
SELECT i.order_id, i.product_id, p.name AS product_name, i.quantity
FROM order_items i
JOIN products p USING (product_id);
