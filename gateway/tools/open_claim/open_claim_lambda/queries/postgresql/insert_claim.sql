-- insert_claim (PostgreSQL dialect, runs on Aurora DSQL)
--
-- Writes one claim: one card and one currency. Used by OpenClaimUseCase.
--
-- Parameters (psycopg named placeholders):
--   complaint_id    text       required, CMP- and a hash of the claim's content
--   creation_date   timestamp  required, the tool's "now" (AS_OF in demos), naive UTC
--   process_date    date       required, creation_date's date
--   customer_id     text       required
--   subcategory     text       required, Cargo no reconocido (fraud) or Cobro indebido (dispute)
--   product_id      text       required, the card
--   description     text       required, the customer's words and the transaction ids
--   claimed_amount  numeric    required, the transactions' total in the claim currency
--   currency        text       required
--   priority        text       required, High or Medium
--
-- The values pass the schema's CHECK constraints: category 'Transactions' and
-- reception_channel 'Web' (the chat runs in the web frontend). The id comes from
-- the claim's content, so a second run of the same claim fails with 23505 and
-- the use case reports the existing claim. RETURNING lets the repository read
-- the result with fetchall().
--
-- TODO(ledgerlens): W1 - INSERT ... RETURNING not yet run on a real Aurora DSQL cluster.
INSERT INTO complaints (
    complaint_id, creation_date, process_date, customer_id, case_type, category,
    subcategory, reception_channel, affected_product_id, description,
    claimed_amount, currency, priority, status, sla_breached, is_repeat_complainer
) VALUES (
    %(complaint_id)s, %(creation_date)s, %(process_date)s, %(customer_id)s, 'Claim', 'Transactions',
    %(subcategory)s, 'Web', %(product_id)s, %(description)s,
    %(claimed_amount)s, %(currency)s, %(priority)s, 'Open', false, false
)
RETURNING complaint_id
