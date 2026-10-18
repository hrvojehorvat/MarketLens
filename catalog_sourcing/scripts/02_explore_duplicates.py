# %% [markdown]
# # 02 — Explore Duplicates (products sold by multiple shops)
#
# Using the product cache built by `01_explore_catalog.py`, check how many real
# products are genuinely **duplicated across independent shops** — i.e. have ≥2 offers
# from different merchant domains — and what currencies/merchants actually show up.
#
# UPCitemdb's `search` results already embed an `offers` array per item. We use that
# first (zero extra API cost). For items with no embedded offers, we optionally backfill
# with a targeted `lookup` call per UPC — budget-capped and sharing the same 100/day
# quota as script 01.

# %%
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

# %%
# --- config (mirrors script 01) -------------------------------------------

CACHE_DIR = Path("../data/catalog")
PRODUCTS_CACHE = CACHE_DIR / "products.jsonl"
OFFERS_CACHE = CACHE_DIR / "offers_lookup.jsonl"   # upc -> offers, from targeted lookup backfill
QUOTA_FILE = CACHE_DIR / "api_quota.json"          # shared with script 01

BASE_URL = "https://api.upcitemdb.com/prod/trial"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

DAILY_QUOTA = 100
SAFETY_BUFFER = 10
MAX_LOOKUPS_THIS_RUN = 15   # backfill budget for this run — most items already have embedded offers

# %%
def _load_quota():
    if QUOTA_FILE.exists():
        state = json.loads(QUOTA_FILE.read_text())
        if state.get("date") == str(date.today()):
            return state
    return {"date": str(date.today()), "used": 0}


def quota_remaining():
    return DAILY_QUOTA - _load_quota()["used"]


def record_request(n=1):
    state = _load_quota()
    state["used"] += n
    QUOTA_FILE.write_text(json.dumps(state))
    return DAILY_QUOTA - state["used"]


print(f"Requests remaining today (shared with script 01): {quota_remaining()}")

# %%
def load_jsonl(path):
    if not path.exists():
        return []
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


products = load_jsonl(PRODUCTS_CACHE)
print(f"Loaded {len(products)} cached products from script 01")

df = pd.json_normalize(products)
df.head()

# %%
# how many already have offers embedded directly from the search response?
def offer_list(item):
    o = item.get("offers")
    return o if isinstance(o, list) else []

embedded_counts = pd.Series([len(offer_list(p)) for p in products])
print("Embedded-offer count distribution (from search results, no extra API cost):")
print(embedded_counts.describe())
print()
print(f"Products with 0 embedded offers: {(embedded_counts == 0).sum()} / {len(products)}")

# %%
# --- optional backfill: targeted lookup for items with 0 embedded offers ----
# Same burst-limit handling as script 01's search call: wait out 429s and retry the
# same request instead of abandoning it, and don't count 429s against daily quota.

MAX_RETRIES_PER_REQUEST = 5
SLEEP_BETWEEN_REQUESTS = 1.0
MAX_BURST_WAIT_SECONDS = 120  # a Retry-After bigger than this is the daily reset, not a burst cooldown


def lookup_upcitemdb(upc):
    params = {"upc": upc}

    for attempt in range(MAX_RETRIES_PER_REQUEST):
        try:
            resp = requests.get(f"{BASE_URL}/lookup", headers=HEADERS, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            print(f"Network error ({e}); retrying in 3s...")
            time.sleep(3)
            continue

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 5))
            if retry_after > MAX_BURST_WAIT_SECONDS:
                state = _load_quota()
                state["used"] = DAILY_QUOTA
                QUOTA_FILE.write_text(json.dumps(state))
                raise RuntimeError(
                    f"Daily quota actually exhausted (server says wait {retry_after/3600:.1f}h). "
                    "Stopping now — resume after the daily reset."
                )
            print(f"Burst limit hit, waiting {retry_after:.1f}s (not counted against daily quota)...")
            time.sleep(retry_after + 0.5)
            continue

        record_request(1)

        if resp.status_code == 404:
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            return {"items": []}

        resp.raise_for_status()
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        return resp.json()

    raise RuntimeError("Repeated burst-limit/network failures after retries — stopping this run, resume later.")


already_looked_up = {o["upc"] for o in load_jsonl(OFFERS_CACHE) if o.get("upc")}
to_backfill = [
    p for p in products
    if len(offer_list(p)) == 0 and p.get("upc") and p["upc"] not in already_looked_up
][:MAX_LOOKUPS_THIS_RUN]

print(f"Backfilling offers for {len(to_backfill)} products via lookup (budget-capped)...")

with OFFERS_CACHE.open("a") as out_f:
    for p in to_backfill:
        if quota_remaining() <= SAFETY_BUFFER:
            print("Near daily quota, stopping backfill early.")
            break
        try:
            data = lookup_upcitemdb(p["upc"])
        except RuntimeError as e:
            print(e)
            break
        items = data.get("items", [])
        offers = items[0].get("offers", []) if items else []
        record = {"upc": p["upc"], "offers": offers}
        out_f.write(json.dumps(record) + "\n")

print(f"Requests remaining today: {quota_remaining()}")

# %%
# --- merge embedded + backfilled offers into one working table --------------

backfilled = {o["upc"]: o["offers"] for o in load_jsonl(OFFERS_CACHE) if o.get("upc")}

rows = []
for p in products:
    upc = p.get("upc")
    offers = offer_list(p)
    if not offers and upc in backfilled:
        offers = backfilled[upc]

    merchants = {o.get("domain") or o.get("merchant") for o in offers if o.get("domain") or o.get("merchant")}
    prices = [o["price"] for o in offers if isinstance(o.get("price"), (int, float)) and o["price"] > 0]
    currencies = {o.get("currency") for o in offers if o.get("currency")}

    rows.append({
        "upc": upc,
        "title": p.get("title"),
        "brand": p.get("brand"),
        "category_top": (p.get("category") or "").split(">")[0].strip(),
        "offer_count": len(offers),
        "distinct_merchant_count": len(merchants),
        "is_duplicated_across_shops": len(merchants) >= 2,
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "currencies_seen": sorted(c for c in currencies if c),
    })

summary = pd.DataFrame(rows)
summary.head()

# %% [markdown]
# ## The question we actually came here to answer

# %%
dup_rate = summary["is_duplicated_across_shops"].mean()
print(f"Products sold by >=2 distinct shops: {summary['is_duplicated_across_shops'].sum()} / {len(summary)} ({dup_rate:.1%})")
print()
print("Distribution of distinct-merchant counts:")
print(summary["distinct_merchant_count"].value_counts().sort_index())

# %%
# currency reality check — how much genuine EUR coverage do we actually have?
all_currencies = pd.Series([c for cs in summary["currencies_seen"] for c in cs])
print("Currency distribution across all offers:")
print(all_currencies.value_counts())

# %%
# top merchants among duplicated products, and by category
dup_only = summary[summary["is_duplicated_across_shops"]]
print(f"Duplicated-product category breakdown ({len(dup_only)} products):")
print(dup_only["category_top"].value_counts())

# %%
# persist the summary for later use when we actually build the pipeline
out_path = CACHE_DIR / "duplicate_summary.csv"
summary.to_csv(out_path, index=False)
print(f"Saved summary for {len(summary)} products to {out_path}")

# %% [markdown]
# **Read on the result (confirmed via smoke test, not just a guess):** EUR offers do
# exist (e.g. Argos Ireland), but they're rare — one EUR offer out of dozens reviewed, and
# always a *single* EUR merchant on a product, never two independent EUR shops on the same
# item at once. So real multi-shop EUR price duplication isn't something this data actually
# gives us — and UPCitemdb's offers lean US/Canada-heavy anyway. Decision: compete in
# **USD**, not EUR — matches the data instead of fighting it. Keep *product identity*
# (title/brand/model/category) real — that's the part UPCitemdb genuinely delivers — and
# treat the *shop-level USD pricing* (our fictional competitor shops, their prices) as
# synthetic, generated on top of the real catalog rather than scraped.
