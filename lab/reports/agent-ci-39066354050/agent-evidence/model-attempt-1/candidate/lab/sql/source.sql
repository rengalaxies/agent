CREATE TABLE IF NOT EXISTS lab_state (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 current_state text NOT NULL DEFAULT 'S0', billing_version integer NOT NULL DEFAULT 1,
 analytics_version integer NOT NULL DEFAULT 1, event_version integer NOT NULL DEFAULT 1,
 paused boolean NOT NULL DEFAULT false, watermark bigint, updated_at timestamptz NOT NULL DEFAULT now());
INSERT INTO lab_state(singleton) VALUES(true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS orders (
 seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 order_id text PRIMARY KEY, amount_rub bigint NOT NULL CHECK(amount_rub >= 0 AND amount_rub <= 92233720368547758),
 currency text NOT NULL CHECK(currency='RUB'), created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS outbox (
 seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, event_id uuid NOT NULL UNIQUE,
 order_id text NOT NULL REFERENCES orders(order_id), routing_key text NOT NULL,
 payload jsonb NOT NULL, published_at timestamptz, attempts integer NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS transition_log (
 target text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now(), detail jsonb NOT NULL);
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE OR REPLACE VIEW analytics.orders_v1 AS SELECT order_id, amount_rub, currency FROM orders;
