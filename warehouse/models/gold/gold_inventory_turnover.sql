with restocked as (
    select product_upc, sum(quantity) as total_restocked
    from {{ ref('silver_inventory_restocks') }}
    group by product_upc
),

sold as (
    select product_upc, sum(quantity) as total_sold
    from {{ ref('silver_orders') }}
    group by product_upc
)

select
    coalesce(restocked.product_upc, sold.product_upc) as product_upc,
    products.title,
    products.category_top,
    coalesce(restocked.total_restocked, 0) as total_restocked,
    coalesce(sold.total_sold, 0) as total_sold,
    round(
        coalesce(sold.total_sold, 0) / nullif(coalesce(restocked.total_restocked, 0), 0), 2
    ) as turnover_ratio
from restocked
full outer join sold on restocked.product_upc = sold.product_upc
left join {{ ref('silver_products') }} as products
    on products.product_upc = coalesce(restocked.product_upc, sold.product_upc)
order by turnover_ratio desc
