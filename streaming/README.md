# streaming

Apache Kafka (a message broker: software that lets independent programs publish and
subscribe to streams of events) producers and consumers, replaying the already-
generated `../store_db` history as if it were happening live. See
[PLAN.md](PLAN.md) for the full design rationale (topics, keys, timestamps, the
producer/consumer function shapes).

Requires `../store_db` to already be running (`docker compose up -d` there) — this
project reads from it, it doesn't own that data.

## Setup

```bash
cp .env.example .env   # edit if store_db's credentials/port differ locally
docker compose up -d   # starts Kafka (KRaft mode) + kafka-ui
uv sync
uv run python -m producers.create_topics   # idempotent — creates the 7 topics if missing
```

Open `http://localhost:8089` (kafka-ui) to browse topics/partitions/messages
visually.

## Run

This is built notebook-first, not CLI-flag-first — the point is to run things
interactively, cell by cell, and watch what happens in kafka-ui and in
`data/bronze/` as you go:

- `notebooks/01_replay.ipynb` — `build_timeline()` once, then repeated
  `publish_next(events, limit=..., interval_seconds=..., batch_size=...)` calls.
  Each call resumes exactly where the last one left off.
- `notebooks/02_consume.ipynb` — repeated `consume_batch(limit=..., idle_timeout_seconds=...)`
  calls. Re-running the same cell is the "follow" mechanism.

**Always use a small `limit` (e.g. 10-20) when just verifying things work.**
`limit=None` drains everything currently available — fine once you're actually
replaying the full history on purpose, not while smoke-testing.

Both modules also work as plain scripts (`uv run python -m producers.replay`, `uv
run python -m consumers.bronze_writer` — module form, so the `producers`/`consumers`
packages resolve correctly), reading their defaults from `.env`
(`REPLAY_LIMIT`/`REPLAY_INTERVAL_SECONDS`/`REPLAY_BATCH_SIZE`,
`CONSUME_LIMIT`/`CONSUME_IDLE_TIMEOUT_SECONDS`) — the notebooks are the primary
interface.

## Output

Consumed events land as partitioned Parquet (a columnar file format good for
analytics) under `data/bronze/<topic>/dt=<event date>/*.parquet` — raw/unprocessed
data for the future `../warehouse/` project (dbt + DuckDB) to pick up.
