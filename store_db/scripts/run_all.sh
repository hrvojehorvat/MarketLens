#!/usr/bin/env bash
# Rebuilds the whole store_db database from scratch against whatever products
# currently sit in ../catalog_sourcing/data/catalog/products.jsonl.
#
# This is a full rebuild, not an incremental update -- 01 drops and recreates
# every table, and 03-10 derive demand/pricing/merchant behavior from the
# entire current product set. There's no meaningful "just add the new ones"
# path with this design, so re-run the full sequence any time the catalog
# changes.
set -euo pipefail
cd "$(dirname "$0")/.."

scripts=(
    scripts/01_create_schema.py
    scripts/02_load_products.py
    scripts/03_generate_demand_profile.py
    scripts/04_generate_merchants.py
    scripts/05_generate_consignments_and_inventory.py
    scripts/06_generate_customers.py
    scripts/07_generate_price_history.py
    scripts/08_generate_orders.py
    scripts/09_generate_returns.py
    scripts/10_generate_reviews.py
)

for script in "${scripts[@]}"; do
    echo "=== $script ==="
    uv run "$script"
done

echo "=== scripts/verify.py ==="
uv run scripts/verify.py
