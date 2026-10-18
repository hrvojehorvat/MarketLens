-- MarketLens store_db schema. Source of truth for the fake single-shop e-commerce
-- database. See ../PLAN.md for the rationale behind each table and the generation
-- logic that fills them.

DROP TABLE IF EXISTS reviews CASCADE;
DROP TABLE IF EXISTS returns CASCADE;
DROP TABLE IF EXISTS shipments CASCADE;
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS price_history CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS inventory CASCADE;
DROP TABLE IF EXISTS consignment_items CASCADE;
DROP TABLE IF EXISTS consignments CASCADE;
DROP TABLE IF EXISTS merchants CASCADE;
DROP TABLE IF EXISTS products CASCADE;

CREATE TABLE products (
    upc TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    brand TEXT,
    category TEXT NOT NULL,
    category_top TEXT NOT NULL,
    attributes JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE merchants (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    contact_name TEXT,
    contact_email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE consignments (
    id BIGSERIAL PRIMARY KEY,
    merchant_id BIGINT NOT NULL REFERENCES merchants(id),
    received_date DATE NOT NULL
);

CREATE TABLE consignment_items (
    id BIGSERIAL PRIMARY KEY,
    consignment_id BIGINT NOT NULL REFERENCES consignments(id) ON DELETE CASCADE,
    product_upc TEXT NOT NULL REFERENCES products(upc),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost NUMERIC(10, 2) NOT NULL CHECK (unit_cost >= 0)
);

CREATE TABLE inventory (
    product_upc TEXT PRIMARY KEY REFERENCES products(upc),
    quantity_on_hand INTEGER NOT NULL DEFAULT 0 CHECK (quantity_on_hand >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE customers (
    id BIGSERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    country TEXT NOT NULL,
    address TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    order_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'shipped', 'completed', 'cancelled'))
);

CREATE TABLE order_items (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_upc TEXT NOT NULL REFERENCES products(upc),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0)
);

CREATE TABLE price_history (
    id BIGSERIAL PRIMARY KEY,
    product_upc TEXT NOT NULL REFERENCES products(upc),
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    effective_from DATE NOT NULL
);

CREATE TABLE payments (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    method TEXT NOT NULL CHECK (method IN ('credit_card', 'paypal', 'bank_transfer')),
    amount NUMERIC(10, 2) NOT NULL CHECK (amount >= 0),
    paid_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('paid', 'pending', 'failed', 'refunded'))
);

CREATE TABLE shipments (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    carrier TEXT NOT NULL,
    tracking_number TEXT NOT NULL,
    shipped_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ
);

CREATE TABLE returns (
    id BIGSERIAL PRIMARY KEY,
    order_item_id BIGINT NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    refund_amount NUMERIC(10, 2) NOT NULL CHECK (refund_amount >= 0),
    returned_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE reviews (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    product_upc TEXT NOT NULL REFERENCES products(upc),
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_consignment_items_product ON consignment_items(product_upc, consignment_id);
CREATE INDEX idx_consignments_merchant ON consignments(merchant_id);
CREATE INDEX idx_order_items_product ON order_items(product_upc, order_id);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_products_category_top ON products(category_top);
CREATE INDEX idx_price_history_product ON price_history(product_upc, effective_from);
CREATE INDEX idx_returns_order_item ON returns(order_item_id);
CREATE INDEX idx_reviews_product ON reviews(product_upc);
CREATE INDEX idx_reviews_customer ON reviews(customer_id);
