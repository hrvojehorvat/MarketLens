"""Generate a monthly price_history time series per product: baseline near the
product's own recorded price range, gentle downward drift, a shared Nov/Dec
promotional dip, and an extra clearance dip for slow movers (low popularity_weight)
in their last couple of months.
"""

import json
import random
import statistics
from pathlib import Path

from _config import SEED, SIM_MONTHS
from _db import get_conn

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

MONTHLY_DRIFT = 0.004  # ~5% depreciation over 12 months
NOV_DIP = 0.90
DEC_DIP = 0.85
CLEARANCE_EXTRA_DIP = 0.80
CLEARANCE_MONTHS = {10, 11}  # Nov, Dec (0-indexed)


def baseline_price(lowest: float, highest: float) -> float:
    if highest <= lowest:
        lowest = max(lowest, 5.0)
        highest = lowest * 1.5
    return round(lowest + random.uniform(0.5, 0.9) * (highest - lowest), 2)


def main() -> None:
    random.seed(SEED)

    demand_profile = json.loads((DATA_DIR / "demand_profile.json").read_text())
    median_popularity = statistics.median(v["popularity_weight"] for v in demand_profile.values())

    with get_conn() as conn:
        products = conn.execute(
            "SELECT upc, attributes FROM products ORDER BY upc"
        ).fetchall()

        conn.execute("TRUNCATE TABLE price_history CASCADE")

        rows = []
        for upc, attributes in products:
            lowest = float(attributes.get("lowest_recorded_price") or 0.0)
            highest = float(attributes.get("highest_recorded_price") or 0.0)
            base = baseline_price(lowest, highest)
            is_slow_mover = demand_profile[upc]["popularity_weight"] < median_popularity

            for month_index, month_start in enumerate(SIM_MONTHS):
                price = base * (1 - MONTHLY_DRIFT * month_index)
                if month_index == 10:
                    price *= NOV_DIP
                elif month_index == 11:
                    price *= DEC_DIP
                if is_slow_mover and month_index in CLEARANCE_MONTHS:
                    price *= CLEARANCE_EXTRA_DIP
                price *= random.uniform(0.97, 1.03)
                rows.append((upc, round(max(price, 1.0), 2), month_start))

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO price_history (product_upc, price, effective_from)
                VALUES (%s, %s, %s)
                """,
                rows,
            )

    print(f"Generated {len(rows)} price_history rows for {len(products)} products.")


if __name__ == "__main__":
    main()
