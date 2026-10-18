"""Generate reviews for a subset of completed order_items.

Ratings follow a realistic J-shaped distribution (mostly 4-5 stars, a smaller 1-star
cluster, few in between) rather than uniform 1-5; returned items skew lower. Review
text is templated from that specific product's own category_top/brand/title so the
free text actually reads as being about the product it's attached to -- this is also
what makes it worth anything as a future RAG corpus, rather than generic Faker filler.
"""

import datetime
import random

from _config import SEED, SIM_END
from _db import get_conn

REVIEW_PROBABILITY = 0.4

RATING_WEIGHTS_NORMAL = {1: 0.08, 2: 0.05, 3: 0.07, 4: 0.25, 5: 0.55}
RATING_WEIGHTS_RETURNED = {1: 0.35, 2: 0.25, 3: 0.20, 4: 0.12, 5: 0.08}

POSITIVE_TEMPLATES = [
    "This {brand} {title} exceeded my expectations, great {category} buy.",
    "Solid {category} purchase -- the {title} works exactly as described.",
    "Love my {title}. {brand} really nailed this one.",
    "Would recommend this {title} to anyone shopping for {category}.",
    "Great value for a {brand} {category} product like the {title}.",
]
NEUTRAL_TEMPLATES = [
    "The {title} is okay, does what it says but nothing special.",
    "Decent {category} item, the {brand} {title} gets the job done.",
    "It's a fine {title}, a few quirks but acceptable overall.",
]
NEGATIVE_TEMPLATES = [
    "Disappointed with this {title}, not what I expected from {brand}.",
    "This {category} item, the {title}, had issues out of the box.",
    "Wouldn't buy this {brand} {title} again, quality felt off.",
    "The {title} stopped working properly after a short time.",
]


def pick_template(rating: int) -> str:
    if rating >= 4:
        return random.choice(POSITIVE_TEMPLATES)
    if rating == 3:
        return random.choice(NEUTRAL_TEMPLATES)
    return random.choice(NEGATIVE_TEMPLATES)


def main() -> None:
    random.seed(SEED)

    with get_conn() as conn:
        conn.execute("TRUNCATE TABLE reviews CASCADE")

        items = conn.execute(
            """
            SELECT oi.id, o.customer_id, oi.product_upc, o.order_date,
                   p.brand, p.title, p.category_top,
                   EXISTS (SELECT 1 FROM returns r WHERE r.order_item_id = oi.id) AS was_returned
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN products p ON p.upc = oi.product_upc
            WHERE o.status = 'completed'
            """
        ).fetchall()

        review_rows = []
        for order_item_id, customer_id, upc, order_date, brand, title, category_top, was_returned in items:
            if random.random() > REVIEW_PROBABILITY:
                continue

            weights = RATING_WEIGHTS_RETURNED if was_returned else RATING_WEIGHTS_NORMAL
            rating = random.choices(list(weights.keys()), weights=list(weights.values()))[0]

            template = pick_template(rating)
            review_text = template.format(brand=brand or "this brand", title=title, category=category_top)

            max_delay = max(1, (SIM_END - order_date).days)
            created_at = datetime.datetime.combine(order_date, datetime.time(14)) + datetime.timedelta(
                days=random.randint(3, min(30, max_delay))
            )

            review_rows.append((customer_id, upc, rating, review_text, created_at))

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO reviews (customer_id, product_upc, rating, review_text, created_at) VALUES (%s, %s, %s, %s, %s)",
                review_rows,
            )

    print(f"Generated {len(review_rows)} reviews from {len(items)} eligible completed order items.")


if __name__ == "__main__":
    main()
