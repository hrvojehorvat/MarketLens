with deduped as (
    select
        *,
        row_number() over (partition by return_id order by event_ts desc) as rn
    from read_parquet('{{ var("bronze_dir") }}/returns.filed/**/*.parquet', union_by_name = true)
)

select
    return_id,
    order_id,
    order_item_id,
    reason,
    refund_amount,
    cast(returned_at as timestamp) as returned_at
from deduped
where rn = 1
