"""Drop and recreate all tables from db/schema.sql."""

from pathlib import Path

from _db import get_conn

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def main() -> None:
    sql = SCHEMA_PATH.read_text()
    with get_conn() as conn:
        conn.execute(sql)
    print("Schema created.")


if __name__ == "__main__":
    main()
