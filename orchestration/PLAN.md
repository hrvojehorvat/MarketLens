# MarketLens — `orchestration/` (Airflow) Plan

## Context

Learning project for data pipelines, event streaming (Kafka), orchestration (Airflow —
a workflow scheduler for running jobs in order, on a schedule), MLOps, AI agents, and
PyTorch, built on a fake e-commerce electronics shop.

**Already done**, each a sibling "project within project" at repo root:
- `catalog_sourcing/` — real product catalog (284 products) from the UPCitemdb API.
- `store_db/` — Postgres OLTP database: a full fake simulated 2025 year of orders,
  payments, shipments, returns, reviews, seeded on the real catalog.
- `streaming/` — Kafka (KRaft, single broker) historical replay of that year into
  7 topics, consumed into partitioned "bronze" (raw/unprocessed) Parquet files under
  `streaming/data/bronze/`. Replay/consume are deliberately interactive, run cell-by-cell
  from notebooks, not automated — that was a conscious choice for this sub-project, not
  an oversight.
- `warehouse/` — dbt (SQL transformation tool) + DuckDB (embedded analytics database)
  project turning bronze into 8 "silver" (deduplicated, typed) views and 5 "gold"
  (aggregated business marts) tables. `dbt run --profiles-dir .` rebuilds everything
  from whatever's currently in bronze + `store_db`'s Postgres (for product metadata);
  its own README already says "safe to just run it again any time bronze has new data."

**Now**: build `orchestration/` — Apache Airflow, automating the one piece of this
chain that's genuinely a repeatable batch job: rebuilding `warehouse/`'s silver/gold
layer. `store_db` is a static, already-fully-generated year — nothing new arrives on
its own schedule — so this DAG (Directed Acyclic Graph, Airflow's term for an ordered
set of tasks) is **manually triggered** (`schedule=None`), not time-scheduled. The
point is learning Airflow's real mechanics (task dependencies, retries, logging, the
web UI) against a job that's honestly repeatable, not pretending there's live data
that isn't there. Kafka replay/consume stay exactly as they are — manual, notebook-driven
— this project does not touch `streaming/`.

## Why Airflow needs its own Docker Compose stack (not a `uv` sub-project)

Every sibling so far is a `uv init --bare` Python project, optionally with one Postgres/
Kafka container alongside it. Airflow doesn't fit that pattern: it's not a library you
`pip install` and import — it's several long-running services (a webserver, a scheduler,
its own metadata database) that need to be running continuously. So `orchestration/` is
a **Docker Compose stack**, no `pyproject.toml`/`.venv` of its own.

It also needs its own container image with `dbt-duckdb` installed, because the task that
runs `dbt run` executes *inside* the Airflow container, not in `warehouse/`'s `uv`-managed
`.venv` — a `.venv` built for the host's OS/architecture won't reliably work bind-mounted
into a Linux container (DuckDB ships compiled native extensions). So: a small custom
`Dockerfile` extending the official `apache/airflow` image, `pip install`-ing `dbt-duckdb`
pinned to the same version `warehouse/pyproject.toml` already uses.

## Directory layout

```
orchestration/
├── Dockerfile                    # FROM apache/airflow:<latest-3.x>, pip install dbt-duckdb==<pinned>
├── docker-compose.yml            # airflow-postgres (metadata db, internal-only) + airflow-init + webserver + scheduler
├── .env.example / .env           # Airflow admin user/pass, _AIRFLOW_WWW_USER_*, fernet key
├── dags/
│   └── warehouse_pipeline.py     # 1 DAG, 2 tasks: dbt_run >> dbt_test, schedule=None
├── README.md
└── PLAN.md                       # this plan, copied in before coding — same as every prior sub-project
```

## `docker-compose.yml`

- `postgres` — plain `postgres:17-alpine`, dedicated to Airflow's own metadata (DAG runs,
  task state) — **not** shared with `store_db`'s app database, kept on **no published
  host port** (nothing outside the stack needs to reach it).
- `airflow-init` — one-shot container: `airflow db migrate` + creates the admin user from
  `.env`, then exits.
- `airflow-webserver` + `airflow-scheduler` — both built from the local `Dockerfile`,
  `AIRFLOW__CORE__EXECUTOR: LocalExecutor` (simplest real executor — no Celery/Redis
  needed for a single-machine learning setup). Webserver published at host port `8090`
  (placeholder, like every prior sub-project's port — check `docker ps`/`lsof -i :8090`
  for local conflicts before finalizing; `8089` is already kafka-ui's).
- Bind-mounts the **whole repo root** (one level up from `orchestration/`) into each
  Airflow container at `/opt/airflow/project`, read-write (dbt needs to write
  `warehouse.duckdb`/`target/`). `dags/` is mounted at the standard `/opt/airflow/dags`.
  One mount of the whole repo, not several partial ones, so `warehouse/dbt_project.yml`'s
  relative `bronze_dir: "../streaming/data/bronze"` resolves correctly inside the
  container exactly as it does on the host.
- Reaches `store_db`'s Postgres via **`host.docker.internal:5438`**, not a shared Docker
  network — `store_db`'s compose project has no named network to join, and
  `host.docker.internal` (built into Docker Desktop on macOS) reaches the same published
  port the host already uses. This is passed as `POSTGRES_HOST` in the DAG's task
  environment, overriding `warehouse/.env`'s `localhost`.

## `dags/warehouse_pipeline.py`

```python
from airflow import DAG
from airflow.providers.standard.operators.bash import BashOperator
from datetime import datetime

WAREHOUSE_DIR = "/opt/airflow/project/warehouse"
ENV = {
    "POSTGRES_HOST": "host.docker.internal",
    "POSTGRES_PORT": "5438",
    "POSTGRES_DB": "store_db",
    "POSTGRES_USER": "store_admin",
    "POSTGRES_PASSWORD": "{{ var.value.store_db_postgres_password }}",
}

with DAG(
    dag_id="warehouse_pipeline",
    description="Rebuild warehouse/ silver+gold from current bronze Parquet + store_db",
    schedule=None,          # manual trigger only -- bronze/store_db don't change on a timer
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["warehouse", "dbt"],
) as dag:
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"cd {WAREHOUSE_DIR} && dbt run --profiles-dir .",
        env=ENV,
    )
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"cd {WAREHOUSE_DIR} && dbt test --profiles-dir .",
        env=ENV,
    )
    dbt_run >> dbt_test
```

The Postgres password is read from an Airflow **Variable** (`store_db_postgres_password`)
rather than hardcoded in the DAG file — set once via the Airflow UI (Admin → Variables)
or `airflow variables set` after the stack is up. This is the one place this plan
introduces a "how a real project would do this more robustly" note: production Airflow
would use a Connection + a secrets backend instead of a bare Variable, which is out of
scope for a learning project but worth knowing exists.

## `.env.example`

```
AIRFLOW_UID=50000
_AIRFLOW_WWW_USER_USERNAME=admin
_AIRFLOW_WWW_USER_PASSWORD=changeme
AIRFLOW__CORE__FERNET_KEY=
```
(`FERNET_KEY` blank is valid — Airflow generates one at first boot if empty; `README.md`
notes that a stable key should be set and kept once `orchestration/` is used beyond a
single throwaway run, since changing it invalidates anything already encrypted with it.)

## Verification (user-run, per standing project rule — Claude does not execute pipeline
logic, dbt runs, or Airflow tasks; Claude manages Docker containers and does read-only
checks only)

1. `cd orchestration && docker compose up -d --build`, confirm all 4 containers healthy
   (`docker compose ps`), open `http://localhost:8090` (Airflow UI), log in with the
   `.env` admin credentials.
2. Set the `store_db_postgres_password` Variable in the UI (Admin → Variables) to match
   `store_db/.env`'s `POSTGRES_PASSWORD`.
3. In the UI, unpause `warehouse_pipeline`, trigger it manually, watch `dbt_run` → `dbt_test`
   go green in the Graph view; check task logs for `dbt`'s normal run output.
4. Confirm `warehouse/warehouse.duckdb` was actually updated from inside the container's
   run (e.g. compare `gold_daily_revenue`'s row count/`updated` timestamp before/after,
   or just trust the green task + logs).
5. Re-trigger a second time to confirm idempotency (same pattern as every prior
   sub-project's idempotency check) — `dbt run`/`dbt test` are safe to re-run, nothing
   should error on a second pass.

## Explicitly out of scope (deliberate phase 2, not forgotten)

Growing `catalog_sourcing/`'s catalog daily is a real recurring input, but it doesn't
reach `warehouse/` automatically yet: today, a bigger catalog means manually re-running
`store_db`'s full-rebuild seed script, then a fresh `streaming/` replay/consume, before
`warehouse/` has anything new to pick up. Wiring catalog growth → `store_db` → `streaming`
→ `warehouse` into one scheduled chain is a real next step, but `store_db`/`streaming`
would first need an *incremental* regeneration path (append new data, not regenerate the
whole year) — that's its own piece of design work, deliberately deferred so this first
`orchestration/` pass stays scoped to the one clean, already-repeatable job: rebuilding
`warehouse/` from whatever's currently there.
