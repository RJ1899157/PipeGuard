select
    order_date,
    count(*)::bigint as completed_order_count,
    sum(order_total)::numeric(24, 2) as revenue
from {{ ref('orders') }}
where status = 'completed'
group by order_date
