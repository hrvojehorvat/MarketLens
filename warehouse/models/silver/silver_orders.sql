-- One row per order line item, unnested out of bronze's array-of-items payload.
-- row_number() dedup handles the same order event having been replayed more
-- than once across different smoke-test runs during development.
with deduped as (
    select
        *,
        row_number() over (partition by order_id order by event_ts desc) as rn
    from read_parquet('{{ var("bronze_dir") }}/orders.placed/**/*.parquet', union_by_name = true)
),

latest as (
    select order_id, customer_id, order_date, status, items
    from deduped
    where rn = 1
)

select
    latest.order_id,
    latest.customer_id,
    cast(latest.order_date as date) as order_date,
    latest.status,
    item.product_upc as product_upc,
    item.quantity as quantity,
    item.unit_price as unit_price,
    round(item.quantity * item.unit_price, 2) as line_total
from latest, unnest(latest.items) as t (item)
