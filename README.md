# MarketLens

An end-to-end data platform on a simulated e-commerce electronics shop: real
product data → Postgres → Kafka event stream → dbt/DuckDB warehouse →
Airflow orchestration. A learning project, built to production standards
(idempotent scripts, Docker, tests).

```
catalog_sourcing/ → store_db/ → streaming/ → warehouse/ ← orchestration/
```

Each folder is its own sibling project — see its README for details.

| Project | What it does |
|---|---|
| [`catalog_sourcing/`](catalog_sourcing) | Real product catalog via a public API |
| [`store_db/`](store_db) | Postgres: a simulated year of orders, inventory, reviews |
| [`streaming/`](streaming) | Kafka replay of that year into raw ("bronze") Parquet |
| [`warehouse/`](warehouse) | dbt + DuckDB: bronze → silver/gold models |
| [`orchestration/`](orchestration) | Airflow DAG to rebuild the warehouse on demand |

## Run it

```bash
cd store_db && docker compose up -d && uv sync && bash scripts/run_all.sh
cd ../streaming && docker compose up -d && uv sync && uv run python -m producers.create_topics
# then notebooks/01_replay.ipynb and 02_consume.ipynb
cd ../warehouse && uv sync && uv run dbt run --profiles-dir .
# or: cd ../orchestration && docker compose up -d --build   (same rebuild, via Airflow UI)
```

Each step needs a `.env` from that folder's `.env.example` first.
