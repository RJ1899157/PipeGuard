with expected as (
    select order_date, count(*) as completed_order_count, sum(order_total) as revenue
    from {{ ref('orders') }} where status = 'completed' group by order_date
)
select coalesce(e.order_date, a.order_date) as order_date
from expected e full outer join {{ ref('daily_revenue') }} a using (order_date)
where e.revenue is distinct from a.revenue
   or e.completed_order_count is distinct from a.completed_order_count
