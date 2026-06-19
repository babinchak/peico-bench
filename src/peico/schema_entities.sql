-- PEICO entity (generator-stage) schema: the live world the agent navigates.
-- Created and populated by generate.py AFTER build_reference.py. Money in cents.
-- FKs point at reference tables where they exist; readable deterministic ids for
-- the curated golden set (swap to UUIDs for the full-scale generator later).

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS claims;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS loyalty_ledger;
DROP TABLE IF EXISTS suitability_records;
DROP TABLE IF EXISTS policy_objects;
DROP TABLE IF EXISTS policy_coverages;
DROP TABLE IF EXISTS policies;
DROP TABLE IF EXISTS bundles;
DROP TABLE IF EXISTS pets;
DROP TABLE IF EXISTS dwellings;
DROP TABLE IF EXISTS vehicles;
DROP TABLE IF EXISTS household_members;
DROP TABLE IF EXISTS bi_signals;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS addresses;

CREATE TABLE addresses (
  address_id TEXT PRIMARY KEY,
  line1      TEXT NOT NULL,
  city       TEXT NOT NULL,
  state      TEXT NOT NULL REFERENCES states(state),
  zip        TEXT NOT NULL,
  region     TEXT NOT NULL REFERENCES regions(region)
);

CREATE TABLE customers (
  cust_id         TEXT PRIMARY KEY,
  legacy_acct     TEXT,                 -- EVERGREEN id; may be NULL or mismatched (quirk)
  legacy_mismatch INTEGER NOT NULL DEFAULT 0,
  status          TEXT NOT NULL,        -- PROSPECT | CUSTOMER
  first_name      TEXT NOT NULL,
  last_name       TEXT NOT NULL,
  dob             TEXT NOT NULL,
  email           TEXT,
  phone           TEXT,
  address_id      TEXT REFERENCES addresses(address_id),
  peico_risk      INTEGER,              -- 300..850
  risk_components TEXT,                 -- json (auditable; CA credit weighted 0)
  tenure_start    TEXT,
  loyalty_tier    TEXT,
  loyalty_points  INTEGER NOT NULL DEFAULT 0,   -- cache == sum(loyalty_ledger.delta_points)
  created_at      TEXT
);

CREATE TABLE bi_signals (
  cust_id              TEXT PRIMARY KEY REFERENCES customers(cust_id),
  churn_propensity_bps INTEGER,
  upsell_propensity_bps INTEGER,
  price_sensitivity_bps INTEGER,
  clv_cents            INTEGER,
  fraud_flag           INTEGER NOT NULL DEFAULT 0,
  contactability       TEXT
);

CREATE TABLE household_members (
  member_id      TEXT PRIMARY KEY,
  cust_id        TEXT NOT NULL REFERENCES customers(cust_id),
  role           TEXT NOT NULL,         -- SPOUSE | DRIVER | DEPENDENT
  first_name     TEXT,
  last_name      TEXT,
  dob            TEXT,
  license_status TEXT,
  years_licensed INTEGER,
  incidents_5yr  INTEGER DEFAULT 0
);

CREATE TABLE vehicles (
  vehicle_id           TEXT PRIMARY KEY,
  cust_id              TEXT NOT NULL REFERENCES customers(cust_id),
  year                 INTEGER, make TEXT, model TEXT,
  vin                  TEXT,
  usage                TEXT,            -- COMMUTE | PLEASURE | BUSINESS_EXCLUDED
  annual_miles         INTEGER,
  financed             INTEGER NOT NULL DEFAULT 0,
  garaging_address_id  TEXT REFERENCES addresses(address_id)
);

CREATE TABLE dwellings (
  dwelling_id            TEXT PRIMARY KEY,
  cust_id                TEXT NOT NULL REFERENCES customers(cust_id),
  type                   TEXT,          -- home | condo | rental
  year_built             INTEGER,
  construction           TEXT,          -- FRAME | MASONRY | FIRE_RESIST
  roof_age               INTEGER,
  sq_ft                  INTEGER,
  replacement_cost_cents INTEGER,
  protection_class       INTEGER,
  dist_to_coast_mi       INTEGER,
  hoa_master_deductible_cents INTEGER
);

CREATE TABLE pets (
  pet_id  TEXT PRIMARY KEY,
  cust_id TEXT NOT NULL REFERENCES customers(cust_id),
  name    TEXT, species TEXT, breed TEXT, age INTEGER
);

CREATE TABLE bundles (
  bundle_id   TEXT PRIMARY KEY,
  cust_id     TEXT NOT NULL REFERENCES customers(cust_id),
  code        TEXT NOT NULL,            -- NEST | NEST_PLUS | FAMILY_TREE | ROOST
  discount_id TEXT REFERENCES discounts(discount_id),
  created_at  TEXT
);

CREATE TABLE policies (
  policy_id           TEXT PRIMARY KEY,
  cust_id             TEXT NOT NULL REFERENCES customers(cust_id),
  line                TEXT NOT NULL REFERENCES product_lines(line),
  tier_id             TEXT NOT NULL REFERENCES tiers(tier_id),
  status              TEXT NOT NULL,    -- QUOTE | ACTIVE | CANCELLED | LAPSED | PENDING
  effective_date      TEXT,
  expiration_date     TEXT,
  term_months         INTEGER,
  rating_as_of        TEXT,             -- as_of used to price (for reproducibility)
  base_premium_cents  INTEGER,
  final_premium_cents INTEGER,
  premium_breakdown   TEXT,             -- json (ordered breakdown)
  rating_inputs       TEXT,             -- json: non-derivable facts (billing, incidents, smoker) for reprice
  underlying_policy_id TEXT REFERENCES policies(policy_id),
  bundle_id           TEXT REFERENCES bundles(bundle_id),
  rep_id              TEXT REFERENCES reps(rep_id),
  created_at          TEXT
);

CREATE TABLE policy_coverages (
  policy_id                  TEXT NOT NULL REFERENCES policies(policy_id),
  coverage_id                TEXT NOT NULL REFERENCES coverages(coverage_id),
  value                      TEXT,
  premium_contribution_cents INTEGER,
  PRIMARY KEY (policy_id, coverage_id)
);

CREATE TABLE policy_objects (
  policy_id   TEXT NOT NULL REFERENCES policies(policy_id),
  object_type TEXT NOT NULL,            -- vehicle | dwelling | pet
  object_id   TEXT NOT NULL,
  PRIMARY KEY (policy_id, object_type, object_id)
);

CREATE TABLE suitability_records (
  suit_id           TEXT PRIMARY KEY,
  cust_id           TEXT NOT NULL REFERENCES customers(cust_id),
  line              TEXT NOT NULL REFERENCES product_lines(line),
  income_cents      INTEGER,
  dependents        INTEGER,
  existing_coverage_cents INTEGER,
  stated_need       TEXT,
  horizon           TEXT,               -- SHORT | MEDIUM | LONG
  risk_tolerance    TEXT,               -- LOW | MEDIUM | HIGH
  completed_at      TEXT,
  outcome           TEXT                -- SUITABLE | UNSUITABLE | NEEDS_REVIEW
);

CREATE TABLE loyalty_ledger (
  entry_id      TEXT PRIMARY KEY,
  cust_id       TEXT NOT NULL REFERENCES customers(cust_id),
  ts            TEXT,
  delta_points  INTEGER NOT NULL,       -- +earn / -redeem / -expire
  reason        TEXT,
  expires_on    TEXT,                   -- NULL = never (pre-2019 no-expiry bug)
  ref_policy_id TEXT REFERENCES policies(policy_id)
);

CREATE TABLE payments (
  payment_id  TEXT PRIMARY KEY,
  cust_id     TEXT NOT NULL REFERENCES customers(cust_id),
  policy_id   TEXT NOT NULL REFERENCES policies(policy_id),
  due         TEXT,
  paid_on     TEXT,
  amount_cents INTEGER,
  status      TEXT                      -- PAID | LATE | MISSED | SCHEDULED
);

CREATE TABLE claims (
  claim_id     TEXT PRIMARY KEY,
  policy_id    TEXT NOT NULL REFERENCES policies(policy_id),
  reported_at  TEXT,
  loss_date    TEXT,
  type         TEXT,
  status       TEXT,                    -- FNOL | OPEN | CLOSED
  reserve_cents INTEGER,
  fraud_score  REAL
);
