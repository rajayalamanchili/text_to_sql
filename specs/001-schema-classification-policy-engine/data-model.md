# Data Model: Schema Classification & Policy Enforcement Engine

Entities below extend the spec's "Key Entities" section with concrete
fields, types, relationships, validation rules, and state transitions needed
for implementation. All entities are Pydantic v2 models in
`backend/src/models/`.

## ColumnClassification

Represents the classification state of a single column at a point in time.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `domain` | enum (`healthcare`, `fintech`, extensible) | Which domain schema this belongs to |
| `table_name` | str | |
| `column_name` | str | |
| `data_type` | str | As reported by schema enumeration (FR-001) |
| `cardinality_ratio` | float (0–1) | `distinct_count / row_count`, from enumeration, never raw values |
| `classification` | enum: `pii_direct`, `pii_indirect`, `sensitive_category`, `business`, `unclassified` | Exactly one, per FR-004 |
| `heuristic_score` | float (0–1) \| null | Output of heuristic pass (FR-002) |
| `llm_score` | float (0–1) \| null | Output of LLM-assisted pass, if triggered (FR-003) |
| `confidence` | float (0–1) | Combined confidence per research.md §4 |
| `source` | enum: `heuristic`, `llm`, `human` | Which pass produced the *current* classification value |
| `status` | enum: `auto_approved`, `pending_review`, `approved`, `rejected` | See State Transitions below |
| `reviewed_by` | str \| null | Admin user identity, set only when `status` leaves `pending_review` via human action |
| `reviewed_at` | datetime \| null | |
| `llm_rationale` | str \| null | Stored for audit only; never used as an enforcement input (Principle I) |

**Validation rules**:
- `confidence < 0.85` ⇒ `status` MUST be `pending_review` and MUST NOT be
  `auto_approved` (FR-005).
- `status == "approved"` MUST have non-null `reviewed_by`/`reviewed_at`, and
  `reviewed_by` must resolve to a `Caller` with role `admin` (FR-013,
  Scenario 8).
- A column with `status` in `{pending_review, rejected}` or with no record
  at all has **no active enforceable policy** — enforcement treats it as
  blocked (FR-005, FR-009).

**State transitions**:

```text
(no record) --enumerate--> unclassified
unclassified --heuristic pass--> auto_approved (confidence >= 0.85)
                              \-> pending_review (confidence < 0.85)
pending_review --llm pass (if not already run)--> auto_approved | pending_review (re-scored)
pending_review --admin approve--> approved (reviewed_by, reviewed_at set)
pending_review --admin reject--> rejected
pending_review --admin reclassify--> approved (classification overwritten, source=human)
```

Only a `Caller` with role `admin` may transition `pending_review` →
`approved`/`rejected` (FR-013, Scenario 8); an `analyst`-role attempt MUST be
rejected and the record MUST remain `pending_review`.

## PolicyArtifact

The versioned, deterministic-enforcement source of truth for one domain.

| Field | Type | Notes |
|---|---|---|
| `domain` | str | |
| `version` | int | Monotonically increasing per domain |
| `tables` | list[PolicyTable] | See below |
| `approved_by` | str | Admin identity who published this version |
| `approved_at` | datetime | |

### PolicyTable (nested)

| Field | Type | Notes |
|---|---|---|
| `table_name` | str | |
| `columns` | dict[str, PolicyColumn] | Keyed by column name |
| `row_policy_template` | str \| null | e.g. `"tenant_id = :current_tenant"`; null if no row-level policy applies |

### PolicyColumn (nested)

| Field | Type | Notes |
|---|---|---|
| `action` | enum: `allow`, `block`, `role_gate` | FR-008 |
| `roles` | list[enum: `analyst`, `admin`] | Required and non-empty iff `action == "role_gate"` |
| `on_role_mismatch` | enum: `reject`, `exclude` | Only meaningful when `action == "role_gate"`; defaults to `reject` (FR-008, Scenario 7) |
| `classification` | same enum as `ColumnClassification.classification` | Carried through for audit/debugging traceability |

**Validation rules**:
- Only columns with `ColumnClassification.status == "approved"` (or
  `auto_approved`) may appear in a published `PolicyArtifact` (FR-006,
  Constitution Principle III).
- A table/column absent from the active artifact is implicitly `block`
  (FR-009) — absence is meaningful, not an oversight.
- Persisted as YAML at `policies/<domain>/<version>/policy.yaml`; the active
  version for a domain is resolved via `policies/<domain>/manifest.yaml`
  (research.md §6).

## AuditLogEntry

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | |
| `timestamp` | datetime | |
| `domain` | str | |
| `query_id` | UUID | Correlates enforcement decisions to a single query attempt |
| `actor_role` | enum: `analyst`, `admin` | From the auth stub at request time |
| `decision` | enum: `allow`, `block`, `mask`, `classify_auto_approved`, `classify_pending_review`, `classify_approved`, `classify_rejected` | Both enforcement and classification decisions are logged (Principle VIII) |
| `reason` | str | Human-readable, e.g. `"column blocked by policy: member_ssn"` (Scenario 4) |
| `policy_version_used` | int \| null | Null only for classification-stage entries where no policy exists yet |
| `raw_query_hash` | str \| null | SHA-256 of the executed/rejected SQL text; never the raw PII values themselves |

**Validation rules**:
- Every enforcement decision (allow/block/mask) MUST produce exactly one
  `AuditLogEntry` (FR-010).
- Every classification status transition MUST produce exactly one
  `AuditLogEntry`, including admin approve/reject/reclassify actions, with
  `actor_role` recording the acting admin (Scenario 8).
- Queryable by `domain`, time range (`timestamp`), and `decision` without
  log-scraping (NFR-004) — enforced by the `GET /audit-log` endpoint's
  supported filters (see contracts/).

## Caller (auth stub)

| Field | Type | Notes |
|---|---|---|
| `role` | enum: `analyst`, `admin` | Parsed from `X-Steward-Role` header; defaults to `analyst` if missing/invalid (research.md §7) |

Not persisted — constructed per-request by a FastAPI dependency. Full
identity/auth integration is out of scope for Milestone 1 (spec "Out of
Scope").

## Domain

Not a database entity — a config-time concept identifying which
`policies/<domain>/` and `domains/<domain>/` directory pair is active for a
request. Enforced to be one of the two Milestone-1-configured values
(`healthcare`, `fintech`) at the API boundary; adding a third domain (FR-011)
requires only a new config+policy directory pair, no engine code change.

## Relationships

```text
Domain 1---* ColumnClassification
Domain 1---* PolicyArtifact (versions)
PolicyArtifact 1---* PolicyTable 1---* PolicyColumn
ColumnClassification *---1 PolicyColumn   (an approved classification becomes a policy column entry)
Domain 1---* AuditLogEntry
PolicyArtifact 1---* AuditLogEntry        (via policy_version_used)
Caller 1---* AuditLogEntry                (via actor_role)
```
