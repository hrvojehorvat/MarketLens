"""Generate returns for a subset of shipped/completed order_items.

Baseline ~5-8% return rate, boosted when the product's price dropped shortly after
the order (buyer's-remorse pattern: "I could have gotten this cheaper"), with the
reason drawn weighted by the product's category_top rather than uniformly. When every
item in an order ends up returned, that order's payment is flipped to 'refunded'
(partial refunds on multi-item orders aren't modeled -- out of scope for this pass).
"""

import datetime
import random
from collections import defaultdict

from _config import DEFAULT_RETURN_REASON_WEIGHTS, RETURN_REASONS_BY_CATEGORY, SEED, SIM_END
from _db import get_conn

BASELINE_RATE = 0.065
PRICE_DROP_BOOSTED_RATE = 0.18
PRICE_DROP_WINDOW_DAYS = 30
PRICE_DROP_THRESHOLD = 0.95


def main() -> None:
    random.seed(SEED)

    with get_conn() as conn:
        conn.execute("TRUNCATE TABLE returns CASCADE")

        items = conn.execute(
            """
            SELECT oi.id, oi.order_id, oi.product_upc, oi.quantity, oi.unit_price,
                   o.order_date, p.category_top
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN products p ON p.upc = oi.product_upc
            WHERE o.status IN ('shipped', 'completed')
            """
        ).fetchall()

        items_by_order = defaultdict(list)
        for row in items:
            items_by_order[row[1]].append(row)

        return_rows = []
        returned_item_ids_by_order = defaultdict(set)

        for order_item_id, order_id, upc, quantity, unit_price, order_date, category_top in items:
            window_end = min(order_date + datetime.timedelta(days=PRICE_DROP_WINDOW_DAYS), SIM_END)
            min_future_price = conn.execute(
                """
                SELECT MIN(price) FROM price_history
                WHERE product_upc = %s AND effective_from > %s AND effective_from <= %s
                """,
                (upc, order_date, window_end),
            ).fetchone()[0]

            rate = BASELINE_RATE
            if min_future_price is not None and float(min_future_price) < float(unit_price) * PRICE_DROP_THRESHOLD:
                rate = PRICE_DROP_BOOSTED_RATE

            if random.random() < rate:
                reasons = RETURN_REASONS_BY_CATEGORY.get(category_top, RETURN_REASONS_BY_CATEGORY["Electronics"])
                reason_weights = DEFAULT_RETURN_REASON_WEIGHTS.get(category_top, DEFAULT_RETURN_REASON_WEIGHTS["Electronics"])
                reason = random.choices(reasons, weights=reason_weights)[0]

                max_delay = max(1, (SIM_END - order_date).days)
                returned_at = datetime.datetime.combine(order_date, datetime.time(12)) + datetime.timedelta(
                    days=random.randint(1, min(20, max_delay))
                )
                refund_amount = round(float(quantity) * float(unit_price), 2)

                return_rows.append((order_item_id, reason, refund_amount, returned_at))
                returned_item_ids_by_order[order_id].add(order_item_id)

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO returns (order_item_id, reason, refund_amount, returned_at) VALUES (%s, %s, %s, %s)",
                return_rows,
            )

            fully_returned_orders = [
                order_id
                for order_id, returned_ids in returned_item_ids_by_order.items()
                if returned_ids == {row[0] for row in items_by_order[order_id]}
            ]
            if fully_returned_orders:
                cur.executemany(
                    "UPDATE payments SET status = 'refunded' WHERE order_id = %s",
                    [(order_id,) for order_id in fully_returned_orders],
                )

    print(f"Generated {len(return_rows)} returns ({len(fully_returned_orders)} fully-refunded orders).")


if __name__ == "__main__":
    main()
