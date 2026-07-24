# Quickstart: Validate the Classification & Policy Enforcement Engine

Proves the milestone works end-to-end: classify a domain schema, review a
low-confidence column, publish a policy, and demonstrate deterministic
enforcement overriding an incorrect/malicious query — mirroring the 10
scenarios in `spec.md`.

## Prerequisites

- Docker Compose stack running: 2× Postgres (healthcare, fintech), backend,
  frontend (see `tech-stack.md` → Infrastructure & local development).
- Synthetic data already seeded for both domains (`domains/healthcare/seed.py`,
  `domains/fintech/seed.py`).
- `X-Steward-Role` header available to set on requests (`analyst` or
  `admin`) — no real auth system required at Milestone 1.

## Setup

```bash
docker compose up -d
# Wait for both Postgres instances + backend to report healthy.
```

## Scenario walkthrough

### 1. Enumerate + classify a domain schema (Scenarios 1–3, 6)

```bash
curl -X POST localhost:8000/domains/healthcare/schema/enumerate
curl -X POST localhost:8000/domains/healthcare/classify
```

**Expect**: `patient_ssn` classified `pii_direct`, confidence ≥ 0.9, not in
the review queue (Scenario 1). `patient_notes` is NOT auto-classified
`business` (Scenario 3) — check via the review queue or policy output.

### 2. Inspect the human-review queue (Scenario 2)

```bash
curl -H "X-Steward-Role: admin" localhost:8000/domains/fintech/review-queue
```

**Expect**: the fintech `notes` column present with `status: pending_review`
and `confidence < 0.85`.

### 3. Approve as admin, confirm role gate (Scenario 8)

```bash
# Rejected: analyst cannot approve
curl -X POST -H "X-Steward-Role: analyst" \
  localhost:8000/domains/fintech/review-queue/<column_id>/approve
# expect 403

# Accepted: admin can approve
curl -X POST -H "X-Steward-Role: admin" \
  localhost:8000/domains/fintech/review-queue/<column_id>/approve
# expect 200, reviewed_by set
```

### 4. Publish the policy artifact (FR-006)

```bash
curl -X POST -H "X-Steward-Role: admin" \
  localhost:8000/domains/healthcare/policy/publish
```

**Expect**: a new versioned `policies/healthcare/<n>/policy.yaml` matching
`contracts/policy-artifact.schema.yaml`'s shape, manifest updated.

### 5. Deterministic guardrail overrides a bad query (Scenario 4)

```bash
curl -X POST -H "X-Steward-Role: analyst" \
  -d '{"sql": "SELECT member_ssn FROM claims"}' \
  localhost:8000/fintech/query
```

**Expect**: `403`, `reason: "column blocked by policy: member_ssn"` — reject
happens regardless of any LLM self-report (Constitution Principle I).

### 6. Row-level predicate injection (Scenario 5)

```bash
curl -X POST -H "X-Steward-Role: analyst" \
  -d '{"question": "show me all claims"}' \
  localhost:8000/domains/fintech/query
```

**Expect**: executed query includes an injected `tenant_id = :current_tenant`
predicate even though the natural-language question never mentioned tenant
scoping; results never cross tenant boundaries.

### 7. Unclassified schema defaults closed (Scenario 6)

```bash
curl -X POST -H "X-Steward-Role: analyst" \
  -d '{"sql": "SELECT * FROM new_unclassified_table"}' \
  localhost:8000/domains/healthcare/query
```

**Expect**: `403`, `reason: "schema not yet classified"`.

### 8. Role-gated column (Scenario 7)

```bash
# Rejected: analyst lacks the gated role
curl -X POST -H "X-Steward-Role: analyst" \
  -d '{"sql": "SELECT diagnosis_code FROM patients"}' \
  localhost:8000/domains/healthcare/query
# expect 403, reason: "column requires role: admin"

# Succeeds: admin has the gated role
curl -X POST -H "X-Steward-Role: admin" \
  -d '{"sql": "SELECT diagnosis_code FROM patients"}' \
  localhost:8000/domains/healthcare/query
# expect 200
```

### 9. DML statement rejected unconditionally (Scenario 9)

```bash
curl -X POST -H "X-Steward-Role: analyst" \
  -d '{"sql": "DELETE FROM transactions WHERE id = 1"}' \
  localhost:8000/domains/fintech/query
```

**Expect**: `403`, `reason: "DML statement rejected: read-only queries only"`
— rejected purely on the parsed statement's AST type, before any column/table
policy lookup runs (Constitution Principle I).

### 10. Irrelevant question does not leak schema (Scenario 10)

```bash
curl -X POST -H "X-Steward-Role: analyst" \
  -d '{"question": "what is the weather today?"}' \
  localhost:8000/domains/healthcare/query
```

**Expect**: `200`, `reason: "question not mapped to schema"` — no SQL is
generated or executed, and no policy-blocked table/column names appear in
the response.

### 11. Query the audit log (NFR-004)

```bash
curl -H "X-Steward-Role: admin" \
  "localhost:8000/audit-log?domain=fintech&decision=block"
```

**Expect**: entries for every block/allow/classify decision produced by the
steps above, filterable by domain, time range, and decision type without any
log-scraping.

## Automated validation (required before this milestone is done)

```bash
# Behavioral scenarios — executes spec.md's 10 Given/When/Then scenarios directly
pytest tests/integration --bdd

# Classifier precision/recall against hand-labeled ground truth (both domains)
python backend/eval/classifier_eval.py --domain healthcare
python backend/eval/classifier_eval.py --domain fintech
```

**Expect**: all 10 scenarios pass; precision/recall on `pii_direct` ≥ 0.85
each, per domain (spec Success Criteria).
