# store_db

Seeds a Postgres database with a fake single-shop e-commerce dataset, built on top of
the 84 real products sourced in `../catalog_sourcing/`. Prep data for later
pipeline/RAG/ML phases of the MarketLens project. See [PLAN.md](PLAN.md) for the full
design rationale (schema, entity relationships, and the generation logic behind every
table).

## Setup

```bash
cp .env.example .env   # edit if you want different credentials/port
docker compose up -d
uv sync
```

## Run

Run the scripts in order from `store_db/`:

```bash
uv run scripts/01_create_schema.py
uv run scripts/02_load_products.py
uv run scripts/03_generate_demand_profile.py
uv run scripts/04_generate_merchants.py
uv run scripts/05_generate_consignments_and_inventory.py
uv run scripts/06_generate_customers.py
uv run scripts/07_generate_price_history.py
uv run scripts/08_generate_orders.py
uv run scripts/09_generate_returns.py
uv run scripts/10_generate_reviews.py
uv run scripts/verify.py
```

The whole sequence is seeded (`SEED` in `scripts/_config.py`) and idempotent -- each
script truncates only the tables it owns, so re-running 01-10 reproduces identical row
counts.

`scripts/verify.py` can be rerun any time afterwards as a sanity check (row counts, no
negative inventory, no oversold product, no orphan orders, FK constraint smoke test,
and a quick price/order-volume correlation print).
