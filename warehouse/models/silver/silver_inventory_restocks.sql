with deduped as (
    select
        *,
        row_number() over (
            partition by consignment_item_id order by event_ts desc
        ) as rn
    from read_parquet('{{ var("bronze_dir") }}/inventory.restocked/**/*.parquet', union_by_name = true)
)

select
    consignment_item_id,
    consignment_id,
    merchant_id,
    product_upc,
    quantity,
    cast(unit_cost as double) as unit_cost,
    cast(received_date as date) as received_date
from deduped
where rn = 1
