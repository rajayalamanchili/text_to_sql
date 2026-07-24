# Feature Spec: Schema Sensitivity Classification & Policy Enforcement Engine

**Project**: Steward
**Feature branch**: `001-schema-classification-policy-engine`
**Status**: Clarified — ready for `/speckit.plan`
**Milestone**: 1 of 4 (Classification & Policy Engine → RAG Retrieval → Bounded
Agentic Loop → MCP Exposure)
**Depends on**: `constitution.md` v1.0.0

## Overview

Build the foundational layer of Steward, a domain-agnostic, governed
natural-language data access platform: a pipeline that, given an
arbitrary relational schema, (1)
classifies each column's sensitivity, (2) routes low-confidence
classifications to human review, (3) stores the resulting classification
as a versioned policy artifact, and (4) enforces that policy
deterministically at query-execution time — regardless of what an LLM
proposes.

This feature does **not** include SQL generation quality, RAG-based schema
retrieval, or agentic retry loops. Those are later milestones and are
explicitly out of scope here (see "Out of Scope").

## User Scenarios & Testing

### Scenario 1: Obvious PII column is classified correctly
**Given** a healthcare schema containing a column `patient_ssn` (string,
near-100% unique values)
**When** the classification pipeline runs
**Then** the column is classified `pii_direct` with confidence ≥ 0.9
**And** the resulting policy sets `action: block` for that column
**And** no human review is triggered.

### Scenario 2: Ambiguous column is flagged for human review
**Given** a fintech schema containing a column `notes` (free text,
low cardinality of distinct patterns)
**When** the classification pipeline runs
**Then** the column receives a classification with confidence < 0.85
**And** the column is added to the human-review queue
**And** a reviewer sees it in the review UI with status `pending_review`
**And** the column's policy status is `pending_review`, not `allowed`,
until a reviewer with the `admin` role approves it in the UI.

### Scenario 3: Adversarially-named column is not misclassified as safe
**Given** a healthcare schema containing a column `patient_notes` that
contains free-text clinical narrative (a common real-world PHI leakage
pattern)
**When** the classification pipeline runs
**Then** the column is NOT auto-classified as `business` with high
confidence
**And** it is either classified `sensitive_category` or routed to human
review — never silently allowed.

### Scenario 4: Deterministic guardrail overrides an incorrect LLM proposal
**Given** an approved policy blocking the `member_ssn` column
**And** an LLM-generated SQL query that references `member_ssn` despite
the block (e.g., due to prompt injection or model error)
**When** the query reaches the policy enforcement node
**Then** the query is rejected before execution
**And** the rejection is logged with the reason "column blocked by policy:
member_ssn"
**And** the rejection does NOT depend on the LLM having correctly
self-reported anything about the query.

### Scenario 5: Row-level policy is applied regardless of LLM-generated predicates
**Given** a fintech schema with a row-policy of `tenant_id = :current_tenant`
**And** a user-generated question that does not mention tenant scoping
**When** SQL is generated and reaches the enforcement node
**Then** the tenant predicate is injected deterministically into the
executed query
**And** the query cannot return rows outside the caller's tenant, even if
the LLM's generated SQL omitted or contradicted that scoping.

### Scenario 6: Unclassified column defaults to blocked, not allowed
**Given** a newly onboarded schema that has not yet completed
classification
**When** any query references a column from that schema
**Then** the query is rejected with reason "schema not yet classified"
**And** no data from that schema is returned under any circumstance.

### Scenario 7: Role-gated column is visible only to the correct role
**Given** a column `diagnosis_code` with policy `action: role_gate,
roles: [admin]`
**When** a user with role `analyst` asks a
question that would surface this column
**Then** the query is rejected (or the column is silently excluded from
results, per FR-008 configuration) with reason "column requires role:
admin"
**And** the same query succeeds for a user with role `admin`.

### Scenario 8: Only an admin can approve a pending classification
**Given** a column in `pending_review` status in the review UI
**When** a user with role `analyst` attempts to approve it
**Then** the approval is rejected
**And** the column remains `pending_review`
**And** only a user with role `admin` can transition it to `approved`,
which is recorded in the audit log with the reviewer's identity.

### Scenario 9: LLM-proposed DML statement is rejected unconditionally
**Given** an approved policy for the fintech domain that would otherwise
allow read access to the `transactions` table
**And** a query request whose generated SQL is
`DELETE FROM transactions WHERE id = 1` (a DML statement, not a `SELECT`)
**When** the query reaches the policy enforcement node
**Then** the query is rejected before execution, regardless of what any
column- or table-level policy would otherwise allow
**And** the rejection is logged with the reason "DML statement rejected:
read-only queries only"
**And** the rejection does NOT depend on the LLM having self-reported that
its own query is DML (this is the exact failure mode Constitution
Principle I exists to prevent).

### Scenario 10: Irrelevant question does not leak schema or bypass enforcement
**Given** a healthcare domain with an approved policy
**And** a user question unrelated to any table in the schema (e.g., "what
is the weather today?")
**When** the question reaches the query graph
**Then** no SQL is executed against the domain database
**And** the response indicates the question could not be mapped to the
schema, without revealing table/column names that a policy would otherwise
block
**And** no policy bypass or data return occurs under any circumstance.

## Functional Requirements

- **FR-001**: The system MUST accept a database connection and enumerate
  all tables and columns, including data types and (where available)
  sample value distributions, without exposing raw row-level data to any
  LLM call during this enumeration step.
- **FR-002**: The system MUST run a heuristic classification pass using
  column name patterns, data type, and cardinality signals, producing a
  preliminary classification and confidence score per column.
- **FR-003**: The system MUST run an LLM-assisted classification pass for
  columns where the heuristic pass confidence is below a configured
  threshold, using masked/aggregated value patterns — never raw
  identifiable values — as input to the LLM.
- **FR-004**: The system MUST assign each column exactly one of the
  following classifications: `pii_direct`, `pii_indirect`,
  `sensitive_category`, `business`, or `unclassified`.
- **FR-005**: Any column with combined classification confidence below
  0.85 (configurable) MUST be placed in a human-review queue and MUST NOT
  have an active enforceable policy until reviewed and approved. 0.85 is
  intentionally conservative: this milestone favors more manual review
  over risking an under-confident auto-approval.
- **FR-006**: The system MUST persist an approved classification set as a
  versioned policy artifact (see Key Entities) per domain.
- **FR-007**: The system MUST provide a policy enforcement component that
  loads the active policy artifact for a domain and deterministically
  evaluates every generated SQL query against it before execution —
  independent of any LLM-reported metadata about that query.
- **FR-008**: The policy enforcement component MUST support at minimum
  these actions per column: `allow`, `block`, `role_gate` (visible only to
  specified roles), and per table: row-level predicate injection. For
  Milestone 1, the supported role set is fixed to two roles: `analyst`
  (standard query access, subject to role_gate restrictions) and `admin`
  (full query access, plus review-queue approval authority per FR-013).
  A user's role is supplied via a simple auth stub (e.g., a request
  header or config value) — full identity/auth integration is out of
  scope for this milestone. When a caller's role does not satisfy a
  column's `role_gate`, the enforcement component's behavior is controlled
  by a per-policy-column setting, `on_role_mismatch: reject | exclude`,
  defaulting to `reject` (the whole query is rejected, consistent with
  FR-009's fail-closed default) — `exclude` (silently omit the gated
  column, allowing the rest of the query to proceed) is an optional,
  explicitly configured alternative, never the default (Scenario 7).
- **FR-009**: The system MUST reject any query referencing a table or
  column that has no active approved policy, defaulting closed.
- **FR-010**: The system MUST log every classification decision and every
  enforcement decision (allow/block/mask, and why) in a queryable audit
  log.
- **FR-011**: The system MUST support at least two independently
  configured domains (healthcare, fintech) running against the same
  engine codebase with zero domain-specific code paths.
- **FR-012**: The system MUST NOT use real PII, PHI, or real financial
  account data at any stage; all test/demo data MUST be synthetic.
- **FR-013**: The system MUST provide a web UI for the human-review
  queue, allowing an `admin`-role user to view pending classifications
  (column, proposed classification, confidence, source signals) and
  approve, reject, or manually reclassify each one. Only `admin`-role
  users may approve a pending classification; the UI MUST enforce this
  and record the approving user's identity in the audit log.
- **FR-014**: The policy enforcement component MUST reject any generated
  statement that is not a read-only `SELECT` (e.g., `INSERT`, `UPDATE`,
  `DELETE`, `DROP`, `ALTER`, `TRUNCATE`) unconditionally, before any
  column- or table-level policy is evaluated — independent of any
  LLM-reported metadata about the statement's nature (Scenario 9). A
  question that cannot be mapped to any table in the domain's active
  policy MUST NOT execute any SQL and MUST NOT reveal schema details that
  a policy would otherwise block (Scenario 10).

## Non-Functional Requirements / Constraints

- **NFR-001**: Classification of a schema of up to 50 tables MUST complete
  in under 5 minutes end-to-end (heuristic + LLM-assisted passes).
- **NFR-002**: Policy enforcement checks on a single query MUST add no
  more than 200ms of latency (deterministic checks only — no LLM calls
  permitted in the enforcement path itself, per Constitution Principle I).
- **NFR-003**: All policy artifacts MUST be version-controlled and
  diffable (plain YAML or JSON, not a binary format).
- **NFR-004**: The audit log MUST be queryable by domain, time range, and
  decision type (allow/block/mask) without requiring log-scraping.

## Key Entities

- **Column Classification**: `{table, column, classification, confidence,
  source (heuristic|llm|human), reviewed_by, reviewed_at}`
- **Policy Artifact**: `{domain, version, tables: [{table_name, columns:
  {...}, row_policy_template}], approved_by, approved_at}`
- **Audit Log Entry**: `{timestamp, domain, query_id, decision, reason,
  policy_version_used}`

Two supporting, non-persisted concepts are also defined in `data-model.md`
but are intentionally not listed above since they aren't stored business
entities: **Caller** (the per-request role, from FR-008's auth stub) and
**Domain** (the config-time healthcare/fintech selector, from FR-011).

## Out of Scope (explicitly deferred to later milestones)

- RAG-based schema/table retrieval for large schemas (Milestone 2).
- Agentic self-correction / retry loops on SQL generation errors
  (Milestone 3).
- MCP server exposure of the query engine (Milestone 4).
- SQL generation quality/accuracy improvements beyond what is needed to
  demonstrate enforcement (tracked separately, not blocking this
  milestone).
- TypeScript frontend implementation for the *end-user query interface*
  (tracked as a parallel, independent feature spec — not a dependency of
  this milestone's completion). Note: the human-review queue UI (FR-013)
  IS in scope for this milestone, since it is required for the
  classification pipeline to be functionally complete — this is a
  separate, minimal internal admin UI, not the end-user-facing product
  frontend.
- Full identity/auth integration (SSO, real user management). Milestone 1
  uses a role stub (a request header or config value asserting the
  caller's role) — sufficient to prove the enforcement logic, not
  production authentication.

## Success Criteria

- Classifier precision and recall, measured against hand-labeled ground
  truth (20–30 columns per domain), meet or exceed a target agreed upon
  in `plan.md` (suggested starting bar: precision ≥ 0.85, recall ≥ 0.85
  on `pii_direct` classifications specifically, since false negatives
  there are the highest-consequence error).
- All ten behavioral scenarios above pass as automated tests.
- The same engine codebase runs both the healthcare and fintech domain
  configurations with no domain-specific conditionals in engine source
  files.
- No milestone-2+ capability (RAG, agentic loop, MCP) has been started
  before this criteria list is met.

## Clarifications

### Session 2026-07-23

- **Q: What confidence threshold should route a column to human review
  instead of auto-approving its classification?**
  **A**: 0.85 (conservative). Rationale: this milestone prioritizes
  avoiding false-negative auto-approvals (a sensitive column wrongly
  marked safe) over minimizing reviewer workload. Affects FR-005 and
  Scenario 2.

- **Q: How should role-based access (`role_gate`) work for Milestone 1?**
  **A**: A small fixed role set — `analyst` and `admin` — supplied via an
  auth stub (request header or config value), not a full identity
  system. `admin` additionally holds review-queue approval authority.
  Affects FR-008, FR-013, and Scenarios 7–8. Full identity/auth
  integration is explicitly out of scope for this milestone.

- **Q: How should the human-review queue for low-confidence columns be
  handled in Milestone 1?**
  **A**: A simple web UI, not a file/PR-based flow. `admin`-role users
  view pending classifications with their source signals and approve,
  reject, or manually reclassify. This became FR-013 and is explicitly
  called out in "Out of Scope" as distinct from the end-user query
  frontend (which remains a separate, later feature spec).

**Impact of this session**: two new behavioral scenarios (7, 8) and one
new functional requirement (FR-013) were added. Success criteria updated
from six to eight required passing scenarios. This spec is now ready for
`/speckit.plan`.

## Amendments

### 2026-07-23 — `/speckit.analyze` remediation

- **Scenario 7** corrected: it had become self-contradictory (both the
  gated role and the successful caller's role were `analyst`). Now uses
  two distinct roles from FR-008's fixed `{analyst, admin}` set —
  `role_gate` on `roles: [admin]`, rejected for `analyst`, succeeds for
  `admin`.
- **Scenarios 9 and 10** added, plus **FR-014**: Constitution Principle VI
  requires eval coverage for "relevant, irrelevant, DML-attempt, and
  policy-boundary questions," and Principle I's rationale specifically
  names DML-blocking-via-LLM-self-report as the prior prototype's core
  flaw. Neither case had a corresponding scenario. Success Criteria updated
  from eight to ten required passing scenarios.

### 2026-07-23 — `/speckit.analyze` follow-up pass

- **FR-008** now explicitly defines the `on_role_mismatch: reject | exclude`
  configuration Scenario 7 referenced but that FR-008 never previously
  named; default is `reject` (fail closed, consistent with FR-009).
- **Key Entities** now cross-references `Caller` and `Domain` (defined in
  `data-model.md`) to clarify why they aren't listed as persisted entities.
- (Tracked in `plan.md`/`tasks.md`, not here): the orphaned `policy_loader.py`
  filename was removed from `plan.md`'s Project Structure, and a synthetic-data
  regression safeguard task (FR-012) was added to `tasks.md`.