"""Generate ~150 customers: growth-curve signup dates, US/Canada-skewed geography,
and a generation-time activity_weight + segment (deal-seeker vs regular) used only to
weight order selection in script 08 -- never stored as a column.
"""

import datetime
import json
import random
from pathlib import Path

from faker import Faker

from _config import CUSTOMER_COUNTRY_WEIGHTS, N_CUSTOMERS, SEED, SIM_START
from _db import get_conn

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "customers_cache.json"

# Linearly increasing per-month signup weights: the shop's customer base grows over
# the year rather than appearing fully formed on day one.
MONTH_SIGNUP_WEIGHTS = [1 + i * 0.4 for i in range(12)]

SEGMENTS = ["deal_seeker", "regular"]
SEGMENT_WEIGHTS = [0.3, 0.7]


def random_signup_date() -> datetime.datetime:
    month_index = random.choices(range(12), weights=MONTH_SIGNUP_WEIGHTS)[0]
    month_start = datetime.date(SIM_START.year, month_index + 1, 1)
    day_offset = random.randint(0, 27)
    signup_date = month_start + datetime.timedelta(days=day_offset)
    return datetime.datetime.combine(signup_date, datetime.time(random.randint(0, 23), random.randint(0, 59)))


def main() -> None:
    random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    countries = list(CUSTOMER_COUNTRY_WEIGHTS.keys())
    country_weights = list(CUSTOMER_COUNTRY_WEIGHTS.values())

    customers = []
    for i in range(N_CUSTOMERS):
        customers.append(
            {
                "full_name": fake.name(),
                "email": f"{fake.user_name()}.{i}@{fake.free_email_domain()}",
                "country": random.choices(countries, weights=country_weights)[0],
                "address": fake.address().replace("\n", ", "),
                "created_at": random_signup_date(),
                "activity_weight": random.lognormvariate(0, 0.9),
                "segment": random.choices(SEGMENTS, weights=SEGMENT_WEIGHTS)[0],
            }
        )

    with get_conn() as conn:
        conn.execute("TRUNCATE TABLE customers CASCADE")
        with conn.cursor() as cur:
            for c in customers:
                cur.execute(
                    """
                    INSERT INTO customers (full_name, email, country, address, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (c["full_name"], c["email"], c["country"], c["address"], c["created_at"]),
                )
                c["id"] = cur.fetchone()[0]

    cache = {
        str(c["id"]): {
            "activity_weight": c["activity_weight"],
            "segment": c["segment"],
            "country": c["country"],
            "created_at": c["created_at"].isoformat(),
        }
        for c in customers
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(cache, indent=2))

    print(f"Generated {len(customers)} customers, cached to {OUT_PATH}")


if __name__ == "__main__":
    main()
