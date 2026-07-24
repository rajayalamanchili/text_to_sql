# API Contract: Schema Classification & Policy Enforcement Engine

FastAPI auto-generates the real OpenAPI spec from these routes; this
document is the human-reviewable contract they must satisfy, and the source
`tasks.md` will implement against. All endpoints are scoped under
`/domains/{domain}` unless noted, where `{domain}` is one of the
Milestone-1-configured domains (FR-011). All endpoints require the
`X-Steward-Role: analyst|admin` header (research.md §7); endpoints marked
**admin-only** reject any other role with `403`.

## Auth header (all endpoints)

| Header | Values | Behavior if missing/invalid |
|---|---|---|
| `X-Steward-Role` | `analyst`, `admin` | Defaults to `analyst` (fail closed) |

## Schema enumeration & classification pipeline

### `POST /domains/{domain}/schema/enumerate`
Enumerates all tables/columns from the domain's configured DB connection
(FR-001). Does not call any LLM. Returns the raw schema metadata (types,
cardinality ratios) with no row-level data included.

**Response 200**: `{ tables: [{ table_name, columns: [{column_name, data_type, cardinality_ratio}] }] }`

### `POST /domains/{domain}/classify`
Runs the classification graph (research.md §9) over the most recently
enumerated schema: heuristic pass, then conditional LLM-assisted pass
(FR-002, FR-003). Idempotent per schema snapshot — re-running re-classifies
all columns from scratch rather than incrementally patching.

**Response 202**: `{ run_id, columns_classified, auto_approved_count, pending_review_count }`

**Constraints**: MUST complete within 5 minutes for a 50-table schema
(NFR-001).

## Human review queue (FR-013)

### `GET /domains/{domain}/review-queue`
Lists all `ColumnClassification` records with `status == "pending_review"`,
including `heuristic_score`, `llm_score`, `confidence`, and `llm_rationale`
as source signals for the reviewer.

**Response 200**: `{ items: [ColumnClassification] }`

### `POST /domains/{domain}/review-queue/{column_id}/approve` — **admin-only**
Transitions the record to `approved`, sets `reviewed_by`/`reviewed_at`,
writes an `AuditLogEntry` (Scenario 8). Non-admin callers get `403` and the
record is unchanged.

**Response 200**: updated `ColumnClassification`
**Response 403**: `{ error: "admin role required" }`

### `POST /domains/{domain}/review-queue/{column_id}/reject` — **admin-only**
Transitions the record to `rejected`. Same auth/audit rules as approve.

### `POST /domains/{domain}/review-queue/{column_id}/reclassify` — **admin-only**
Body: `{ classification: <enum> }`. Overwrites the classification, sets
`source = "human"`, transitions to `approved`. Same auth/audit rules.

## Policy artifact

### `GET /domains/{domain}/policy`
Returns the currently active `PolicyArtifact` for the domain (resolved via
`policies/<domain>/manifest.yaml`, research.md §6).

**Response 200**: `PolicyArtifact` (see data-model.md), or `404` if the
domain has never had a policy published — callers MUST treat `404` as
"nothing is allowed" (FR-009), not as an error to retry past.

### `POST /domains/{domain}/policy/publish` — **admin-only**
Publishes a new `PolicyArtifact` version built from all currently `approved`
`ColumnClassification` records for the domain. Increments `version`, updates
the manifest, writes an `AuditLogEntry`.

**Response 201**: `PolicyArtifact`

## Query execution (enforcement demonstration)

### `POST /domains/{domain}/query`
Body: `{ question: str }` or `{ sql: str }` (Milestone 1 does not require
production-quality NL→SQL generation — a minimal generation step exists only
to exercise the enforcement node end-to-end, per spec "Out of Scope").
Runs the query graph (research.md §9): generate (if `question` given) →
deterministic enforce → execute only if enforcement passes.

**Response 200** (allowed): `{ query_id, rows: [...], policy_version_used }`

**Response 403** (blocked): `{ query_id, reason: "column blocked by policy: member_ssn", policy_version_used }`
(Scenario 4) — rejection MUST NOT depend on any LLM self-report about the
query (Constitution Principle I).

**Response 403** (DML rejected): `{ query_id, reason: "DML statement rejected: read-only queries only", policy_version_used }`
(FR-014, Scenario 9) — any non-`SELECT` root statement is rejected before
any column/table policy lookup, based purely on the parsed AST's statement
type.

**Response 200** (irrelevant question): `{ query_id, reason: "question not mapped to schema" }`
(FR-014, Scenario 10) — returned when no table/column in the question maps
to the domain's schema; no SQL is generated or executed, and no
policy-blocked table/column names are revealed.

**Constraints**: Enforcement check itself (excluding any LLM generation
step) MUST add ≤200ms latency (NFR-002).

## Audit log

### `GET /audit-log?domain=&from=&to=&decision=`
Filters `AuditLogEntry` records by domain, time range, and decision type
(NFR-004) — no separate log-scraping tool required. `domain` is optional
(omit to query across all domains); `from`/`to` are ISO-8601 timestamps;
`decision` matches the `AuditLogEntry.decision` enum.

**Response 200**: `{ items: [AuditLogEntry] }`
