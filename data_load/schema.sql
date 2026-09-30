-- LedgerLens Aurora DSQL schema: the single source of truth for types and constraints.
-- data_load runs the bank/pii CREATE TABLE statements in DuckDB (validation) and in DSQL.
-- File rules: statements end with a semicolon; no semicolon or double dash inside string literals.

CREATE SCHEMA IF NOT EXISTS bank;
CREATE SCHEMA IF NOT EXISTS pii;
CREATE SCHEMA IF NOT EXISTS app;

-- pii and bank: organizer data. Dropped and recreated by every load; read-only for the app.
CREATE TABLE pii.customers (
  customer_id varchar(30) PRIMARY KEY, document_number varchar(30) NOT NULL, document_type varchar(12) NOT NULL,
  first_name varchar(100) NOT NULL, last_name varchar(100) NOT NULL, date_of_birth date NOT NULL, gender varchar(1),
  email varchar(100), mobile_phone varchar(20), landline_phone varchar(20), address varchar(200), city varchar(100) NOT NULL,
  state varchar(100) NOT NULL, country varchar(50) NOT NULL, postal_code varchar(10), detected_accent varchar(50),
  segment varchar(50) NOT NULL, credit_score integer, estimated_monthly_income numeric(15,2), occupation varchar(100),
  marital_status varchar(20), education_level varchar(50), registration_date timestamp NOT NULL,
  registration_branch_id varchar(30), customer_status varchar(20) NOT NULL, last_updated timestamp NOT NULL,
  accepts_marketing boolean NOT NULL
);
CREATE TABLE pii.service_agents (
  agent_id varchar(30) PRIMARY KEY, employee_code varchar(15) NOT NULL, first_name varchar(100) NOT NULL,
  last_name varchar(100) NOT NULL, email varchar(100), phone varchar(20), native_accent varchar(50) NOT NULL,
  country_of_origin varchar(50) NOT NULL, assigned_branch_id varchar(30), agent_type varchar(30) NOT NULL,
  experience_level varchar(20) NOT NULL, languages varchar(100) NOT NULL, specialty varchar(100), hire_date date NOT NULL,
  avg_csat numeric(3,2), total_monthly_interactions integer, agent_status varchar(20) NOT NULL, work_shift varchar(20) NOT NULL
);
CREATE TABLE bank.products (
  product_id varchar(30) PRIMARY KEY, customer_id varchar(30) NOT NULL,
  product_type varchar(50) NOT NULL CHECK (product_type IN ('Cuenta Ahorro','Tarjeta Crédito','Cuenta Corriente','Tarjeta Débito','Préstamo Personal','Préstamo Hipotecario','Inversión','Seguro')),
  product_number varchar(30) NOT NULL, currency varchar(3) NOT NULL, current_balance numeric(15,2) NOT NULL,
  credit_limit numeric(15,2), interest_rate numeric(5,2), opening_date date NOT NULL, expiration_date date,
  opening_branch_id varchar(30), product_status varchar(20) NOT NULL CHECK (product_status IN ('Active','Blocked','Closed','Suspended')),
  opening_channel varchar(30) NOT NULL, has_linked_app boolean NOT NULL, days_past_due integer,
  last_transaction_date timestamp, last_updated timestamp NOT NULL
);
CREATE TABLE bank.branches (
  branch_id varchar(30) PRIMARY KEY, branch_code varchar(10) NOT NULL, branch_name varchar(100) NOT NULL,
  branch_type varchar(30) NOT NULL, address varchar(200) NOT NULL, city varchar(100) NOT NULL, state varchar(100) NOT NULL,
  country varchar(50) NOT NULL, postal_code varchar(10), geographic_zone varchar(50) NOT NULL, phone varchar(20) NOT NULL,
  email varchar(100), opening_time time NOT NULL, closing_time time NOT NULL, has_atms boolean NOT NULL, atm_count integer,
  has_teller_windows boolean NOT NULL, teller_window_count integer, latitude numeric(10,7), longitude numeric(10,7),
  branch_opening_date date NOT NULL, branch_status varchar(20) NOT NULL
);
CREATE TABLE bank.marketing_campaigns (
  campaign_id varchar(30) PRIMARY KEY, campaign_name varchar(150) NOT NULL, description text, campaign_type varchar(50) NOT NULL,
  campaign_objective varchar(100) NOT NULL, promoted_product varchar(50), target_segment varchar(50), target_country varchar(50),
  start_date date NOT NULL, end_date date NOT NULL, budget numeric(12,2), campaign_status varchar(20) NOT NULL,
  expected_conversion_rate numeric(5,2)
);
CREATE TABLE bank.daily_exchange_rates (
  date date NOT NULL, source_currency varchar(3) NOT NULL, target_currency varchar(3) NOT NULL,
  exchange_rate numeric(12,6) NOT NULL, buy_rate numeric(12,6), sell_rate numeric(12,6), source varchar(50),
  PRIMARY KEY (date, source_currency, target_currency)
);
CREATE TABLE bank.transactions (
  transaction_id varchar(30) PRIMARY KEY, transaction_date timestamp NOT NULL, process_date date NOT NULL,
  product_id varchar(30) NOT NULL, customer_id varchar(30) NOT NULL, transaction_type varchar(50) NOT NULL,
  transaction_category varchar(50), amount numeric(15,2) NOT NULL, currency varchar(3) NOT NULL, amount_usd numeric(15,2),
  channel varchar(30) NOT NULL, branch_id varchar(30), merchant_name varchar(150), merchant_category varchar(50),
  transaction_country varchar(50) NOT NULL, transaction_city varchar(100),
  transaction_status varchar(20) NOT NULL CHECK (transaction_status IN ('Approved','Declined','Pending','Reversed')),
  response_code varchar(10) CHECK (response_code IN ('00','05','14','51','54')),
  is_fraud boolean NOT NULL, fraud_score numeric(5,2), latitude numeric(10,7), longitude numeric(10,7)
);
CREATE TABLE bank.call_center_interactions (
  interaction_id varchar(30) PRIMARY KEY, interaction_date timestamp NOT NULL, process_date date NOT NULL,
  customer_id varchar(30) NOT NULL, agent_id varchar(30), interaction_type varchar(30) NOT NULL, channel varchar(30) NOT NULL,
  contact_reason varchar(100) NOT NULL, reason_category varchar(50) NOT NULL, duration_seconds integer, wait_time_seconds integer,
  was_resolved boolean, requires_followup boolean NOT NULL, detected_sentiment varchar(20), sentiment_score numeric(3,2),
  customer_detected_accent varchar(50), agent_used_accent varchar(50), was_escalated boolean NOT NULL,
  mentioned_products varchar(200), has_transcript boolean NOT NULL, has_recording boolean NOT NULL
);
CREATE TABLE bank.call_transcripts (
  transcript_id varchar(30) PRIMARY KEY, interaction_id varchar(30) NOT NULL, process_date date NOT NULL,
  customer_id varchar(30) NOT NULL, agent_id varchar(30) NOT NULL, full_text text NOT NULL, customer_text text, agent_text text,
  detected_language varchar(10) NOT NULL, detected_accent varchar(50), accent_confidence numeric(3,2),
  detected_keywords varchar(500), mentioned_entities text, detected_intents varchar(300), main_topics varchar(300),
  transcription_model varchar(50) NOT NULL, audio_quality varchar(20), duration_seconds integer
);
CREATE TABLE bank.satisfaction_surveys (
  survey_id varchar(30) PRIMARY KEY, survey_date timestamp NOT NULL, process_date date NOT NULL,
  interaction_id varchar(30) NOT NULL, customer_id varchar(30), agent_id varchar(30), survey_type varchar(20) NOT NULL,
  send_channel varchar(30), main_score smallint, nps_category varchar(20), question_1_text text, question_1_response smallint,
  question_2_text text, question_2_response smallint, question_3_text text, question_3_response smallint, open_comments text,
  comment_sentiment varchar(20), response_time_hours numeric(8,2), campaign_response_rate numeric(5,2)
);
CREATE TABLE bank.digital_events (
  event_id varchar(30) PRIMARY KEY, event_date timestamp NOT NULL, process_date date NOT NULL, customer_id varchar(30),
  session_id varchar(50) NOT NULL, event_type varchar(50) NOT NULL, event_category varchar(50) NOT NULL, channel varchar(30) NOT NULL,
  platform varchar(30), browser varchar(50), app_version varchar(20), page_url varchar(300), page_title varchar(200),
  action varchar(100), element_id varchar(100), product_id varchar(30), event_value numeric(15,2), duration_seconds integer,
  ip_address varchar(45), ip_country varchar(50), ip_city varchar(100), is_mobile boolean NOT NULL, referrer varchar(300),
  utm_source varchar(100), utm_medium varchar(100), utm_campaign varchar(100)
);
CREATE TABLE bank.complaints (
  complaint_id varchar(30) PRIMARY KEY, creation_date timestamp NOT NULL, process_date date NOT NULL,
  customer_id varchar(30) NOT NULL, case_type varchar(30) NOT NULL,
  category varchar(100) NOT NULL CHECK (category IN ('Branch','Fees','Service','Technical','Transactions')),
  subcategory varchar(100),
  reception_channel varchar(30) NOT NULL CHECK (reception_channel IN ('Call Center','Email','Web','App','Branch','Regulator')),
  affected_product_id varchar(30), related_branch_id varchar(30), origin_interaction_id varchar(30), description text NOT NULL,
  claimed_amount numeric(15,2), currency varchar(3), priority varchar(20) NOT NULL, status varchar(30) NOT NULL,
  assigned_agent_id varchar(30), assignment_date timestamp, first_response_date timestamp, resolution_date timestamp,
  closing_date timestamp, sla_breached boolean NOT NULL, resolution_days integer, resolution text,
  compensation_granted numeric(15,2), resolution_satisfaction smallint, is_repeat_complainer boolean NOT NULL
);
CREATE TABLE bank.campaign_sends (
  send_id varchar(30) PRIMARY KEY, send_date timestamp NOT NULL, process_date date NOT NULL, campaign_id varchar(30) NOT NULL,
  customer_id varchar(30) NOT NULL, send_channel varchar(30) NOT NULL, template_used varchar(100), subject varchar(200),
  send_status varchar(20) NOT NULL, was_delivered boolean NOT NULL, was_opened boolean, open_date timestamp, was_clicked boolean,
  click_date timestamp, click_count integer, had_conversion boolean NOT NULL, conversion_date timestamp,
  conversion_value numeric(15,2), open_device varchar(30), open_country varchar(50), failure_reason varchar(200),
  send_cost numeric(10,4)
);

CREATE VIEW bank.customer_profile AS
  SELECT customer_id, first_name, country, customer_status FROM pii.customers;
CREATE VIEW bank.agent_roster AS
  SELECT agent_id, languages, specialty, work_shift, agent_status FROM pii.service_agents;

-- app: written by LedgerLens. Created once, never dropped by a load.
CREATE TABLE IF NOT EXISTS app.approvals (
  approval_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), session_id varchar(100) NOT NULL, customer_id varchar(30) NOT NULL,
  action varchar(20) NOT NULL CHECK (action IN ('block_card','open_claim')), target_ids text NOT NULL, readback text NOT NULL,
  status varchar(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','used')),
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL, approved_at timestamptz, used_at timestamptz
);
CREATE TABLE IF NOT EXISTS app.cases (
  case_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), customer_id varchar(30) NOT NULL, claim_id varchar(40),
  queue varchar(50) NOT NULL, priority varchar(10) NOT NULL, reason varchar(30) NOT NULL, customer_language varchar(5) NOT NULL,
  payload jsonb NOT NULL, status varchar(20) NOT NULL DEFAULT 'open', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app.audit_log (
  audit_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), created_at timestamptz NOT NULL DEFAULT now(), actor_sub varchar(64) NOT NULL,
  customer_id varchar(30), session_id varchar(100), tool varchar(60) NOT NULL, approval_id uuid, input jsonb, result jsonb,
  outcome varchar(20) NOT NULL
);
CREATE TABLE IF NOT EXISTS app.feedback (
  feedback_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_sub varchar(64) NOT NULL, session_id varchar(100) NOT NULL,
  message text NOT NULL, feedback_type varchar(10) NOT NULL CHECK (feedback_type IN ('positive','negative')), comment text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app.load_manifest (
  table_name varchar(60) NOT NULL, as_of timestamp NOT NULL, window_start date NOT NULL, window_end date NOT NULL,
  source_uri text NOT NULL, source_files integer NOT NULL, source_etag_digest varchar(64) NOT NULL,
  staged_uri text NOT NULL, staged_sha256 varchar(64) NOT NULL, rows_staged bigint NOT NULL, rows_loaded bigint NOT NULL,
  loaded_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (table_name, as_of)
);
CREATE TABLE IF NOT EXISTS app.card_blocks (
  card_id varchar(30) PRIMARY KEY, customer_id varchar(30) NOT NULL, approval_id uuid NOT NULL,
  business_date date NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app.claims (
  claim_id varchar(40) PRIMARY KEY, customer_id varchar(30) NOT NULL, approval_id uuid NOT NULL,
  claim_type varchar(10) NOT NULL CHECK (claim_type IN ('fraud','dispute')), transaction_ids jsonb NOT NULL,
  claimed_amount numeric(15,2) NOT NULL, currency varchar(3) NOT NULL, customer_statement varchar(500),
  business_date date NOT NULL, deadline_date date NOT NULL, rule_ids jsonb NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','handed_off','closed')),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Roles: created only if missing. Grants: re-applied after every load (recreated tables lose them).
CREATE ROLE ll_read WITH LOGIN;
CREATE ROLE ll_write WITH LOGIN;
CREATE ROLE ll_approvals WITH LOGIN;
CREATE ROLE ll_feedback WITH LOGIN;
GRANT USAGE ON SCHEMA bank TO ll_read;
GRANT USAGE ON SCHEMA app TO ll_read;
GRANT SELECT ON bank.products, bank.transactions, bank.complaints, bank.customer_profile, bank.agent_roster TO ll_read;
GRANT SELECT ON app.approvals, app.cases, app.card_blocks, app.claims TO ll_read;
GRANT USAGE ON SCHEMA bank TO ll_write;
GRANT USAGE ON SCHEMA app TO ll_write;
GRANT SELECT ON bank.products, bank.transactions, bank.complaints, bank.customer_profile, bank.agent_roster TO ll_write;
GRANT SELECT ON app.approvals, app.cases, app.card_blocks, app.claims TO ll_write;
GRANT INSERT, UPDATE ON app.approvals, app.claims TO ll_write;
GRANT INSERT ON app.card_blocks, app.cases, app.audit_log TO ll_write;
GRANT USAGE ON SCHEMA app TO ll_approvals;
GRANT SELECT, UPDATE ON app.approvals TO ll_approvals;
GRANT USAGE ON SCHEMA app TO ll_feedback;
GRANT INSERT ON app.feedback TO ll_feedback;

-- Secondary indexes, only for queries the tools run. bank: rebuilt after every load. app: created once.
CREATE INDEX ASYNC idx_transactions_customer_date ON bank.transactions (customer_id, transaction_date);
CREATE INDEX ASYNC idx_products_customer ON bank.products (customer_id);
CREATE INDEX ASYNC idx_complaints_customer_date ON bank.complaints (customer_id, creation_date);
CREATE INDEX ASYNC idx_cases_customer_date ON app.cases (customer_id, created_at);
CREATE INDEX ASYNC idx_claims_customer_date ON app.claims (customer_id, business_date);
