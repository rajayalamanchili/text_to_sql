-- Healthcare domain schema (T012, research.md §10, tech-stack.md "Healthcare
-- synthetic data").
--
-- Synthea-derived in structure (patients/encounters/conditions, per
-- research.md §10) and populated by the Python-native Synthea-style
-- generator in seed.py (tech-stack.md, amended 2026-07-29) — no real patient
-- data ever originates here (FR-012, Constitution Principle VII).
--
-- Column names are deliberately domain-config content, not engine code
-- (Constitution Principle IV): the classification/enforcement engine never
-- hardcodes "patient_ssn" or "diagnosis_code" — it discovers them via
-- schema enumeration (FR-001) like any other column.

CREATE TABLE IF NOT EXISTS patients (
    patient_id BIGSERIAL PRIMARY KEY,
    patient_ssn TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    birth_date DATE NOT NULL,
    gender TEXT NOT NULL,
    marital_status TEXT,
    address TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    zip TEXT NOT NULL,
    -- Sensitive-category signal column (Scenario 7): visible only under a
    -- role_gate policy once classified/published.
    diagnosis_code TEXT,
    -- Free-text clinical narrative: deliberately does not match any
    -- heuristic dictionary term (research.md §1), exercising the
    -- adversarial-column default (research.md §2, Scenario 3) — must never
    -- be auto-classified `business`.
    patient_notes TEXT
);

CREATE TABLE IF NOT EXISTS encounters (
    encounter_id BIGSERIAL PRIMARY KEY,
    patient_id BIGINT NOT NULL REFERENCES patients (patient_id),
    encounter_date TIMESTAMPTZ NOT NULL,
    encounter_class TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    reason_description TEXT
);

CREATE TABLE IF NOT EXISTS conditions (
    condition_id BIGSERIAL PRIMARY KEY,
    patient_id BIGINT NOT NULL REFERENCES patients (patient_id),
    encounter_id BIGINT NOT NULL REFERENCES encounters (encounter_id),
    condition_code TEXT NOT NULL,
    condition_description TEXT NOT NULL,
    onset_date DATE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_encounters_patient_id ON encounters (patient_id);
CREATE INDEX IF NOT EXISTS idx_conditions_patient_id ON conditions (patient_id);
CREATE INDEX IF NOT EXISTS idx_conditions_encounter_id ON conditions (encounter_id);
