-- Audit log table (data-model.md#AuditLogEntry, FR-010, NFR-004).
--
-- Applied identically to every domain's Postgres instance (tech-stack.md
-- "Audit log storage": same-instance pattern as domain data, no separate
-- audit database) — this file has no domain-specific content, per
-- Constitution Principle IV.

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    "timestamp" TIMESTAMPTZ NOT NULL DEFAULT now(),
    domain TEXT NOT NULL,
    query_id UUID NOT NULL,
    actor_role TEXT NOT NULL
        CHECK (actor_role IN ('analyst', 'admin')),
    decision TEXT NOT NULL
        CHECK (decision IN (
            'allow', 'block', 'mask',
            'classify_auto_approved', 'classify_pending_review',
            'classify_approved', 'classify_rejected', 'policy_published'
        )),
    reason_code TEXT
        CHECK (reason_code IN (
            'COLUMN_BLOCKED', 'NO_ACTIVE_POLICY', 'DML_REJECTED',
            'MULTIPLE_STATEMENTS_REJECTED', 'ROLE_GATE_MISMATCH',
            'SCHEMA_NOT_CLASSIFIED', 'QUESTION_NOT_MAPPED', 'ENFORCEMENT_ERROR'
        )),
    reason_message TEXT,
    policy_version_used INTEGER,
    raw_query_hash TEXT,

    -- reason_message is only ever the rendered template for reason_code
    -- (data-model.md#AuditLogEntry) — the two are set or null together.
    CONSTRAINT reason_code_message_paired
        CHECK ((reason_code IS NULL) = (reason_message IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_audit_log_domain ON audit_log (domain);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log ("timestamp");
CREATE INDEX IF NOT EXISTS idx_audit_log_decision ON audit_log (decision);
CREATE INDEX IF NOT EXISTS idx_audit_log_query_id ON audit_log (query_id);
