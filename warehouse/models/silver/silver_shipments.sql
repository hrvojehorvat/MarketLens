-- A real shipment legitimately produces two events (shipped, then delivered),
-- so the dedup key is (shipment_id, status), not shipment_id alone.
with deduped as (
    select
        *,
        row_number() over (
            partition by shipment_id, status order by event_ts desc
        ) as rn
    from read_parquet('{{ var("bronze_dir") }}/shipments.status_changed/**/*.parquet', union_by_name = true)
)

select
    shipment_id,
    order_id,
    carrier,
    tracking_number,
    status,
    cast(event_ts as timestamp) as status_at
from deduped
where rn = 1
