select user_id, amount from {{ ref('transactions') }}
