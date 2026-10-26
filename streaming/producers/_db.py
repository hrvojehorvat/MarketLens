"""Read-only Postgres connection into store_db — the replay source for streaming/."""

from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from producers._config import postgres_dsn


@contextmanager
def get_conn():
    conn = psycopg.connect(postgres_dsn(), row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()
