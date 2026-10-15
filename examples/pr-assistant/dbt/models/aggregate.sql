select user_id, sum(amount) as amount
from {{ ref('spending') }}
group by user_id
