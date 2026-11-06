with deduped as (
    select
        *,
        row_number() over (partition by review_id order by event_ts desc) as rn
    from read_parquet('{{ var("bronze_dir") }}/reviews.posted/**/*.parquet', union_by_name = true)
)

select
    review_id,
    customer_id,
    product_upc,
    rating,
    review_text,
    cast(created_at as timestamp) as created_at
from deduped
where rn = 1
