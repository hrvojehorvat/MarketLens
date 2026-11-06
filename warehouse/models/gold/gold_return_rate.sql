-- returns.filed only carries order_item_id, not product_upc (that gap exists
-- all the way back in the event payload) -- so this resolves it straight from
-- store_db's order_items via the same Postgres attachment silver_products uses.
with return_products as (
    select
        returns.return_id,
        returns.refund_amount,
        order_items.product_upc
    from {{ ref('silver_returns') }} as returns
    inner join pg.public.order_items as order_items
        on order_items.id = returns.order_item_id
),

line_items as (
    select product_upc, count(*) as items_sold
    from {{ ref('silver_orders') }}
    group by product_upc
),

returns_agg as (
    select
        product_upc,
        count(*) as items_returned,
        round(sum(refund_amount), 2) as total_refunded
    from return_products
    group by product_upc
)

select
    line_items.product_upc,
    products.title,
    products.category_top,
    line_items.items_sold,
    coalesce(returns_agg.items_returned, 0) as items_returned,
    round(
        coalesce(returns_agg.items_returned, 0) / nullif(line_items.items_sold, 0)::double, 4
    ) as return_rate,
    coalesce(returns_agg.total_refunded, 0) as total_refunded
from line_items
left join returns_agg on returns_agg.product_upc = line_items.product_upc
left join {{ ref('silver_products') }} as products on products.product_upc = line_items.product_upc
order by return_rate desc
