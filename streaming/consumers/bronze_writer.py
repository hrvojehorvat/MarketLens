"""Bronze (raw/unprocessed) layer consumer.

One function, meant to be called repeatedly from a notebook cell (see
notebooks/02_consume.ipynb): each call reuses the same long-lived Kafka consumer,
so its committed offset naturally continues from the last call -- calling the
function again is the "follow" mechanism, instead of an infinite --follow loop.

consume_batch() buffers incoming messages per topic and flushes them as
partitioned Parquet (a columnar file format good for analytics) files under
data/bronze/<topic>/dt=<event date>/*.parquet, feeding the future warehouse/
project (dbt (a SQL transformation tool) + DuckDB (an embedded analytics
database)).
"""

import json
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from confluent_kafka import Consumer
from dotenv import load_dotenv
from producers._config import KAFKA_BOOTSTRAP_SERVERS, TOPICS

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BRONZE_DIR = Path(__file__).resolve().parent.parent / "data" / "bronze"
GROUP_ID = "bronze-writer"

_consumer: Consumer | None = None


def _get_consumer() -> Consumer:
    global _consumer
    if _consumer is None:
        _consumer = Consumer(
            {
                "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
                "group.id": GROUP_ID,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        _consumer.subscribe(list(TOPICS.keys()))
    return _consumer


def _flush(buffers: dict) -> dict:
    """Write each topic's buffered rows to Parquet, partitioned by the event's
    own date (event_ts) rather than wall-clock ingestion time -- bronze should
    mirror when things happened in the replay, not when we happened to read
    them off Kafka."""
    written = {}
    for topic, rows in buffers.items():
        if not rows:
            continue

        by_date = defaultdict(list)
        for row in rows:
            event_date = row["event_ts"][:10]
            by_date[event_date].append(row)

        paths = []
        for event_date, date_rows in by_date.items():
            out_dir = BRONZE_DIR / topic / f"dt={event_date}"
            out_dir.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pylist(date_rows)
            filename = f"part-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}.parquet"
            out_path = out_dir / filename
            pq.write_table(table, out_path)
            paths.append(str(out_path.relative_to(BRONZE_DIR)))
        written[topic] = paths
    return written


def consume_batch(limit=None, idle_timeout_seconds=2) -> dict:
    """Pull and land the next batch of messages.

    - limit: how many messages this call consumes. None = keep going until
      idle_timeout_seconds passes with nothing new to read.
    - idle_timeout_seconds: stop once this many seconds pass without a new
      message, whichever comes first against `limit`.

    Returns a per-topic count of what this call consumed (and where it wrote).
    """
    consumer = _get_consumer()
    buffers: dict = defaultdict(list)
    consumed = 0
    last_message_time = time.monotonic()

    while limit is None or consumed < limit:
        msg = consumer.poll(timeout=1.0)

        if msg is None:
            if time.monotonic() - last_message_time >= idle_timeout_seconds:
                break
            continue

        if msg.error():
            print(f"Consumer error: {msg.error()}")
            continue

        payload = json.loads(msg.value())
        buffers[msg.topic()].append(payload)
        consumed += 1
        last_message_time = time.monotonic()

    written = _flush(buffers)
    if consumed:
        consumer.commit()

    summary = {topic: len(rows) for topic, rows in buffers.items()}
    print(f"Consumed {consumed} messages this call:")
    for topic, n in sorted(summary.items()):
        print(f"  {topic}: {n} message(s) -> {written.get(topic, [])}")

    return summary


if __name__ == "__main__":
    _limit_raw = os.environ.get("CONSUME_LIMIT", "").strip()
    _limit = int(_limit_raw) if _limit_raw else None
    _idle_timeout = float(os.environ.get("CONSUME_IDLE_TIMEOUT_SECONDS", "2") or 2)

    consume_batch(limit=_limit, idle_timeout_seconds=_idle_timeout)
