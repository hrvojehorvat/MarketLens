"""The core simulation: month-by-month order generation.

For each month: checks stock against a safety threshold and triggers a reorder
consignment (from a specialty-matched merchant) when needed; generates that month's
orders with demand driven by
    popularity_weight * (price_that_month / product_median_price) ** (-elasticity) * seasonality
so "most orders happened when price was lower" is an emergent property rather than a
hardcoded fact; looks up unit_price from price_history (never computed independently);
ties order status to recency and to a simulated payment outcome; creates the matching
payments and shipments rows inline; updates the running inventory snapshot.
"""

import calendar
import datetime
import json
import random
import statistics
from pathlib import Path

from _config import (
    PAYMENT_METHOD_WEIGHTS,
    PAYMENT_METHODS,
    CARRIERS,
    SEED,
    SIM_END,
    SIM_MONTHS,
    TARGET_ORDERS,
)
from _db import get_conn

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SIZE_TIER_WEIGHT = {"small": 1, "medium": 2, "large": 3}
REORDER_QTY_SCALE = 40
PAYMENT_FAILURE_RATE = 0.04
DEAL_SEEKER_BOOST = 2.5
DIP_RATIO_THRESHOLD = 0.95


def seasonality_factor(month_index: int) -> float:
    return 1.15 if month_index in (10, 11) else 1.0


def pick_merchant(category_top: str, merchants: dict) -> str:
    candidates = [mid for mid, m in merchants.items() if category_top in m["specialties"]]
    weights = [SIZE_TIER_WEIGHT[merchants[mid]["size_tier"]] for mid in candidates]
    return random.choices(candidates, weights=weights)[0]


def unit_cost_for(lowest: float, highest: float) -> float:
    if highest <= lowest:
        lowest = max(lowest, 5.0)
        highest = lowest * 1.5
    return round(max(lowest + random.uniform(0.0, 0.4) * (highest - lowest), 1.0), 2)


def transit_days(country: str) -> int:
    return random.randint(2, 5) if country in ("United States", "Canada") else random.randint(7, 14)


def main() -> None:
    random.seed(SEED)

    demand_profile = json.loads((DATA_DIR / "demand_profile.json").read_text())
    merchants = json.loads((DATA_DIR / "merchants_cache.json").read_text())
    customers_cache = json.loads((DATA_DIR / "customers_cache.json").read_text())

    with get_conn() as conn:
        conn.execute(
            "TRUNCATE TABLE shipments, payments, order_items, orders CASCADE"
        )

        products = conn.execute(
            "SELECT upc, category_top, attributes FROM products ORDER BY upc"
        ).fetchall()
        product_category = {upc: cat for upc, cat, _ in products}
        product_attrs = {upc: attrs for upc, _, attrs in products}
        upcs = [upc for upc, _, _ in products]

        customer_ids = [row[0] for row in conn.execute("SELECT id FROM customers").fetchall()]

        price_rows = conn.execute(
            "SELECT product_upc, effective_from, price FROM price_history ORDER BY product_upc, effective_from"
        ).fetchall()
        price_by_product_month: dict[str, dict[datetime.date, float]] = {}
        for upc, effective_from, price in price_rows:
            price_by_product_month.setdefault(upc, {})[effective_from] = float(price)

        median_price = {
            upc: statistics.median(months.values()) for upc, months in price_by_product_month.items()
        }

        stock = {
            row[0]: row[1]
            for row in conn.execute("SELECT product_upc, quantity_on_hand FROM inventory").fetchall()
        }
        initial_stock = dict(stock)

        # 1. Pre-compute each month's per-product demand weight and the resulting
        # order count for that month, so months with lower average prices (e.g. the
        # Nov/Dec price dip baked into price_history) naturally get more orders.
        monthly_weights: list[dict[str, float]] = []
        for month_index, month_start in enumerate(SIM_MONTHS):
            weights = {}
            for upc in upcs:
                price = price_by_product_month[upc][month_start]
                ratio = price / median_price[upc]
                elasticity = demand_profile[upc]["elasticity"]
                popularity = demand_profile[upc]["popularity_weight"]
                weights[upc] = popularity * (ratio ** (-elasticity)) * seasonality_factor(month_index)
            monthly_weights.append(weights)

        grand_total = sum(sum(w.values()) for w in monthly_weights)
        orders_per_month = [
            max(1, round(TARGET_ORDERS * sum(w.values()) / grand_total)) for w in monthly_weights
        ]

        order_rows = []
        order_item_rows = []
        payment_rows = []
        shipment_rows = []

        for month_index, month_start in enumerate(SIM_MONTHS):
            days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]
            weights = monthly_weights[month_index]

            # Reorder check: trigger a replenishment consignment for any product that
            # has dropped below a simple safety threshold, before generating this
            # month's demand against it -- supply responding to demand, not an
            # independent schedule.
            with conn.cursor() as cur:
                for upc in upcs:
                    threshold = max(10, round(0.15 * initial_stock.get(upc, 0)))
                    if stock.get(upc, 0) < threshold:
                        merchant_id = pick_merchant(product_category[upc], merchants)
                        attrs = product_attrs[upc]
                        lowest = float(attrs.get("lowest_recorded_price") or 0.0)
                        highest = float(attrs.get("highest_recorded_price") or 0.0)
                        cost = unit_cost_for(lowest, highest)
                        qty = max(10, round(demand_profile[upc]["popularity_weight"] * REORDER_QTY_SCALE))
                        received_date = month_start + datetime.timedelta(days=random.randint(1, 7))

                        cur.execute(
                            "INSERT INTO consignments (merchant_id, received_date) VALUES (%s, %s) RETURNING id",
                            (merchant_id, received_date),
                        )
                        consignment_id = cur.fetchone()[0]
                        cur.execute(
                            """
                            INSERT INTO consignment_items (consignment_id, product_upc, quantity, unit_cost)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (consignment_id, upc, qty, cost),
                        )
                        stock[upc] = stock.get(upc, 0) + qty

            product_weight_list = [weights[upc] for upc in upcs]

            for _ in range(orders_per_month[month_index]):
                primary_upc = random.choices(upcs, weights=product_weight_list)[0]
                ratio = price_by_product_month[primary_upc][month_start] / median_price[primary_upc]
                is_dip = ratio < DIP_RATIO_THRESHOLD

                customer_weights = [
                    customers_cache[str(cid)]["activity_weight"]
                    * (DEAL_SEEKER_BOOST if is_dip and customers_cache[str(cid)]["segment"] == "deal_seeker" else 1.0)
                    for cid in customer_ids
                ]
                customer_id = random.choices(customer_ids, weights=customer_weights)[0]
                country = customers_cache[str(customer_id)]["country"]

                chosen_upcs = [primary_upc]
                if random.random() < 0.2:
                    second_upc = random.choices(upcs, weights=product_weight_list)[0]
                    if second_upc != primary_upc:
                        chosen_upcs.append(second_upc)

                items = []
                for upc in chosen_upcs:
                    available = stock.get(upc, 0)
                    if available <= 0:
                        continue
                    qty = min(available, random.choices([1, 2, 3], weights=[0.7, 0.25, 0.05])[0])
                    stock[upc] -= qty
                    unit_price = price_by_product_month[upc][month_start]
                    items.append((upc, qty, unit_price))

                if not items:
                    continue

                order_date = month_start + datetime.timedelta(days=random.randint(0, days_in_month - 1))
                days_since_order = (SIM_END - order_date).days
                amount = round(sum(qty * price for _, qty, price in items), 2)

                if days_since_order < 2:
                    status = "processing"
                    payment_status = "pending"
                    paid_at = None
                elif random.random() < PAYMENT_FAILURE_RATE:
                    status = "cancelled"
                    payment_status = "failed"
                    paid_at = None
                else:
                    payment_status = "paid"
                    paid_at = datetime.datetime.combine(order_date, datetime.time(random.randint(0, 23))) + datetime.timedelta(
                        hours=random.randint(1, 36)
                    )
                    if days_since_order < 10:
                        status = "shipped"
                    else:
                        status = "completed"

                order_rows.append((customer_id, order_date, status))
                order_index = len(order_rows) - 1
                for upc, qty, unit_price in items:
                    order_item_rows.append((order_index, upc, qty, unit_price))
                payment_rows.append(
                    (order_index, random.choices(PAYMENT_METHODS, weights=PAYMENT_METHOD_WEIGHTS)[0], amount, paid_at, payment_status)
                )

                if status in ("shipped", "completed"):
                    shipped_at = paid_at + datetime.timedelta(hours=random.randint(2, 48))
                    delivered_at = None
                    if status == "completed":
                        delivered_at = shipped_at + datetime.timedelta(days=transit_days(country))
                    shipment_rows.append(
                        (
                            order_index,
                            random.choice(CARRIERS),
                            f"TRK{random.randint(10**9, 10**10 - 1)}",
                            shipped_at,
                            delivered_at,
                        )
                    )

        with conn.cursor() as cur:
            order_db_ids = []
            for customer_id, order_date, status in order_rows:
                cur.execute(
                    "INSERT INTO orders (customer_id, order_date, status) VALUES (%s, %s, %s) RETURNING id",
                    (customer_id, order_date, status),
                )
                order_db_ids.append(cur.fetchone()[0])

            cur.executemany(
                "INSERT INTO order_items (order_id, product_upc, quantity, unit_price) VALUES (%s, %s, %s, %s)",
                [(order_db_ids[idx], upc, qty, price) for idx, upc, qty, price in order_item_rows],
            )
            cur.executemany(
                "INSERT INTO payments (order_id, method, amount, paid_at, status) VALUES (%s, %s, %s, %s, %s)",
                [(order_db_ids[idx], method, amount, paid_at, status) for idx, method, amount, paid_at, status in payment_rows],
            )
            cur.executemany(
                "INSERT INTO shipments (order_id, carrier, tracking_number, shipped_at, delivered_at) VALUES (%s, %s, %s, %s, %s)",
                [
                    (order_db_ids[idx], carrier, tracking, shipped_at, delivered_at)
                    for idx, carrier, tracking, shipped_at, delivered_at in shipment_rows
                ],
            )

        conn.execute("DELETE FROM inventory")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO inventory (product_upc, quantity_on_hand) VALUES (%s, %s)",
                [(upc, max(0, qty)) for upc, qty in stock.items()],
            )

    print(f"Generated {len(order_rows)} orders ({len(order_item_rows)} line items) across 12 months.")
    print(f"Orders per month target: {orders_per_month}")


if __name__ == "__main__":
    main()
