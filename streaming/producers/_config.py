"""Shared constants for the Kafka (message broker — lets independent programs
publish and subscribe to streams of events) producers and consumers."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")

# Topic name -> partition count. Partitioning splits a topic into ordered lanes;
# messages published with the same key always land in the same partition, which
# is what keeps e.g. all events for one order in order relative to each other.
TOPICS = {
    "orders.placed": 3,
    "payments.processed": 3,
    "shipments.status_changed": 3,
    "price.changed": 3,
    "inventory.restocked": 3,
    "returns.filed": 3,
    "reviews.posted": 3,
}


def postgres_dsn() -> str:
    return (
        f"host={os.environ['POSTGRES_HOST']} "
        f"port={os.environ['POSTGRES_PORT']} "
        f"dbname={os.environ['POSTGRES_DB']} "
        f"user={os.environ['POSTGRES_USER']} "
        f"password={os.environ['POSTGRES_PASSWORD']}"
    )
