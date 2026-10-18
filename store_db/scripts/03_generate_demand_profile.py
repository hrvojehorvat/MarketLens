"""Compute per-product popularity_weight and elasticity.

This is deliberately NOT written to Postgres -- it's the "ground truth" that drives
the order-generation simulation (script 08) and the price-history clearance logic
(script 07), but it must stay inferable from the resulting data rather than readable
off a label column. Cached to data/demand_profile.json purely so the recipe is
reproducible and inspectable during development.

Elasticity sign convention used throughout the simulation: demand_multiplier =
(price_that_month / product_median_price) ** (-elasticity). So:
  - elasticity > 0  -> normal demand curve (price down => demand up)
  - elasticity ~= 0 -> price-insensitive
  - elasticity < 0  -> inverted (price up => demand up) -- the intentional anomaly group
"""

import json
import random
from pathlib import Path

from _config import SEED
from _db import get_conn

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "demand_profile.json"


def main() -> None:
    random.seed(SEED)

    with get_conn() as conn:
        upcs = [row[0] for row in conn.execute("SELECT upc FROM products ORDER BY upc").fetchall()]

    profile = {}
    for upc in upcs:
        popularity_weight = random.lognormvariate(0, 0.9)

        roll = random.random()
        if roll < 0.85:
            group = "normal"
            elasticity = random.uniform(0.8, 2.5)
        elif roll < 0.95:
            group = "insensitive"
            elasticity = random.uniform(-0.1, 0.1)
        else:
            group = "inverted"
            elasticity = random.uniform(-2.0, -0.5)

        profile[upc] = {
            "popularity_weight": popularity_weight,
            "elasticity": elasticity,
            "group": group,
        }

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(profile, indent=2))

    counts = {"normal": 0, "insensitive": 0, "inverted": 0}
    for v in profile.values():
        counts[v["group"]] += 1
    print(f"Demand profile for {len(profile)} products written to {OUT_PATH}")
    print(f"Elasticity groups: {counts}")


if __name__ == "__main__":
    main()
