-- Bronze only carries each price's start date; this derives effective_to via
-- lead() so downstream models can join "what was the price on date X" without
-- redoing that lookup themselves.
with deduped as (
    select
        *,
        row_number() over (partition by price_history_id order by event_ts desc) as rn
    from read_parquet('{{ var("bronze_dir") }}/price.changed/**/*.parquet', union_by_name = true)
),

latest as (
    select
        price_history_id,
        product_upc,
        cast(price as double) as price,
        cast(effective_from as date) as effective_from
    from deduped
    where rn = 1
)

select
    price_history_id,
    product_upc,
    price,
    effective_from,
    lead(effective_from) over (
        partition by product_upc order by effective_from
    ) as effective_to
from latest
