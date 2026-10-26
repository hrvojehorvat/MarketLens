# streaming — Plan

Apache Kafka (a message broker: software that lets independent programs publish and
subscribe to streams of events) producers and consumers, learning event-streaming
concepts on top of the already-generated `../store_db` history.

## Key framing decision

`store_db` is a *static*, already fully-generated historical year (2025-01-01 ->
2025-12-31) — not a live system that changes in real time. So this project is built
as a **historical replay**: a producer reads every event-bearing row out of Postgres
in true chronological order and publishes it to Kafka as if it were happening live.
This is an honest, realistic pattern and gives real producer/consumer mechanics to
learn against real relational data, instead of needing a live app to generate events.

## Topics & event design

Each topic models one real e-commerce event type, keyed for sensible partitioning
(splitting a topic into ordered lanes; messages with the same key always land in the
same partition, preserving order for that key):

| Topic | Source table(s) | Keyed by | Timestamp used |
|---|---|---|---|
| `orders.placed` | `orders` + `order_items` | `customer_id` | `order_date` |
| `payments.processed` | `payments` | `order_id` | `paid_at` |
| `shipments.status_changed` | `shipments` (2 events: shipped, delivered) | `order_id` | `shipped_at` / `delivered_at` |
| `price.changed` | `price_history` | `product_upc` | `effective_from` |
| `inventory.restocked` | `consignments` + `consignment_items` | `product_upc` | `received_date` |
| `returns.filed` | `returns` | `order_id` (via order_item) | `returned_at` |
| `reviews.posted` | `reviews` | `product_upc` | `created_at` |

Each topic gets 3 partitions.

## Producer: `producers/replay.py`

Importable module, not a CLI tool — built to be called cell-by-cell from a notebook:

- `build_timeline()` — queries all 7 sources once, merges everything into one
  chronologically sorted list, and returns an iterator over it. Call once per
  session.
- `publish_next(events, limit=None, interval_seconds=0, batch_size=1)` — pulls from
  that shared iterator (so repeated calls resume where the last one left off) and
  publishes to Kafka. `limit=None` drains everything left right now.
  `interval_seconds` paces between batches of `batch_size` messages.

`producers/create_topics.py` — idempotent setup script, creates the 7 topics with 3
partitions each if they don't already exist.

## Consumer: `consumers/bronze_writer.py`

- `consume_batch(limit=None, idle_timeout_seconds=2)` — pulls from Kafka using one
  long-lived consumer (kept alive across calls, so its committed offset naturally
  continues), buffers per topic, and micro-batches: flushes each topic's buffer to
  partitioned Parquet (a columnar file format good for analytics) under
  `data/bronze/<topic>/dt=<event date>/*.parquet`. Stops once it hits `limit`
  messages or goes `idle_timeout_seconds` with nothing new to read.

Re-running the same `consume_batch()` cell is the "follow" mechanism — no infinite
loop needed, which also matches running things step by step in Jupyter.

## Verification

1. `docker compose up -d`, confirm `kafka` healthy, open `http://localhost:8089`
   (kafka-ui) in a browser.
2. `uv run python -m producers.create_topics` — confirm 7 topics appear in kafka-ui.
3. **Small-limit smoke test only** — never run an unlimited drain while verifying:
   `notebooks/01_replay.ipynb` → `publish_next(events, limit=20)`, confirm messages
   visible in kafka-ui, then `notebooks/02_consume.ipynb` → `consume_batch(limit=20)`,
   confirm Parquet files under `data/bronze/`.
4. **Live demo**: run a paced `publish_next(events, limit=30, interval_seconds=3)`
   in one notebook while re-running `consume_batch()` in the other — watch Parquet
   files appear a little at a time.
5. Re-run `create_topics.py` to confirm idempotency (topics not duplicated).
