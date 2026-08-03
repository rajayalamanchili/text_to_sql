-- Column classification results table (data-model.md#ColumnClassification,
-- FR-002-FR-005). Applied identically to every domain's Postgres instance
-- (same per-domain storage pattern as audit_log, tech-stack.md) — this
-- file has no domain-specific content, per Constitution Principle IV.
--
-- Re-classifying a column (POST /domains/{domain}/classify) upserts its
-- row here rather than appending a new one — one row per (domain,
-- table_name, column_name), always reflecting the most recent
-- classification run (contracts/api.md: "re-running re-classifies all
-- columns from scratch"). A fresh run also clears any prior human-review
-- state (reviewed_by/reviewed_at), since a newly computed classification
-- supersedes whatever an admin previously approved/rejected for the old
-- value (src/services/classification/persistence.py).

CREATE TABLE IF NOT EXISTS column_classifications (
    id UUID PRIMARY KEY,
    domain TEXT NOT NULL,
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    cardinality_ratio DOUBLE PRECISION NOT NULL
        CHECK (cardinality_ratio >= 0 AND cardinality_ratio <= 1),
    classification TEXT NOT NULL
        CHECK (classification IN (
            'pii_direct', 'pii_indirect', 'sensitive_category', 'business', 'unclassified'
        )),
    heuristic_score DOUBLE PRECISION,
    llm_score DOUBLE PRECISION,
    confidence DOUBLE PRECISION NOT NULL
        CHECK (confidence >= 0 AND confidence <= 1),
    source TEXT NOT NULL
        CHECK (source IN ('heuristic', 'llm', 'human')),
    status TEXT NOT NULL
        CHECK (status IN ('auto_approved', 'pending_review', 'approved', 'rejected')),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    llm_rationale TEXT,

    CONSTRAINT column_classifications_unique_column
        UNIQUE (domain, table_name, column_name)
);

CREATE INDEX IF NOT EXISTS idx_column_classifications_domain
    ON column_classifications (domain);
CREATE INDEX IF NOT EXISTS idx_column_classifications_status
    ON column_classifications (domain, status);
