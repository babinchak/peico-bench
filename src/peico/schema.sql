-- PEICO reference schema (v1, reference tables only).
-- The "physics" of the world: lines, tiers, coverages, defaults, rules, promos.
-- Generated entities (customers, policies, ...) come in a later build stage.
-- Money is integer CENTS. JSON-shaped columns are stored as TEXT(json).

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS tier_coverage_defaults;
DROP TABLE IF EXISTS eligibility_rules;
DROP TABLE IF EXISTS coverages;
DROP TABLE IF EXISTS tiers;
DROP TABLE IF EXISTS promotions;
DROP TABLE IF EXISTS discounts;
DROP TABLE IF EXISTS kb_documents;
DROP TABLE IF EXISTS product_lines;
DROP TABLE IF EXISTS states;
DROP TABLE IF EXISTS regions;

CREATE TABLE regions (
  region TEXT PRIMARY KEY,
  label  TEXT NOT NULL,
  notes  TEXT
);

CREATE TABLE states (
  state  TEXT PRIMARY KEY,
  region TEXT NOT NULL REFERENCES regions(region),
  name   TEXT NOT NULL,
  notes  TEXT
);

CREATE TABLE product_lines (
  line                 TEXT PRIMARY KEY,
  label                TEXT NOT NULL,
  category             TEXT NOT NULL,
  parent_line          TEXT REFERENCES product_lines(line),
  requires_suitability INTEGER NOT NULL DEFAULT 0,
  requires_underlying  TEXT,            -- json list or null
  notes                TEXT
);

CREATE TABLE tiers (
  tier_id    TEXT PRIMARY KEY,          -- "<LINE>:<CODE>"
  line       TEXT NOT NULL REFERENCES product_lines(line),
  code       TEXT NOT NULL,
  label      TEXT NOT NULL,
  position   INTEGER NOT NULL,
  sellable   INTEGER NOT NULL,
  retired_on TEXT,
  notes      TEXT
);

CREATE TABLE coverages (
  coverage_id TEXT PRIMARY KEY,         -- "<LINE>:<CODE>"
  line        TEXT NOT NULL REFERENCES product_lines(line),
  code        TEXT NOT NULL,
  label       TEXT NOT NULL,
  kind        TEXT NOT NULL,            -- limit | deductible | flag | feature
  unit        TEXT NOT NULL,            -- usd | usd_split | usd_daily | pct | bool | years
  notes       TEXT
);

CREATE TABLE tier_coverage_defaults (
  tier_id       TEXT NOT NULL REFERENCES tiers(tier_id),
  coverage_id   TEXT NOT NULL REFERENCES coverages(coverage_id),
  included      INTEGER NOT NULL,
  default_value TEXT,                   -- cents / "cents/cents" / decimal / bool / null
  editable      INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (tier_id, coverage_id)
);

CREATE TABLE eligibility_rules (
  rule_id         TEXT PRIMARY KEY,
  line            TEXT NOT NULL REFERENCES product_lines(line),
  tier_id         TEXT REFERENCES tiers(tier_id),
  coverage_id     TEXT REFERENCES coverages(coverage_id),
  state           TEXT REFERENCES states(state),
  effect          TEXT NOT NULL,        -- DENY | REQUIRE | PROHIBIT_FACTOR | GATE
  condition       TEXT,
  effective_start TEXT,
  effective_end   TEXT,
  reason_doc      TEXT NOT NULL REFERENCES kb_documents(doc_id),
  notes           TEXT
);

CREATE TABLE promotions (
  promo_code    TEXT PRIMARY KEY,
  label         TEXT NOT NULL,
  scope         TEXT,                   -- json
  window_start  TEXT,
  window_end    TEXT,
  effect        TEXT,                   -- json
  stacks_with   TEXT,                   -- json list
  caps          TEXT,                   -- json
  active        INTEGER NOT NULL,
  retired_rider INTEGER NOT NULL,
  doc_id        TEXT NOT NULL REFERENCES kb_documents(doc_id),
  notes         TEXT
);

CREATE TABLE discounts (
  discount_id TEXT PRIMARY KEY,
  code        TEXT NOT NULL,
  label       TEXT NOT NULL,
  effect      TEXT,                     -- json
  stack_order INTEGER NOT NULL,
  eligibility TEXT,
  notes       TEXT
);

CREATE TABLE kb_documents (
  doc_id     TEXT PRIMARY KEY,
  title      TEXT NOT NULL,
  category   TEXT NOT NULL,
  applies_to TEXT,                      -- json
  body_md    TEXT NOT NULL
);
