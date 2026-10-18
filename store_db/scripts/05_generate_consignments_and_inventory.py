"""Initial stocking phase: one opening consignment batch per product, sized by
popularity and sourced from a specialty-matching merchant. Seeds the inventory
snapshot. Mid-simulation reorders (triggered by depletion) happen inside script 08,
not here.
"""

import datetime
import json
import random
from collections import defaultdict
from pathlib import Path

from _config import SEED, SIM_START
from _db import get_conn

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SIZE_TIER_WEIGHT = {"small": 1, "medium": 2, "large": 3}
BASE_QTY_SCALE = 60
MIN_INITIAL_QTY = 10
STOCKING_WINDOW_DAYS = 21


def pick_merchant(category_top: str, merchants: dict) -> str:
    candidates = [
        mid for mid, m in merchants.items() if category_top in m["specialties"]
    ]
    weights = [SIZE_TIER_WEIGHT[merchants[mid]["size_tier"]] for mid in candidates]
    return random.choices(candidates, weights=weights)[0]


def unit_cost_for(lowest: float, highest: float) -> float:
    if highest <= lowest:
        lowest = max(lowest, 5.0)
        highest = lowest * 1.5
    cost = lowest + random.uniform(0.0, 0.4) * (highest - lowest)
    return round(max(cost, 1.0), 2)


def main() -> None:
    random.seed(SEED)

    demand_profile = json.loads((DATA_DIR / "demand_profile.json").read_text())
    merchants = json.loads((DATA_DIR / "merchants_cache.json").read_text())

    with get_conn() as conn:
        products = conn.execute(
            "SELECT upc, category_top, attributes FROM products ORDER BY upc"
        ).fetchall()

        conn.execute("TRUNCATE TABLE consignment_items, consignments, inventory CASCADE")

        # Group consignment items by (merchant, received_date) so each merchant's
        # delivery looks like one real shipment containing several products, not a
        # separate consignment per product.
        batches: dict[tuple[str, datetime.date], list[tuple[str, int, float]]] = defaultdict(list)

        for upc, category_top, attributes in products:
            merchant_id = pick_merchant(category_top, merchants)
            popularity_weight = demand_profile[upc]["popularity_weight"]

            quantity = max(
                MIN_INITIAL_QTY,
                round(popularity_weight * BASE_QTY_SCALE * random.uniform(0.8, 1.2)),
            )
            lowest = float(attributes.get("lowest_recorded_price") or 0.0)
            highest = float(attributes.get("highest_recorded_price") or 0.0)
            cost = unit_cost_for(lowest, highest)

            offset_days = random.randint(0, STOCKING_WINDOW_DAYS)
            received_date = SIM_START + datetime.timedelta(days=offset_days)

            batches[(merchant_id, received_date)].append((upc, quantity, cost))

        with conn.cursor() as cur:
            for (merchant_id, received_date), items in batches.items():
                cur.execute(
                    "INSERT INTO consignments (merchant_id, received_date) VALUES (%s, %s) RETURNING id",
                    (merchant_id, received_date),
                )
                consignment_id = cur.fetchone()[0]
                cur.executemany(
                    """
                    INSERT INTO consignment_items (consignment_id, product_upc, quantity, unit_cost)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [(consignment_id, upc, qty, cost) for upc, qty, cost in items],
                )

        conn.execute(
            """
            INSERT INTO inventory (product_upc, quantity_on_hand)
            SELECT product_upc, SUM(quantity) FROM consignment_items GROUP BY product_upc
            ON CONFLICT (product_upc) DO UPDATE SET
                quantity_on_hand = EXCLUDED.quantity_on_hand, updated_at = now()
            """
        )

    print(f"Created {len(batches)} initial consignments covering {len(products)} products.")


if __name__ == "__main__":
    main()
