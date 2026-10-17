CREATE TABLE IF NOT EXISTS ledger (
 order_id text PRIMARY KEY, amount_minor bigint NOT NULL CHECK(amount_minor >= 0),
 currency text NOT NULL CHECK(currency='RUB'), created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS processed_events (
 event_id uuid PRIMARY KEY, order_id text NOT NULL REFERENCES ledger(order_id),
 processed_at timestamptz NOT NULL DEFAULT now());
