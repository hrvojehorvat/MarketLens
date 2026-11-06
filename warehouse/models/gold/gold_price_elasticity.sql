-- Joins each order line to whatever price was actually in effect on that
-- order's date -- a ready-made dataset for later asking "did volume move
-- when price changed" (the ml/ phase).
select
    o.product_upc,
    o.order_date,
    p.price as price_at_order,
    sum(o.quantity) as units_sold,
    round(sum(o.line_total), 2) as revenue
from {{ ref('silver_orders') }} as o
inner join {{ ref('silver_price_history') }} as p
    on
        p.product_upc = o.product_upc
        and o.order_date >= p.effective_from
        and (o.order_date < p.effective_to or p.effective_to is null)
group by o.product_upc, o.order_date, p.price
order by o.product_upc, o.order_date
