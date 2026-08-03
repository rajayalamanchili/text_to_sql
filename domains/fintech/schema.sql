-- Fintech domain schema (T013, research.md §10, tech-stack.md "Fintech
-- synthetic data").
--
-- Hand-designed (customers/accounts/transactions/claims) and populated by
-- seed.py using Faker plus a PaySim-style transaction pattern generator
-- (research.md §10) — no real account or transaction data ever originates
-- here (FR-012, Constitution Principle VII).
--
-- Column names are deliberately domain-config content, not engine code
-- (Constitution Principle IV): the classification/enforcement engine never
-- hardcodes "member_ssn" or "tenant_id" — it discovers them via schema
-- enumeration (FR-001) like any other column.

CREATE TABLE IF NOT EXISTS customers (
    customer_id BIGSERIAL PRIMARY KEY,
    -- One customer belongs to exactly one tenant; claims inherit it
    -- (Scenario 5's row-level tenant scoping).
    tenant_id TEXT NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    address TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    zip TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers (customer_id),
    account_type TEXT NOT NULL,
    balance NUMERIC(14, 2) NOT NULL,
    opened_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES accounts (account_id),
    -- PaySim-style fields (research.md §10): transaction_type/amount/
    -- balance_before/balance_after/is_fraud mirror PaySim's
    -- type/amount/oldbalanceOrg/newbalanceOrig/isFraud columns.
    transaction_type TEXT NOT NULL,
    amount NUMERIC(14, 2) NOT NULL,
    balance_before NUMERIC(14, 2) NOT NULL,
    balance_after NUMERIC(14, 2) NOT NULL,
    is_fraud BOOLEAN NOT NULL DEFAULT false,
    transaction_date TIMESTAMPTZ NOT NULL,
    -- Ambiguous column (Scenario 2): free text drawn from a small, repeated
    -- set of memo patterns — low cardinality of distinct patterns, unlike
    -- healthcare's high-entropy `patient_notes` — driving heuristic
    -- confidence below the 0.85 auto-approval threshold (FR-005).
    notes TEXT
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers (customer_id),
    -- Row-level policy governed column (Scenario 5): injected as
    -- `tenant_id = :current_tenant` once published.
    tenant_id TEXT NOT NULL,
    -- Direct-identifier column (Scenario 4): blocked once classified.
    member_ssn TEXT NOT NULL,
    claim_amount NUMERIC(14, 2) NOT NULL,
    claim_date DATE NOT NULL,
    claim_status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_accounts_customer_id ON accounts (customer_id);
CREATE INDEX IF NOT EXISTS idx_transactions_account_id ON transactions (account_id);
CREATE INDEX IF NOT EXISTS idx_claims_customer_id ON claims (customer_id);
CREATE INDEX IF NOT EXISTS idx_claims_tenant_id ON claims (tenant_id);
