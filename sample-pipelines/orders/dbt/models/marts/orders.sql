select order_id, customer_id, ordered_at, order_date, quantity, unit_price, order_total, status
from {{ ref('stg_orders') }}
