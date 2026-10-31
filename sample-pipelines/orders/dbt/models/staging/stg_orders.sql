select
    order_id,
    customer_id,
    ordered_at,
    (ordered_at at time zone 'UTC')::date as order_date,
    quantity,
    unit_price,
    (quantity * unit_price)::numeric(20, 2) as order_total,
    status
from {{ source('orders_raw', 'orders') }}
