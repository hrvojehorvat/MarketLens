"""Load the real products from catalog_sourcing into the products table.

category_top is the first segment of the ">"-delimited category path. A handful of
source records have an empty category (all gaming headsets) -- those fall back to
"Electronics", which is what they clearly are, rather than leaving category NULL.

A few records carry an "ean" (European Article Number -- the 13-digit international
barcode standard, a superset of the 12-digit UPC) instead of a "upc" -- items the
API only had a non-US barcode for. We use that as the products.upc value instead;
the column is really just "the barcode", regardless of which standard it follows.
"""

import json
from pathlib import Path

from _db import get_conn

PRODUCTS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "catalog_sourcing"
    / "data"
    / "catalog"
    / "products.jsonl"
)

FALLBACK_CATEGORY = "Electronics"


def load_records():
    with open(PRODUCTS_PATH) as f:
        for line in f:
            yield json.loads(line)


def main() -> None:
    rows = []
    for rec in load_records():
        upc = rec.get("upc") or str(rec["ean"])
        category = rec["category"].strip() or FALLBACK_CATEGORY
        category_top = category.split(">")[0].strip() or FALLBACK_CATEGORY

        attributes = {
            k: v
            for k, v in rec.items()
            if k not in {"category", "offers", "upc", "ean", "title", "brand"}
        }

        rows.append(
            (
                upc,
                rec["title"],
                rec.get("brand") or None,
                category,
                category_top,
                json.dumps(attributes),
            )
        )

    with get_conn() as conn:
        conn.execute("TRUNCATE TABLE products CASCADE")
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO products (upc, title, brand, category, category_top, attributes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (upc) DO UPDATE SET
                    title = EXCLUDED.title,
                    brand = EXCLUDED.brand,
                    category = EXCLUDED.category,
                    category_top = EXCLUDED.category_top,
                    attributes = EXCLUDED.attributes
                """,
                rows,
            )

    print(f"Loaded {len(rows)} products.")


if __name__ == "__main__":
    main()
