# orchestration

Apache Airflow (a workflow scheduler) — automates the one piece of this
chain that's genuinely a repeatable batch job: rebuilding `../warehouse`'s
silver/gold layer. Everything upstream of `warehouse/` (catalog sourcing,
`store_db`, the Kafka replay) stays manual/notebook-driven — this project
only orchestrates the dbt run.

Unlike every other sibling project here, this isn't a `uv`-managed Python
project: Airflow is several long-running services (a web/API server, a
scheduler, its own metadata database), so it's a Docker Compose stack with
a small custom image (`Dockerfile`) that adds `dbt-duckdb` on top of the
official `apache/airflow` image — the DAG's tasks run `dbt` *inside* this
container, not in `warehouse/`'s host-built `.venv`.

## Setup

```bash
cp .env.example .env   # edit the admin password if you care; defaults work for local use
docker compose up -d --build
```

Open `http://localhost:8090` (placeholder port — check for local conflicts
first) and log in with `.env`'s admin credentials.

Then, one-time, in the UI under **Admin → Variables**, add a variable named
`store_db_postgres_password` with the value from `../store_db/.env`'s
`POSTGRES_PASSWORD` — the DAG reads it from there instead of hardcoding it
in the DAG file. (A real deployment would use a Connection + secrets backend
instead of a bare Variable; a Variable is enough for a learning project.)

## Running it

Unpause `warehouse_pipeline` and trigger it manually (there's no schedule —
`store_db` is a static, already fully-generated year, so nothing new arrives
on a timer; see "Why manual" below). It runs two tasks, `dbt_run >> dbt_test`,
against `../warehouse` — identical to running
`cd ../warehouse && dbt run --profiles-dir .` by hand, just via Airflow's UI,
logs, and retry mechanics instead of a terminal.

Safe to re-trigger any time: both `dbt run` and `dbt test` rebuild from
whatever's currently in bronze Parquet + `store_db`, same as running them
directly.

## Why manual, not scheduled

Growing `../catalog_sourcing`'s catalog is a real recurring input, but it
doesn't reach `warehouse/` automatically yet — today a bigger catalog means
manually re-running `store_db`'s full-rebuild seed script and a fresh
`streaming/` replay before `warehouse/` has anything new to pick up. Wiring
that whole chain into one scheduled DAG is a real next step, but `store_db`/
`streaming` would need an *incremental* regeneration path first (append new
data, not regenerate the whole year) — deliberately deferred so this first
pass stays scoped to the one clean, already-repeatable job.

## Notes

- Airflow's own metadata Postgres (DAG runs, task state) is a separate
  container from `store_db`'s app database — not shared, no published host
  port.
- The whole repo root is bind-mounted into the Airflow containers at
  `/opt/airflow/project`, so `warehouse/dbt_project.yml`'s relative
  `bronze_dir: "../streaming/data/bronze"` resolves the same way it does on
  the host.
- `store_db`'s Postgres is reached via `host.docker.internal` (Docker
  Desktop's built-in hostname for the host machine) at the same port
  (`5438`) the host itself uses — `store_db`'s Compose project has no named
  network for this stack to join directly.
