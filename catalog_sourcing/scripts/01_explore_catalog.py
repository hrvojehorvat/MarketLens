# %% [markdown]
# # 01 — Explore Catalog
#
# Pull real electronics products from **UPCitemdb** (free `EXPLORER` plan — no signup,
# no API key, 100 combined requests/day shared with notebook 02) and explore what we get:
# category spread, brand spread, data quality.
#
# **Why UPCitemdb:** confirmed from its live OpenAPI spec — the `search` endpoint returns
# up to 10 items per call, and each item already carries its own `offers` array
# (merchant, domain, currency, price, link) for later duplicate-shop analysis in notebook 02.
#
# **Quota reality check:** the free plan is 100 requests/day for *both* search and lookup
# combined, but each `search` call returns up to **10 items per page** (confirmed live —
# offers come embedded too). With ~50 diverse keywords below, one run can realistically get
# close to the ~500-product target without needing multiple days — the request cap below
# is set with that in mind, leaving a little headroom for notebook 02 the same day. If a run
# falls short (keyword overlap, short result sets), just re-run after the quota resets;
# progress is cached to disk and accumulates across runs either way.
#
# **Known caveat (confirmed via smoke test):** UPCitemdb's offer data leans
# US/Canada-retailer-heavy. Genuine EUR offers do turn up occasionally (e.g. Argos Ireland)
# but are rare and never duplicated — a product might have one EUR merchant, never two.
# Real multi-shop EUR duplication isn't something this data provides; notebook 02 quantifies
# this and the catalog build below also drops generic/unbranded listings (brand
# `"unbranding"` etc.) that would otherwise pollute the product set with junk.

# %%
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

# %%
# --- config -----------------------------------------------------------------

CACHE_DIR = Path("../data/catalog")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

PRODUCTS_CACHE = CACHE_DIR / "products.jsonl"      # accumulated unique products (append-only)
QUOTA_FILE = CACHE_DIR / "api_quota.json"          # shared daily-quota tracker (both notebooks)
PROGRESS_FILE = CACHE_DIR / "search_progress.json" # resume pointer: which keyword/offset to query next

BASE_URL = "https://api.upcitemdb.com/prod/trial"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

DAILY_QUOTA = 100          # UPCitemdb free EXPLORER plan: 100 combined requests/day
SAFETY_BUFFER = 10         # leave a little headroom for notebook 02 run same day
MAX_REQUESTS_THIS_RUN = 80 # 10 items/page x 80 requests can comfortably reach the 500 target in one run

TARGET_TOTAL_PRODUCTS = 500

# Generic/dropship listings to exclude — these show up with a single-merchant offer,
# near-duplicate titles, and no real brand (confirmed via live smoke test: "unbranding").
BRAND_BLOCKLIST = {"", "unbranding", "generic", "generic brand", "unbranded", "no brand"}


def is_real_brand(item):
    brand = (item.get("brand") or "").strip().lower()
    return brand not in BRAND_BLOCKLIST


# Diverse electronics keywords — broad enough to reach ~500 unique products over
# several runs. Add more here any time; duplicates are deduped automatically.
SEARCH_QUERIES = [
    "smartphone", "iphone", "samsung galaxy phone", "android phone",
    "laptop", "gaming laptop", "macbook", "chromebook", "2 in 1 laptop",
    "tablet", "ipad", "android tablet",
    "wireless headphones", "noise cancelling headphones", "wireless earbuds",
    "bluetooth speaker", "soundbar", "home theater system",
    "smart watch", "fitness tracker",
    "4k tv", "oled tv", "smart tv",
    "digital camera", "mirrorless camera", "action camera", "drone",
    "gaming console", "gaming controller", "gaming headset", "gaming mouse",
    "mechanical keyboard", "computer monitor", "graphics card", "ssd drive",
    "external hard drive", "wifi router", "mesh router", "network switch",
    "power bank", "wireless charger", "webcam", "smart home speaker",
    "smart thermostat", "smart doorbell", "robot vacuum", "air purifier",
    "printer", "all in one printer", "projector", "e reader",
    "car dash cam", "dvd player", "bluetooth car adapter",
]

# %%
# --- shared daily-quota tracker ---------------------------------------------

def _load_quota():
    if QUOTA_FILE.exists():
        state = json.loads(QUOTA_FILE.read_text())
        if state.get("date") == str(date.today()):
            return state
    return {"date": str(date.today()), "used": 0}


def quota_remaining():
    state = _load_quota()
    return DAILY_QUOTA - state["used"]


def record_request(n=1):
    state = _load_quota()
    state["used"] += n
    QUOTA_FILE.write_text(json.dumps(state))
    return DAILY_QUOTA - state["used"]


print(f"Requests used today: {_load_quota()['used']} / {DAILY_QUOTA}")
print(f"Remaining today: {quota_remaining()}")

# %%
# --- dedup state: load what we already have ---------------------------------

def load_cached_products():
    if not PRODUCTS_CACHE.exists():
        return []
    items = []
    with PRODUCTS_CACHE.open() as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def product_key(item):
    # prefer a real identifier; fall back to upc/ean/title so we never lose an item
    return item.get("upc") or item.get("ean") or item.get("gtin") or item.get("title")


cached_items = load_cached_products()
seen_keys = {product_key(it) for it in cached_items}
print(f"Already cached: {len(cached_items)} unique products")

# %%
# --- resume pointer: don't re-query keywords/pages already exhausted --------
# Without this, every run restarts at SEARCH_QUERIES[0]/offset=0 and burns quota
# re-fetching pages whose products are already in seen_keys (confirmed: the
# accumulation loop has no memory of where a *previous run* stopped querying,
# only of which *products* it already saved). This file fixes that.

def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"keyword_index": 0, "offset": 0}


def save_progress(keyword_index, offset):
    PROGRESS_FILE.write_text(json.dumps({"keyword_index": keyword_index, "offset": offset}))


progress = load_progress()
print(f"Resuming from keyword #{progress['keyword_index']} ({SEARCH_QUERIES[progress['keyword_index']] if progress['keyword_index'] < len(SEARCH_QUERIES) else '<past end>'}), offset {progress['offset']}")
print("Note: if you reorder/remove keywords in SEARCH_QUERIES between runs, this resume "
      "pointer will point at the wrong keyword — only append new ones at the end.")

# %%
# --- UPCitemdb search call ---------------------------------------------------
# UPCitemdb's free plan enforces a short *burst* limit (separate from the 100/day
# quota) — confirmed live: back-to-back requests trip a 429 with Retry-After ~20s.
# On a 429 we wait it out and retry the *same* request rather than abandoning it and
# moving to the next keyword (which just re-trips the limiter immediately, over and
# over). 429s are NOT counted against the daily quota tracker — only real responses are.

MAX_RETRIES_PER_REQUEST = 5
SLEEP_BETWEEN_REQUESTS = 1.0  # seconds — paces successful calls to avoid retripping the burst limiter
MAX_BURST_WAIT_SECONDS = 120  # a Retry-After bigger than this is the daily reset, not a burst cooldown


def search_upcitemdb(keywords, offset=0, match_mode=0):
    params = {"s": keywords, "offset": offset, "match_mode": match_mode, "type": "product"}

    for attempt in range(MAX_RETRIES_PER_REQUEST):
        try:
            resp = requests.get(f"{BASE_URL}/search", headers=HEADERS, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            print(f"Network error ({e}); retrying in 3s...")
            time.sleep(3)
            continue

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 5))
            if retry_after > MAX_BURST_WAIT_SECONDS:
                # Server is reporting hours, not seconds — the real daily quota is exhausted,
                # not a short burst cooldown. Don't sleep through it; stop now and mark today
                # as used up so later cells/runs don't keep hammering a dead quota.
                state = _load_quota()
                state["used"] = DAILY_QUOTA
                QUOTA_FILE.write_text(json.dumps(state))
                raise RuntimeError(
                    f"Daily quota actually exhausted (server says wait {retry_after/3600:.1f}h). "
                    "Stopping now — resume after the daily reset."
                )
            print(f"Burst limit hit, waiting {retry_after:.1f}s (not counted against daily quota)...")
            time.sleep(retry_after + 0.5)
            continue  # retry the same request

        record_request(1)  # only count requests that got a real (non-429) response

        if resp.status_code == 404:
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            return {"code": "NOT_FOUND", "total": 0, "offset": 0, "items": []}

        resp.raise_for_status()
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        return resp.json()

    raise RuntimeError("Repeated burst-limit/network failures after retries — stopping this run, resume later.")

# %%
# --- accumulate new unique products, budget- and target-aware ---------------

new_items = []
skipped_unbranded = 0
requests_made_this_run = 0

with PRODUCTS_CACHE.open("a") as out_f:
    for idx, keyword in enumerate(SEARCH_QUERIES):
        if idx < progress["keyword_index"]:
            continue  # fully exhausted in a previous run — resume pointer skips it

        if requests_made_this_run >= MAX_REQUESTS_THIS_RUN:
            print("Hit this-run request cap, stopping.")
            break
        if quota_remaining() <= SAFETY_BUFFER:
            print("Close to daily quota, stopping to leave headroom for notebook 02.")
            break
        if len(seen_keys) >= TARGET_TOTAL_PRODUCTS:
            print(f"Reached target of {TARGET_TOTAL_PRODUCTS} products, stopping.")
            break

        offset = progress["offset"] if idx == progress["keyword_index"] else 0
        while True:
            if requests_made_this_run >= MAX_REQUESTS_THIS_RUN or quota_remaining() <= SAFETY_BUFFER:
                break
            try:
                data = search_upcitemdb(keyword, offset=offset)
            except RuntimeError as e:
                print(e)
                break
            requests_made_this_run += 1

            items = data.get("items", [])
            for item in items:
                if not is_real_brand(item):
                    skipped_unbranded += 1
                    continue
                key = product_key(item)
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    new_items.append(item)
                    out_f.write(json.dumps(item) + "\n")

            next_offset = data.get("offset", 0)
            if not next_offset or next_offset <= offset:
                save_progress(idx + 1, 0)  # keyword exhausted, move on next time
                break
            offset = next_offset
            save_progress(idx, offset)  # persist immediately so a stop mid-keyword still resumes correctly

print(f"This run: {requests_made_this_run} requests made, {len(new_items)} new unique products added")
print(f"Skipped (unbranded/generic, e.g. brand='unbranding'): {skipped_unbranded}")
print(f"Total unique products cached so far: {len(seen_keys)} / {TARGET_TOTAL_PRODUCTS}")
print(f"Requests remaining today: {quota_remaining()}")

# %% [markdown]
# ## Explore what we've collected so far

# %%
all_items = load_cached_products()
df = pd.json_normalize(all_items)
print(df.shape)
df.head()

# %%
# top-level category (UPCitemdb categories look like "Electronics > Audio > Headphones")
df["category_top"] = df.get("category", pd.Series(dtype=str)).fillna("").str.split(">").str[0].str.strip()

print("Products by top-level category:")
print(df["category_top"].value_counts())

# %%
print("Top 20 brands:")
print(df.get("brand", pd.Series(dtype=str)).fillna("(missing)").value_counts().head(20))

# %%
# data quality: how many are missing a brand / usable identifier / any offers at all?
missing_brand = df["brand"].isna().mean() if "brand" in df else 1.0
has_offers = df["offers"].apply(lambda o: isinstance(o, list) and len(o) > 0) if "offers" in df else pd.Series([False] * len(df))

print(f"Missing brand: {missing_brand:.1%}")
print(f"Items with >=1 offer already embedded from search: {has_offers.mean():.1%}  ({has_offers.sum()} / {len(df)})")

# %% [markdown]
# **Next:** if this run didn't quite reach ~500 unique products, just re-run this
# script after the daily quota resets — progress accumulates in `products.jsonl` across
# runs either way. Once there's a healthy sample, move to `02_explore_duplicates.py` to
# check how many are genuinely sold by multiple independent shops.
