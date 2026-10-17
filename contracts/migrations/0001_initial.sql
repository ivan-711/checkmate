-- 0001_initial: the 13:15 frozen schema (architecture v0.5.2 §4, §11, §22.3; ADR-016 §6).
-- Applied in autocommit mode by contracts/migrations/apply.py (continuous aggregates
-- cannot be created inside a transaction). event_type is TEXT + CHECK, not an enum;
-- migration 0002_frontdesk_steps widens the list after the 16:00 gate.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS schema_migration (
  version     text PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now()
);

-- Source and normalized records -------------------------------------------------------
CREATE TABLE source_record (
  id               uuid PRIMARY KEY,
  source_system    text NOT NULL,
  source_local_id  text NOT NULL,
  kind             text NOT NULL CHECK (kind IN ('FHIR_PATIENT','CSV_ROW','TEMPLATED_SPECIALIST','ONC_BENCH','FRONTDESK_INTAKE')),
  raw_payload      jsonb NOT NULL,
  payload_sha256   text NOT NULL,
  is_constructed   boolean NOT NULL DEFAULT false,
  ingested_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_system, source_local_id)
);

CREATE TABLE normalized_record (
  record_id            uuid PRIMARY KEY REFERENCES source_record(id) ON DELETE CASCADE,
  given_name           text,
  family_name          text,
  given_name_folded    text,
  family_name_folded   text,
  birth_date           date,
  birth_year           int,
  birth_month          int,
  birth_day            int,
  sex                  text,
  phone_e164           text,
  address_line         text,
  zip5                 text
);

CREATE TABLE block_key (
  key_type   text NOT NULL,
  key_value  text NOT NULL,
  record_id  uuid NOT NULL REFERENCES source_record(id) ON DELETE CASCADE,
  PRIMARY KEY (key_type, key_value, record_id)
);

-- Pairs and append-only decisions -----------------------------------------------------
CREATE TABLE intake_session (
  id                   uuid PRIMARY KEY,
  created_at           timestamptz NOT NULL DEFAULT now(),
  language             text NOT NULL CHECK (language IN ('ES','EN')),
  agent_mode           text NOT NULL CHECK (agent_mode IN ('LIVE','REPLAY')),
  scenario_context_id  text,
  prompt_version       text NOT NULL,
  tool_schema_version  text NOT NULL,
  model_id             text,
  intake_record_id     uuid REFERENCES source_record(id),
  intake_args_sha256   text,
  closed_at            timestamptz
);

CREATE TABLE candidate_pair (
  id                 uuid PRIMARY KEY,
  record_a_id        uuid NOT NULL REFERENCES source_record(id),
  record_b_id        uuid NOT NULL REFERENCES source_record(id),
  block_keys         text[] NOT NULL DEFAULT '{}',
  origin             text NOT NULL CHECK (origin IN ('MATCH_RUN','FRONTDESK_HANDOFF')),
  intake_session_id  uuid REFERENCES intake_session(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (record_a_id < record_b_id),
  UNIQUE (record_a_id, record_b_id)
);
CREATE INDEX candidate_pair_origin_idx ON candidate_pair (origin);

CREATE TABLE match_decision (
  id                    uuid PRIMARY KEY,
  pair_id               uuid NOT NULL REFERENCES candidate_pair(id),
  version               int NOT NULL CHECK (version >= 1),
  logit                 double precision NOT NULL,
  p                     double precision NOT NULL CHECK (p >= 0 AND p <= 1),
  raw_score             double precision NOT NULL,
  band                  text NOT NULL CHECK (band IN ('AUTO_LINK','REVIEW','KEEP_SEPARATE')),
  negative_rules_fired  text[] NOT NULL DEFAULT '{}',
  evidence_snapshot     jsonb NOT NULL,
  status                text NOT NULL CHECK (status IN ('PROPOSED','LINKED','REJECTED','REVOKED')),
  actor                 text NOT NULL,
  actor_type            text NOT NULL CHECK (actor_type IN ('AGENT','REGISTRAR','PATIENT','SYSTEM')),
  reason_code           text CHECK (reason_code IN ('DIFFERENT_PERSON','INSUFFICIENT_EVIDENCE')),
  note                  text,
  decided_at            timestamptz NOT NULL DEFAULT now(),
  scorer_version        text NOT NULL,
  threshold_set_id      text NOT NULL,
  CHECK (status NOT IN ('REJECTED','REVOKED') OR reason_code IS NOT NULL),
  UNIQUE (pair_id, version)
);
CREATE INDEX match_decision_current_idx ON match_decision (pair_id, version DESC);

CREATE TABLE not_a_match (
  record_a_id  uuid NOT NULL REFERENCES source_record(id),
  record_b_id  uuid NOT NULL REFERENCES source_record(id),
  decision_id  uuid NOT NULL REFERENCES match_decision(id),
  actor        text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (record_a_id, record_b_id)
);

-- Entities (union-find over LINKED edges; golden record derived on read) ---------------
CREATE TABLE entity (
  id          uuid PRIMARY KEY,
  version     int NOT NULL DEFAULT 1,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE entity_member (
  entity_id         uuid NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  source_record_id  uuid NOT NULL REFERENCES source_record(id),
  PRIMARY KEY (entity_id, source_record_id),
  UNIQUE (source_record_id)
);

-- Safety alerts (DetectedIssue-shaped) ------------------------------------------------
CREATE TABLE safety_alert (
  id                  uuid PRIMARY KEY,
  entity_id           uuid NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  rule_id             text NOT NULL DEFAULT 'BL-AMOX-01',
  rule_version        text NOT NULL DEFAULT 'v1',
  tier                text NOT NULL CHECK (tier IN ('A','B')),
  allergy_record_id   uuid NOT NULL REFERENCES source_record(id),
  allergy_resource_id text NOT NULL,
  order_record_id     uuid NOT NULL REFERENCES source_record(id),
  order_resource_id   text NOT NULL,
  revealed_by_merge   boolean NOT NULL,
  severity            text NOT NULL DEFAULT 'moderate',
  status              text NOT NULL CHECK (status IN ('PRELIMINARY','RETRACTED')),
  card_text           text NOT NULL,
  citation            jsonb,
  constructed_scenario boolean NOT NULL DEFAULT false,
  identified_at       timestamptz NOT NULL DEFAULT now(),
  retracted_at        timestamptz
);

-- Thresholds, demo sessions, evaluation ----------------------------------------------
CREATE TABLE threshold_set (
  thresholds_id       text PRIMARY KEY,
  c_low               double precision NOT NULL,
  c_high              double precision NOT NULL,
  t_low_display       double precision,
  t_high_display      double precision,
  platt_a             double precision,
  platt_b             double precision,
  auto_link_enabled   boolean NOT NULL DEFAULT false,
  is_calibrated       boolean NOT NULL DEFAULT false,
  source_run_id       text,
  is_current          boolean NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (c_low <= c_high)
);
CREATE UNIQUE INDEX threshold_set_one_current ON threshold_set (is_current) WHERE is_current;
INSERT INTO threshold_set (thresholds_id, c_low, c_high, auto_link_enabled, is_calibrated, is_current)
VALUES ('provisional-0', 0.0, 2.0, false, false, true);

CREATE TABLE demo_session (
  id                   uuid PRIMARY KEY,
  scenario_id          text NOT NULL,
  scorer_version       text NOT NULL,
  threshold_set_id     text NOT NULL,
  snapshot             jsonb,
  previous_session_id  uuid,
  created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE eval_run (
  id               uuid PRIMARY KEY,
  manifest         jsonb NOT NULL,
  manifest_sha256  text NOT NULL,
  executor         text NOT NULL CHECK (executor IN ('LOCAL_POOL','MODAL')),
  status           text NOT NULL,
  git_sha          text,
  started_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz
);

CREATE TABLE eval_result (
  run_id           uuid NOT NULL REFERENCES eval_run(id) ON DELETE CASCADE,
  split            text NOT NULL,
  dataset          text NOT NULL,
  regime           text NOT NULL,
  tier             text NOT NULL,
  operating_point  text NOT NULL,
  category         text NOT NULL,
  metrics          jsonb NOT NULL,
  PRIMARY KEY (run_id, split, dataset, regime, tier, operating_point, category)
);

-- Idempotency (architecture §5) --------------------------------------------------------
CREATE TABLE idempotency_record (
  scope           text NOT NULL,
  key             text NOT NULL,
  request_sha256  text NOT NULL,
  status_code     int NOT NULL,
  response        jsonb NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope, key)
);

-- FrontDesk state (ADR-016 §5) ---------------------------------------------------------
CREATE TABLE intake_turn (
  session_id         uuid NOT NULL REFERENCES intake_session(id) ON DELETE CASCADE,
  turn_index         int NOT NULL CHECK (turn_index >= 0),
  client_request_id  text NOT NULL,
  request_sha256     text NOT NULL,
  status             text NOT NULL CHECK (status IN ('IN_PROGRESS','COMPLETED','FAILED')),
  claimed_at         timestamptz NOT NULL DEFAULT now(),
  completed_at       timestamptz,
  user_text          text NOT NULL,
  response           jsonb,
  degraded           text,
  PRIMARY KEY (session_id, turn_index),
  UNIQUE (session_id, client_request_id)
);

CREATE TABLE agent_tool_call (
  id                 uuid PRIMARY KEY,
  session_id         uuid NOT NULL REFERENCES intake_session(id) ON DELETE CASCADE,
  turn_index         int NOT NULL,
  step_index         int NOT NULL,
  tool_name          text NOT NULL,
  args               jsonb,
  args_sha256        text NOT NULL,
  grounding_ok       boolean NOT NULL DEFAULT true,
  gate_outcome       text NOT NULL CHECK (gate_outcome IN ('ALLOW','DENY')),
  reason_code        text,
  evidence_ids       uuid[] NOT NULL DEFAULT '{}',
  evidence_snapshot  jsonb NOT NULL,
  effect_key         text UNIQUE,
  effect_status      text NOT NULL CHECK (effect_status IN ('APPLIED','REPLAYED','NONE')),
  effect_ref         text,
  policy_version     text NOT NULL,
  latency_ms         int NOT NULL DEFAULT 0,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, turn_index, step_index)
);

CREATE TABLE intake_history_item (
  id                uuid PRIMARY KEY,
  intake_record_id  uuid NOT NULL REFERENCES source_record(id) ON DELETE CASCADE,
  kind              text NOT NULL CHECK (kind IN ('ALLERGY','MEDICATION','CONDITION','OTHER')),
  text              text NOT NULL,
  evidence_quote    text NOT NULL,
  verification      text NOT NULL DEFAULT 'AGENT_INTAKE_UNVERIFIED' CHECK (verification = 'AGENT_INTAKE_UNVERIFIED'),
  created_at        timestamptz NOT NULL DEFAULT now()
);

-- Event log hypertable (architecture §4, §11; ADR-016 §6) ------------------------------
CREATE TABLE event_log (
  ts                 timestamptz NOT NULL DEFAULT now(),
  event_id           uuid NOT NULL,
  event_type         text NOT NULL CHECK (event_type IN (
    'RECORD_INGESTED','MATCH_RUN_COMPLETED','PAIR_SCORED','LINK_APPROVED','LINK_REJECTED','LINK_REVOKED',
    'ENTITY_MERGED','ENTITY_SPLIT','ALERT_RAISED','ALERT_RETRACTED','WHATIF_APPLIED','DEMO_RESET','DEMO_RESTORED',
    'EXPLANATION_GENERATED','EXTERNAL_CALL','EVAL_RUN_STARTED','EVAL_RUN_FINISHED',
    'INTAKE_STARTED','AGENT_TOOL_CALLED','INTAKE_HANDOFF_CREATED','AGENT_TURN_DEGRADED')),
  request_id         text,
  run_id             uuid,
  entry_point        text NOT NULL CHECK (entry_point IN ('API','CLI','EVAL_WORKER','REPLAY','AGENT')),
  entity_id          uuid,
  pair_id            uuid,
  decision_id        uuid,
  actor              text NOT NULL,
  actor_type         text NOT NULL CHECK (actor_type IN ('AGENT','REGISTRAR','PATIENT','SYSTEM')),
  band               text CHECK (band IS NULL OR band IN ('AUTO_LINK','REVIEW','KEEP_SEPARATE')),
  outcome            text,
  latency_ms         int,
  mode               text NOT NULL CHECK (mode IN ('LIVE','LOCAL','REPLAY')),
  versions           jsonb NOT NULL DEFAULT '{}'::jsonb,
  payload            jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- v0.4 intake columns, nullable, in the 13:15 migration so no hypertable change at 18:00
  intake_session_id  uuid,
  tool_call_id       uuid,
  tool_name          text,
  gate_outcome       text CHECK (gate_outcome IS NULL OR gate_outcome IN ('ALLOW','DENY')),
  reason_code        text,
  evidence_ids       uuid[],
  evidence_snapshot  jsonb,
  client_request_id  text,
  effect_status      text CHECK (effect_status IS NULL OR effect_status IN ('APPLIED','REPLAYED','NONE')),
  PRIMARY KEY (ts, event_id)
);
SELECT create_hypertable('event_log', 'ts', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX event_log_entity_idx ON event_log (entity_id, ts DESC) WHERE entity_id IS NOT NULL;
CREATE INDEX event_log_intake_idx ON event_log (intake_session_id, ts DESC) WHERE intake_session_id IS NOT NULL;
CREATE INDEX event_log_type_idx ON event_log (event_type, ts DESC);

-- Continuous aggregates, all real-time (materialized_only = false) ---------------------
CREATE MATERIALIZED VIEW band_flow_1m WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', ts) AS bucket, band, count(*) AS scored
FROM event_log
WHERE event_type = 'PAIR_SCORED'
GROUP BY bucket, band
WITH NO DATA;
ALTER MATERIALIZED VIEW band_flow_1m SET (timescaledb.materialized_only = false);
SELECT add_continuous_aggregate_policy('band_flow_1m',
  start_offset => INTERVAL '1 hour', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute');

CREATE MATERIALIZED VIEW review_outcomes_5m WITH (timescaledb.continuous) AS
SELECT time_bucket('5 minutes', ts) AS bucket, outcome,
       count(*) AS decisions, avg(latency_ms) AS mean_latency_ms, max(latency_ms) AS max_latency_ms
FROM event_log
WHERE event_type IN ('LINK_APPROVED','LINK_REJECTED')
GROUP BY bucket, outcome
WITH NO DATA;
ALTER MATERIALIZED VIEW review_outcomes_5m SET (timescaledb.materialized_only = false);
SELECT add_continuous_aggregate_policy('review_outcomes_5m',
  start_offset => INTERVAL '1 hour', end_offset => INTERVAL '5 minutes', schedule_interval => INTERVAL '5 minutes');

CREATE MATERIALIZED VIEW agent_gate_5m WITH (timescaledb.continuous) AS
SELECT time_bucket('5 minutes', ts) AS bucket, tool_name, gate_outcome, mode, count(*) AS calls
FROM event_log
WHERE event_type = 'AGENT_TOOL_CALLED'
GROUP BY bucket, tool_name, gate_outcome, mode
WITH NO DATA;
ALTER MATERIALIZED VIEW agent_gate_5m SET (timescaledb.materialized_only = false);
SELECT add_continuous_aggregate_policy('agent_gate_5m',
  start_offset => INTERVAL '1 hour', end_offset => INTERVAL '5 minutes', schedule_interval => INTERVAL '5 minutes');
