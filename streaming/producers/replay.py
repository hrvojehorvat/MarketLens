"""Historical replay producer.

store_db is a *static*, already fully-generated year (2025-01-01 -> 2025-12-31) —
not a live system. So instead of waiting for real events, this reads every
event-bearing row out of Postgres in true chronological order and republishes it
to Kafka as if it were happening live.

Two functions, meant to be called from a notebook cell by cell (see
notebooks/01_replay.ipynb):

- build_timeline() — queries every source table once, merges everything into one
  chronologically sorted list of (timestamp, topic, key, payload) tuples, and
  returns an iterator over it. Call this once per session.
- publish_next(events, ...) — pulls from that shared iterator and publishes to
  Kafka. Call it again later with the same iterator to resume exactly where the
  last call left off, instead of restarting from day one.
"""

import datetime
import json
import os
import time
from collections import defaultdict
from itertools import islice

from confluent_kafka import Producer
from dotenv import load_dotenv

from producers._config import KAFKA_BOOTSTRAP_SERVERS
from producers._db import get_conn

load_dotenv(__import__("pathlib").Path(__file__).resolve().parent.parent / ".env")

_producer: Producer | None = None


def _get_producer() -> Producer:
    global _producer
    if _producer is None:
        _producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    return _producer


def _midnight(d: datetime.date) -> datetime.datetime:
    # TIMESTAMPTZ columns (paid_at, shipped_at, returned_at, created_at, ...) come
    # back from Postgres as timezone-aware datetimes. Plain DATE columns don't carry
    # a timezone at all, so this needs to pick one explicitly (UTC) to stay
    # comparable with the aware ones when the merged timeline gets sorted.
    return datetime.datetime.combine(d, datetime.time.min, tzinfo=datetime.UTC)


def _envelope(topic: str, ts: datetime.datetime, payload: dict) -> dict:
    return {"event_type": topic, "event_ts": ts.isoformat(), **payload}


def _orders_placed(conn) -> list[tuple]:
    sql = """
        SELECT o.id AS order_id, o.customer_id, o.order_date, o.status,
               array_agg(
                   json_build_object(
                       'product_upc', oi.product_upc,
                       'quantity', oi.quantity,
                       'unit_price', oi.unit_price
                   )
               ) AS items
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id
        GROUP BY o.id, o.customer_id, o.order_date, o.status
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    events = []
    for row in rows:
        ts = _midnight(row["order_date"])
        key = str(row["customer_id"])
        payload = _envelope("orders.placed", ts, row)
        events.append((ts, "orders.placed", key, payload))
    return events


def _payments_processed(conn) -> list[tuple]:
    sql = """
        SELECT id AS payment_id, order_id, method, amount, paid_at, status
        FROM payments
        WHERE status = 'paid' AND paid_at IS NOT NULL
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    events = []
    for row in rows:
        ts = row["paid_at"]
        key = str(row["order_id"])
        payload = _envelope("payments.processed", ts, row)
        events.append((ts, "payments.processed", key, payload))
    return events


def _shipments_status_changed(conn) -> list[tuple]:
    sql = """
        SELECT id AS shipment_id, order_id, carrier, tracking_number,
               shipped_at, delivered_at
        FROM shipments
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    events = []
    for row in rows:
        key = str(row["order_id"])
        if row["shipped_at"] is not None:
            payload = _envelope(
                "shipments.status_changed",
                row["shipped_at"],
                {**row, "status": "shipped"},
            )
            events.append((row["shipped_at"], "shipments.status_changed", key, payload))
        if row["delivered_at"] is not None:
            payload = _envelope(
                "shipments.status_changed",
                row["delivered_at"],
                {**row, "status": "delivered"},
            )
            events.append((row["delivered_at"], "shipments.status_changed", key, payload))
    return events


def _price_changed(conn) -> list[tuple]:
    sql = """
        SELECT id AS price_history_id, product_upc, price, effective_from
        FROM price_history
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    events = []
    for row in rows:
        ts = _midnight(row["effective_from"])
        key = row["product_upc"]
        payload = _envelope("price.changed", ts, row)
        events.append((ts, "price.changed", key, payload))
    return events


def _inventory_restocked(conn) -> list[tuple]:
    sql = """
        SELECT ci.id AS consignment_item_id, ci.consignment_id, c.merchant_id,
               ci.product_upc, ci.quantity, ci.unit_cost, c.received_date
        FROM consignment_items ci
        JOIN consignments c ON c.id = ci.consignment_id
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    events = []
    for row in rows:
        ts = _midnight(row["received_date"])
        key = row["product_upc"]
        payload = _envelope("inventory.restocked", ts, row)
        events.append((ts, "inventory.restocked", key, payload))
    return events


def _returns_filed(conn) -> list[tuple]:
    sql = """
        SELECT r.id AS return_id, oi.order_id, r.order_item_id, r.reason,
               r.refund_amount, r.returned_at
        FROM returns r
        JOIN order_items oi ON oi.id = r.order_item_id
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    events = []
    for row in rows:
        ts = row["returned_at"]
        key = str(row["order_id"])
        payload = _envelope("returns.filed", ts, row)
        events.append((ts, "returns.filed", key, payload))
    return events


def _reviews_posted(conn) -> list[tuple]:
    sql = """
        SELECT id AS review_id, customer_id, product_upc, rating, review_text,
               created_at
        FROM reviews
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    events = []
    for row in rows:
        ts = row["created_at"]
        key = row["product_upc"]
        payload = _envelope("reviews.posted", ts, row)
        events.append((ts, "reviews.posted", key, payload))
    return events


def build_timeline():
    """Query every event source once and return an iterator over the merged,
    chronologically sorted timeline. Call once per session; reuse the same
    iterator across repeated publish_next() calls so each call resumes where
    the last one left off."""
    with get_conn() as conn:
        events: list[tuple] = []
        events += _orders_placed(conn)
        events += _payments_processed(conn)
        events += _shipments_status_changed(conn)
        events += _price_changed(conn)
        events += _inventory_restocked(conn)
        events += _returns_filed(conn)
        events += _reviews_posted(conn)

    events.sort(key=lambda e: (e[0], e[1], e[2]))
    print(f"Timeline built: {len(events)} events total.")
    return iter(events)


def publish_next(events, limit=None, interval_seconds=0, batch_size=1) -> dict:
    """Publish the next messages pulled from `events` (the iterator returned by
    build_timeline()).

    - limit: how many messages this call publishes. None = drain everything
      currently left in the timeline, as fast as possible.
    - interval_seconds: real seconds to sleep between batches. 0 = no pacing.
    - batch_size: how many messages go out before each sleep (default 1).

    Returns a per-topic count of what this call actually published.
    """
    producer = _get_producer()
    counts: dict[str, int] = defaultdict(int)
    published = 0

    while limit is None or published < limit:
        remaining = batch_size if limit is None else min(batch_size, limit - published)
        batch = list(islice(events, remaining))
        if not batch:
            break

        for _, topic, key, payload in batch:
            producer.produce(
                topic,
                key=key.encode("utf-8"),
                value=json.dumps(payload, default=str).encode("utf-8"),
            )
            counts[topic] += 1
            published += 1

        producer.poll(0)
        if interval_seconds > 0:
            time.sleep(interval_seconds)

    producer.flush()

    print(f"Published {published} messages this call:")
    for topic, n in sorted(counts.items()):
        print(f"  {topic}: {n}")

    return dict(counts)


if __name__ == "__main__":
    _limit_raw = os.environ.get("REPLAY_LIMIT", "").strip()
    _limit = int(_limit_raw) if _limit_raw else None
    _interval = float(os.environ.get("REPLAY_INTERVAL_SECONDS", "0") or 0)
    _batch_size = int(os.environ.get("REPLAY_BATCH_SIZE", "1") or 1)

    _timeline = build_timeline()
    publish_next(_timeline, limit=_limit, interval_seconds=_interval, batch_size=_batch_size)
