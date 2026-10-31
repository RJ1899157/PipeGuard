select order_id from {{ ref('orders') }} where order_total < 0
