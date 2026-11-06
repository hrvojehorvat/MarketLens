# warehouse

dbt (a SQL transformation tool) + DuckDB (an embedded analytics database),
turning `../streaming/data/bronze/` into the silver and gold layers of the
bronze/silver/gold ("medallion") architecture.

Requires `../store_db` running (for `silver_products`/`gold_return_rate`,
which read product/category data straight from it) and at least one replay
through `../streaming` so there's bronze Parquet to read.

## Layers

- **Bronze** — already exists: raw Parquet under `../streaming/data/bronze/`,
  written by `../streaming/consumers/bronze_writer.py`. Not a dbt model at all,
  just files on disk.
- **Silver** (`models/silver/`) — one model per bronze topic: deduplicated
  (multiple smoke-test replays can republish the same event), typed, and
  lightly reshaped (e.g. `silver_orders` unnests one row per order line item).
  `silver_products` is the one silver model that doesn't read from bronze —
  product/category metadata was never part of any event payload, so it reads
  directly from `store_db`'s Postgres via DuckDB's `postgres` extension
  (configured in `profiles.yml`).
- **Gold** (`models/gold/`) — small aggregated marts built for actual
  analysis: daily revenue, a price-elasticity feature set (units sold per
  product per day, joined to whatever price was active that day), inventory
  turnover, return rate, and review ratings.

## Setup

```bash
cp .env.example .env   # edit if store_db's credentials/port differ locally
uv sync
```

dbt doesn't load `.env` files itself, so export those vars into the shell
before running dbt:

```bash
set -a && source .env && set +a
uv run dbt run --profiles-dir .
```

Re-run that `dbt run` any time bronze has new data (e.g. after another replay)
— every model rebuilds from whatever's currently in `data/bronze/` and
`store_db`, so it's always safe to just run it again.

## Explore the output

```bash
uv run dbt docs generate --profiles-dir . && uv run dbt docs serve --profiles-dir .
```

or query `warehouse.duckdb` directly:

```bash
uv run python -c "import duckdb; print(duckdb.connect('warehouse.duckdb').sql('select * from gold_daily_revenue').df())"
```
