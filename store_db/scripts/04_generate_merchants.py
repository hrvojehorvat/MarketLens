"""Generate ~10 supplier merchants, each specialized in 1-3 product categories.

Specialty and size tier are NOT stored as columns on the merchants table -- a real
analyst would infer a distributor's specialty from what it actually ships
(consignment_items -> products.category_top), not read it off a label. They're cached
to data/merchants_cache.json purely so later scripts (05: initial stocking, 08:
mid-simulation reorders) can pick a specialty-matching supplier without re-deriving the
random assignment from scratch.
"""

import json
import random
from pathlib import Path

from faker import Faker

from _config import MERCHANT_COUNTRY_WEIGHTS, N_MERCHANTS, SEED
from _db import get_conn

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "merchants_cache.json"

SIZE_TIERS = ["small", "medium", "large"]
SIZE_TIER_WEIGHTS = [0.5, 0.35, 0.15]


def main() -> None:
    random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    with get_conn() as conn:
        categories = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT category_top FROM products ORDER BY category_top"
            ).fetchall()
        ]

    countries = list(MERCHANT_COUNTRY_WEIGHTS.keys())
    country_weights = list(MERCHANT_COUNTRY_WEIGHTS.values())

    merchants = []
    for _ in range(N_MERCHANTS):
        n_specialties = random.choice([1, 1, 2, 2, 3])
        specialties = random.sample(categories, k=min(n_specialties, len(categories)))
        size_tier = random.choices(SIZE_TIERS, weights=SIZE_TIER_WEIGHTS)[0]
        merchants.append(
            {
                "name": fake.company(),
                "country": random.choices(countries, weights=country_weights)[0],
                "contact_name": fake.name(),
                "contact_email": fake.company_email(),
                "specialties": specialties,
                "size_tier": size_tier,
            }
        )

    # Guarantee every category has at least 2 specialty-matched merchants, so
    # specialty-based sourcing in scripts 05/08 never gets stuck with no supplier.
    for category in categories:
        covering = [m for m in merchants if category in m["specialties"]]
        while len(covering) < 2:
            candidate = random.choice([m for m in merchants if m not in covering])
            candidate["specialties"].append(category)
            covering.append(candidate)

    with get_conn() as conn:
        conn.execute("TRUNCATE TABLE merchants CASCADE")
        with conn.cursor() as cur:
            for m in merchants:
                cur.execute(
                    """
                    INSERT INTO merchants (name, country, contact_name, contact_email)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (m["name"], m["country"], m["contact_name"], m["contact_email"]),
                )
                m["id"] = cur.fetchone()[0]

    cache = {
        str(m["id"]): {"specialties": m["specialties"], "size_tier": m["size_tier"]}
        for m in merchants
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(cache, indent=2))

    print(f"Generated {len(merchants)} merchants, cached to {OUT_PATH}")


if __name__ == "__main__":
    main()
