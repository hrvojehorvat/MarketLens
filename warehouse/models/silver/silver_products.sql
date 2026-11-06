-- The only silver model that doesn't read from bronze -- product/category
-- metadata was never part of any event payload, so this reads it straight
-- from store_db via the Postgres attachment configured in profiles.yml.
select
    upc as product_upc,
    title,
    brand,
    category,
    category_top
from pg.public.products
