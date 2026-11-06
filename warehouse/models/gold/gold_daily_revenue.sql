select
    order_date,
    count(distinct order_id) as order_count,
    round(sum(line_total), 2) as revenue
from {{ ref('silver_orders') }}
group by order_date
order by order_date
