# store_db — Plan

Seed a Postgres database with a fake single-shop e-commerce dataset, built on top of
the 84 real products sourced in `../catalog_sourcing/`. This is prep data for later
pipeline/RAG/ML phases — not that work itself.

## Why

With a real (if modest) product catalog in hand, the next step is "prephase" data prep:
build a believable relational dataset — suppliers, stock, customers, orders, payments,
shipments, returns, reviews, price history — on top of the real 84 products, so later
phases (streaming, warehouse, ML, agents/RAG) have real relational data and real free
text to work with instead of starting from nothing. Modeled as **one single fake shop**
(not a multi-merchant marketplace): merchants are suppliers we buy stock from, not
competing sellers.

## Sub-project setup

Sibling to `catalog_sourcing/` at the repo root. Own `pyproject.toml`/`uv.lock`/`.venv`
via `uv init --bare --vcs none --no-pin-python --name store_db`, then
`uv add 'psycopg[binary]' python-dotenv faker`.

- `psycopg[binary]` (v3) — modern Postgres driver, no ORM: one-shot seeding job, no
  live app layer yet to justify SQLAlchemy models or migration tooling.
- `python-dotenv` — one `.env` shared by `docker-compose.yml` and the Python scripts.
- `faker` — merchants/customers/reviews text generation.

`docker-compose.yml` (Postgres only, won't collide with a future full-stack compose
file): `postgres:17-alpine`, host port `5433` (avoids colliding with a local default
Postgres on 5432), named volume `store_db_pgdata`, healthcheck via `pg_isready`.

`.env.example` (committed) / `.env` (gitignored):
```
POSTGRES_USER=store_admin
POSTGRES_PASSWORD=changeme
POSTGRES_DB=store_db
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
```

## Schema (`db/schema.sql`, raw DDL — source of truth, no ORM)

Core (supply side → stock → demand side, hub = `products`):
```sql
products (
  upc TEXT PRIMARY KEY, title TEXT NOT NULL, brand TEXT,
  category TEXT NOT NULL,           -- full ">"-delimited path, verbatim from catalog_sourcing
  category_top TEXT NOT NULL,       -- category split on ">", first segment
  attributes JSONB,                 -- rest of the source record (offers excluded)
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

merchants (                          -- suppliers we buy stock from, NOT competing sellers
  id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, country TEXT NOT NULL,
  contact_name TEXT, contact_email TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

consignments (                       -- one stock shipment from one merchant
  id BIGSERIAL PRIMARY KEY, merchant_id BIGINT NOT NULL REFERENCES merchants(id),
  received_date DATE NOT NULL
)
consignment_items (
  id BIGSERIAL PRIMARY KEY,
  consignment_id BIGINT NOT NULL REFERENCES consignments(id) ON DELETE CASCADE,
  product_upc TEXT NOT NULL REFERENCES products(upc),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_cost NUMERIC(10,2) NOT NULL CHECK (unit_cost >= 0)
)

inventory (                          -- materialized current on-hand snapshot
  product_upc TEXT PRIMARY KEY REFERENCES products(upc),
  quantity_on_hand INTEGER NOT NULL DEFAULT 0 CHECK (quantity_on_hand >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

customers (
  id BIGSERIAL PRIMARY KEY, full_name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
  country TEXT NOT NULL, address TEXT, created_at TIMESTAMPTZ NOT NULL  -- backdated signup date
)

orders (
  id BIGSERIAL PRIMARY KEY, customer_id BIGINT NOT NULL REFERENCES customers(id),
  order_date DATE NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('processing','shipped','completed','cancelled'))
)
order_items (
  id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_upc TEXT NOT NULL REFERENCES products(upc),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0)
)
```

Chosen extensions (RAG/ML value + standard e-commerce completeness):
```sql
price_history (                      -- per-product listed-price time series
  id BIGSERIAL PRIMARY KEY, product_upc TEXT NOT NULL REFERENCES products(upc),
  price NUMERIC(10,2) NOT NULL CHECK (price >= 0), effective_from DATE NOT NULL
)
-- order_items.unit_price is looked up from the price_history row effective on
-- order_date (most recent effective_from <= order_date), not computed independently —
-- keeps "what the order charged" consistent with "what was listed that day."

payments (                           -- 1:1 with orders
  id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
  method TEXT NOT NULL CHECK (method IN ('credit_card','paypal','bank_transfer')),
  amount NUMERIC(10,2) NOT NULL CHECK (amount >= 0), paid_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('paid','pending','failed','refunded'))
)

shipments (                          -- 0 or 1 per order; only for shipped/completed orders
  id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
  carrier TEXT NOT NULL, tracking_number TEXT NOT NULL,
  shipped_at TIMESTAMPTZ, delivered_at TIMESTAMPTZ
)

returns (                            -- small % of order_items from shipped/completed orders
  id BIGSERIAL PRIMARY KEY,
  order_item_id BIGINT NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
  reason TEXT NOT NULL, refund_amount NUMERIC(10,2) NOT NULL CHECK (refund_amount >= 0),
  returned_at TIMESTAMPTZ NOT NULL
)

reviews (                            -- subset of completed order_items
  id BIGSERIAL PRIMARY KEY, customer_id BIGINT NOT NULL REFERENCES customers(id),
  product_upc TEXT NOT NULL REFERENCES products(upc),
  rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  review_text TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL
)
```
Deferred (not now): `customer_addresses`, `support_tickets`, `promotions`/
`discount_codes`, `carts`/`cart_items`.

Indexes beyond PK/UNIQUE: `consignment_items(product_upc, consignment_id)`,
`consignments(merchant_id)`, `order_items(product_upc, order_id)`, `orders(customer_id)`,
`products(category_top)`, `price_history(product_upc, effective_from)`,
`returns(order_item_id)`, `reviews(product_upc)`, `reviews(customer_id)`.

## Entity relationships

```
merchants ──1:N── consignments ──1:N── consignment_items ──N:1── products ──1:1── inventory
                                                                      │
customers ──1:N── orders ──1:N── order_items ────────────────────────┘
                     │ 1:1          │ N:1
                     │              ├──N:1── price_history (effective price lookup)
              payments(0/1)         └──0/1── returns
              shipments(0/1)
customers ──1:N── reviews ──N:1── products
```

## Making the fake data look real, not dummy

Confirmed in `products.jsonl`: every one of the 84 real records already carries
`lowest_recorded_price` / `highest_recorded_price` (genuine historical range from the
source API) — this anchors synthetic cost/price generation in something real per
product, rather than pure randomness. Every other table is synthetic, but **nothing is
generated independently** — each one is a function of the real products and/or of
tables generated before it, so the whole database forms one connected, causally
consistent story instead of several unrelated random tables. Guiding rule applied
table-by-table below: **generation-time traits that would act as an answer key for
later ML/analysis (popularity, elasticity, customer segment, anomaly group) stay out of
the schema** — they drive the simulation but must be *inferable* from the resulting
data later, the way a real analyst would discover them, not read off a label column.
Ordinary business facts (a merchant's name, a payment's status) are stored normally.

1. **products** — real data, nothing synthetic here; it's the fixed anchor everything
   else hangs off of.
2. **Per-product demand profile** (generation-time only, not a table): each product
   gets a `popularity_weight` (log-normal/Zipf-like — a few bestsellers, a long tail of
   slow movers) and an `elasticity` — ~85% "normal" (price down → demand up that
   period), ~10% near-zero (price-insensitive goods), ~5% *inverted* (demand up when
   price goes up) — a deliberate, intentional anomaly for later detection work to find.
3. **merchants** — ~10 Faker suppliers, each assigned (at generation time, inferred
   later from their consignments, not stored as a column) 1–3 `category_top`
   specialties and a size tier (small/medium/large) controlling how much volume they
   move. Real distributors specialize; a merchant selling everything to everyone would
   be the dummy version.
4. **consignments / consignment_items** — two realistic phases, not one random pass:
   (a) **initial stocking** at the start of the 12-month window, sized by each
   product's `popularity_weight` (bestsellers get bigger opening batches — suppliers
   order more of what they expect to sell) and sourced only from a merchant whose
   specialty matches that product's category; (b) **reorders mid-simulation**,
   triggered when a product's running stock drops below a simple safety threshold
   while orders are being generated (step 8) — supply responding to demand, not an
   independent schedule. `unit_cost` is derived from that product's own
   `lowest_recorded_price`/`highest_recorded_price` range, not sampled independently.
5. **inventory** — the running counter these phases maintain; a popular product should
   never sit at zero for the whole year (reorders prevent that), and a true slow-mover
   is allowed to end the year overstocked — both outcomes should *emerge*, not be forced.
6. **customers** — Faker profiles, but: signup dates (`created_at`) follow a growth
   curve (more signups in later months) rather than uniform random dates; country
   distribution is skewed toward US/Canada (matching what the catalog-sourcing work
   already found) rather than Faker's flat default; each customer also gets a
   generation-time `activity_weight` (long-tail — a few repeat buyers, most order once
   or twice) and a latent segment — "deal-seeker" (buys disproportionately during price
   dips) vs. "regular" (buys steadily regardless of price) — used only to weight order
   selection, never stored.
7. **price_history** — baseline near the product's own recorded price range, gentle
   downward drift (typical electronics depreciation) plus a shared Nov/Dec promotional
   dip across all products (expected seasonality, not an anomaly); slow-movers
   (low `popularity_weight`) additionally get a deeper "clearance" dip in their last
   couple of months, mirroring real retail behavior of discounting what isn't selling.
8. **orders / order_items** — the core simulation, run month-by-month: expected
   order-line volume for a product in a given month ∝ `popularity_weight ×
   (price_that_month / product's own median price)^(-elasticity) ×
   seasonality_factor(month)`, scaled so total volume lands near ~300 orders — this is
   what makes "most orders happened when the price was lower" an *emergent* property
   instead of a hardcoded fact. Customers are drawn weighted by `activity_weight` and
   segment (deal-seekers preferentially selected in dip months); `unit_price` is looked
   up from `price_history` effective on `order_date` (never computed independently of
   it); nothing is sold past available stock. **Order status is tied to how recent the
   order is**, not an independent random label: orders near the end of the 12-month
   window skew toward `processing`/`shipped`, older orders have had time to resolve to
   `completed`; `cancelled` is driven partly by a simulated payment failure (see next).
9. **payments** — `amount` = that order's line-item sum (never independent);
   `paid_at` follows `order_date` by a short, realistic delay; a small failure rate on
   `paid_at` attempt is *why* some orders end up `cancelled` (causal link from payments
   → order status, not two unrelated random fields pointing the same way by coincidence).
10. **shipments** — only for shipped/completed orders; `shipped_at` is always after that
    order's `paid_at` (can't ship before payment clears), and `delivered_at` adds a
    transit duration that varies with the customer's country (domestic vs.
    international) rather than a flat random range.
11. **returns** — baseline ~5–8% of shipped/completed order_items, boosted when that
    product's price *dropped* shortly after the order (buyer's-remorse pattern); the
    `reason` is drawn weighted by the product's `category_top` (e.g. "defective" more
    likely for electronics with moving parts) instead of uniformly from a flat list.
12. **reviews** — ratings follow a realistic skewed distribution (mostly 4–5★, a
    smaller 1★ cluster, few in between — the real-world J-shape, not uniform 1–5);
    returned items' reviews (when present) skew lower; `review_text` is templated using
    that specific product's `category_top`/`brand`/`title` so the free text actually
    reads as being about the product it's attached to (this is also what makes it worth
    anything as a future RAG corpus) rather than generic Faker filler.

This logic lives entirely in the generation scripts (documented, seeded, reproducible)
— the schema itself stays exactly as defined above with no extra "ground truth" columns.

## Scripts (`scripts/`, run in order, each truncates only the tables it owns —
rerunning the whole sequence twice must produce identical row counts; Faker/`random`
seeded with a fixed constant for reproducibility)

| # | Script | Does |
|---|---|---|
| — | `_db.py` | Shared helper: loads `.env`, builds DSN, context-managed `psycopg` connection. |
| 1 | `01_create_schema.py` | Drops/recreates all tables from `db/schema.sql`. |
| 2 | `02_load_products.py` | Reads `../catalog_sourcing/data/catalog/products.jsonl` (84 rows), upserts into `products` by `upc`, keeps `lowest_recorded_price`/`highest_recorded_price` available (via `attributes` JSONB) for later steps to anchor cost/price generation. |
| 3 | `03_generate_demand_profile.py` | Computes per-product `popularity_weight` + `elasticity` (incl. the ~10% near-zero and ~5% inverted anomaly groups). Not a DB table — writes a small local JSON cache under `data/` so the recipe is reproducible and inspectable, but never loaded into Postgres. |
| 4 | `04_generate_merchants.py` | ~10 Faker suppliers, each assigned 1–3 `category_top` specialties + a size tier (kept in-memory, used by script 5; not a DB column — inferable later from consignment_items). |
| 5 | `05_generate_consignments_and_inventory.py` | Initial stocking phase only: opening consignments sized by `popularity_weight`, sourced from a specialty-matching merchant; seeds `inventory`. Mid-simulation reorders happen inside script 8, not here. |
| 6 | `06_generate_customers.py` | ~150 Faker customers: growth-curve signup dates, US/Canada-skewed country distribution, each with a generation-time `activity_weight` + deal-seeker/regular segment (in-memory only). |
| 7 | `07_generate_price_history.py` | Per product: baseline near its recorded price range, gentle downward drift + shared Nov/Dec dip + extra clearance dip for low-`popularity_weight` products late in the window. |
| 8 | `08_generate_orders.py` | The month-by-month simulation: checks stock vs. a safety threshold and triggers a reorder consignment (specialty-matched merchant) when needed; generates that month's order lines per the demand formula with weighted customer selection; looks up `unit_price` from `price_history`; sets `status` by order recency; creates the matching `payments` row (amount from line items, delay from order_date, occasional failure → feeds `cancelled`) and `shipments` row (timing after `paid_at`, transit length by customer country) per order; writes the final `inventory` snapshot. |
| 9 | `09_generate_returns.py` | ~5–8% baseline return rate on shipped/completed order_items, boosted by a recent price drop (buyer's-remorse), `reason` weighted by `category_top`. |
| 10 | `10_generate_reviews.py` | Subset of completed order_items get a `reviews` row, rating from the skewed real-world distribution (lower if returned), `review_text` templated from that product's own category/brand/title. |
| — | `verify.py` | Rerun-anytime sanity check (row counts, no negative inventory, no oversold product, no orphan orders, FK violation smoke test, plus a correlation sanity print: average order volume in below-median-price months vs. above-median). |

## Directory layout
```
store_db/
├── pyproject.toml / uv.lock / .venv/ (gitignored)
├── docker-compose.yml
├── .env.example / .env (gitignored)
├── README.md
├── PLAN.md
├── db/schema.sql
└── scripts/ (files listed above)
```

## Verification

1. `cd store_db && docker compose up -d`, wait for healthy.
2. `uv run scripts/01_create_schema.py` through `10_generate_reviews.py` in order.
3. `uv run scripts/verify.py` — asserts row counts (`products`=84, others near target),
   no negative `inventory.quantity_on_hand`, no product oversold across order_items vs.
   consignment_items, no orphan orders, FK violation raises as expected.
4. Manual `psql` spot checks (row counts by category/status/merchant, sample inventory).
5. Re-run the whole script sequence a second time; confirm `verify.py` reports identical
   counts (idempotency).
