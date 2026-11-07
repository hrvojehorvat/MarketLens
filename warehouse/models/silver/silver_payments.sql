with deduped as (
    select
        *,
        row_number() over (partition by payment_id order by event_ts desc) as rn
    from read_parquet('{{ var("bronze_dir") }}/payments.processed/**/*.parquet', union_by_name = true)
)

select
    payment_id,
    order_id,
    method,
    cast(amount as double) as amount,
    cast(paid_at as timestamp) as paid_at,
    status
from deduped
where rn = 1
