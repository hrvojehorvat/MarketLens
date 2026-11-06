select
    reviews.product_upc,
    products.title,
    products.category_top,
    count(*) as review_count,
    round(avg(reviews.rating), 2) as avg_rating
from {{ ref('silver_reviews') }} as reviews
left join {{ ref('silver_products') }} as products on products.product_upc = reviews.product_upc
group by reviews.product_upc, products.title, products.category_top
order by avg_rating asc
