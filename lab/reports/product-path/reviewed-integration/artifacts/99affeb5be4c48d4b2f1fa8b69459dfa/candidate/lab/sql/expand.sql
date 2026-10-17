ALTER TABLE orders ADD COLUMN IF NOT EXISTS amount_minor bigint;
UPDATE orders SET amount_minor = amount_rub * 100 WHERE amount_minor IS NULL;
ALTER TABLE orders ALTER COLUMN amount_minor SET NOT NULL;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='orders_money_consistent') THEN
  ALTER TABLE orders ADD CONSTRAINT orders_money_consistent CHECK(amount_minor >= 0 AND amount_minor % 100 = 0 AND amount_minor / 100 = amount_rub);
 END IF;
END $$;
