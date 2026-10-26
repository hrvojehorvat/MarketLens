"""Idempotent topic setup: creates every topic in TOPICS if it doesn't exist yet."""

import sys
from pathlib import Path

# Makes the producers package importable regardless of how this file is run --
# `python -m producers.create_topics` already puts the project root on sys.path
# on its own, but running this file directly (plain `python producers/create_topics.py`,
# or a Jupyter/VS Code "Run Cell") does not, since it puts producers/ itself
# there instead. Same fix the notebooks use, just relative to this file.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from confluent_kafka import KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

from producers._config import KAFKA_BOOTSTRAP_SERVERS, TOPICS


def create_topics() -> None:
    admin = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    existing = set(admin.list_topics(timeout=10).topics.keys())

    to_create = [
        NewTopic(name, num_partitions=partitions, replication_factor=1)
        for name, partitions in TOPICS.items()
        if name not in existing
    ]

    if not to_create:
        print("All topics already exist:")
        for name in TOPICS:
            print(f"  - {name}")
        return

    futures = admin.create_topics(to_create)
    for name, future in futures.items():
        try:
            future.result()
            print(f"Created topic: {name}")
        except KafkaException as exc:
            print(f"Failed to create {name}: {exc}")


if __name__ == "__main__":
    create_topics()
