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
**And** the rejection is logged with `reason_code: COLUMN_BLOCKED`
(message: "column blocked by policy: member_ssn")
**And** the rejection does NOT depend on the LLM having correctly
self-reported anything about the query.

### Scenario 5: Row-level policy is applied regardless of LLM-generated predicates
**Given** a fintech schema with a row-policy of `tenant_id = :current_tenant`
**And** the caller's request includes `X-Steward-Tenant: <tenant_id>`, which
resolves the `:current_tenant` placeholder (FR-008)
**And** a user-generated question that does not mention tenant scoping
**When** SQL is generated and reaches the enforcement node
**Then** the tenant predicate is injected deterministically into the
executed query — AND-merged at the AST level with whatever `WHERE`
clause the LLM's SQL already contained, never overwriting or stripping it
**And** the query cannot return rows outside the caller's tenant, even if
the LLM's generated SQL omitted or contradicted that scoping
**And** if `X-Steward-Tenant` is absent or malformed for a table whose
policy requires it, the query is rejected fail-closed with
`reason_code: ENFORCEMENT_ERROR`, consistent with FR-007.

### Scenario 6: Unclassified column defaults to blocked, not allowed
**Given** a newly onboarded schema that has not yet completed
classification
**When** any query references a column from that schema
**Then** the query is rejected with `reason_code: NO_ACTIVE_POLICY`
(message: "schema not yet classified")
**And** no data from that schema is returned under any circumstance.

### Scenario 7: Role-gated column is visible only to the correct role
**Given** a column `diagnosis_code` with policy `action: role_gate,
roles: [admin]`
**When** a user with role `analyst` asks a
question that would surface this column
**Then** the query is rejected (or the column is silently excluded from
results, per FR-008 configuration) with `reason_code: ROLE_GATE_MISMATCH`
(message: "column requires role: admin")
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
**And** the rejection is logged with `reason_code: DML_REJECTED`
(message: "DML statement rejected: read-only queries only")
**And** the rejection does NOT depend on the LLM having self-reported that
its own query is DML (this is the exact failure mode Constitution
Principle I exists to prevent).
**And** this rejection applies identically to a single-statement DML
query and to a stacked multi-statement input (e.g.,
`SELECT * FROM transactions; DROP TABLE transactions;`), the latter
logged with `reason_code: MULTIPLE_STATEMENTS_REJECTED` instead of
`DML_REJECTED`.

### Scenario 10: Irrelevant question does not leak schema or bypass enforcement
**Given** a healthcare domain with an approved policy
**And** a user question unrelated to any table in the schema (e.g., "what
is the weather today?")
**When** the question reaches the query graph
**Then** no SQL is executed against the domain database
**And** the response indicates `reason_code: QUESTION_NOT_MAPPED` (message:
"question not mapped to schema"), without revealing table/column names
that a policy would otherwise block
**And** no policy bypass or data return occurs under any circumstance.

### Scenario 11: Enforcement-path failure fails closed, never open
**Given** a domain whose active policy artifact has become unreadable
(e.g., the policy YAML is corrupted or the file is missing), OR the
enforcement component raises an unexpected internal error while
evaluating a query
**When** a query reaches the policy enforcement node
**Then** the query is rejected before execution
**And** the rejection is logged with reason `ENFORCEMENT_ERROR`
**And** no data is returned under any circumstance, even though no
column- or table-level policy was actually violated.

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
  independent of any LLM-reported metadata about that query. For
  Milestone 1, "the active policy artifact" for a domain is always the
  most recently published version — publishing always advances the
  domain's active-version pointer forward; there is no rollback-to-an-
  earlier-version action in this milestone. If the
  active policy artifact cannot be loaded, or the enforcement component
  encounters an unexpected internal error while evaluating a query, the
  query MUST be rejected (fail closed) and logged with reason
  `ENFORCEMENT_ERROR` — an enforcement-path failure MUST NOT be allowed
  to behave like an implicit pass, consistent with FR-009's
  default-closed behavior. When a single query trips more than one
  independent column/table-level policy violation, the reported reason
  is chosen by severity, not by AST scan order: `ENFORCEMENT_ERROR`
  (FR-007) and no-active-policy default-closed (FR-009) or an explicit
  `block` action (FR-008) rank highest — any of these alone rejects the
  whole query — followed by `role_gate` mismatch (FR-008), followed by
  row-policy predicate injection (Scenario 5), which does not itself
  cause rejection. The non-`SELECT`/DML check (FR-014) and the
  question-to-schema mapping check (Scenario 10) remain structurally
  prior to all of the above, per FR-014. The active policy version is
  resolved once, at the start of a query's enforcement evaluation, and
  that same version is used for every check in that evaluation (column
  lookup, role-gate, row-policy injection) and recorded as the audit
  log's `policy_version_used`; a policy publish that occurs while a
  query is mid-evaluation MUST NOT affect that in-flight query — the
  next query to arrive is the first to see the newly published version.
  Every rejection produced by this component or by FR-008/FR-009/FR-014
  (`COLUMN_BLOCKED`, `NO_ACTIVE_POLICY`, `DML_REJECTED`,
  `MULTIPLE_STATEMENTS_REJECTED`, `ROLE_GATE_MISMATCH`,
  `ENFORCEMENT_ERROR`) is surfaced to the API caller as HTTP `403
  Forbidden` with a JSON body of `{reason_code, reason_message,
  query_id}` — one consistent contract regardless of which reason
  applies. Scenario 10's `QUESTION_NOT_MAPPED` case is a distinct,
  non-rejection outcome (no policy was violated; the question simply
  didn't map to the schema) and instead returns HTTP `200` with the same
  `{reason_code, reason_message, query_id}` body shape. Deterministic
  column resolution (used by the no-active-policy check, the role_gate
  check, and row-policy predicate injection alike) MUST correctly resolve
  columns referenced through joins, CTEs, subqueries, and `SELECT *`
  expansion, not only a flat single-table `SELECT` — this is a tested
  guarantee, not best-effort, per Success Criteria.
- **FR-008**: The policy enforcement component MUST support at minimum
  these actions per column: `allow`, `block`, `role_gate` (visible only to
  specified roles), and per table: row-level predicate injection. For
  Milestone 1, the supported role set is fixed to two roles: `analyst`
  (standard query access, subject to role_gate restrictions) and `admin`
  (full query access, plus review-queue approval authority per FR-013).
  A user's role is supplied via a simple auth stub (e.g., a request
  header or config value) — full identity/auth integration is out of
  scope for this milestone. Any `X-Steward-Role` value outside the fixed
  `{analyst, admin}` enum — whether the header is missing entirely or
  present with an unrecognized value (e.g. `superuser`) — is treated
  identically: it defaults to `analyst`, the more restrictive role, per
  the same fail-closed rationale as FR-009. There is no separate
  "invalid role value" error path. When a caller's role does not satisfy a
  column's `role_gate`, the enforcement component's behavior is controlled
  by a per-policy-column setting, `on_role_mismatch: reject | exclude`,
  defaulting to `reject` (the whole query is rejected, consistent with
  FR-009's fail-closed default) — `exclude` (silently omit the gated
  column, allowing the rest of the query to proceed) is an optional,
  explicitly configured alternative, never the default (Scenario 7). For
  tables whose `row_policy_template` references `:current_tenant`
  (Scenario 5), the caller's tenant is supplied via a second auth-stub
  header, `X-Steward-Tenant`, parsed alongside `X-Steward-Role`. If a
  query touches such a table and `X-Steward-Tenant` is absent or
  malformed, the query MUST be rejected fail-closed with
  `reason_code: ENFORCEMENT_ERROR` (FR-007) — tenant-resolution failure is
  treated as an enforcement-path failure, not a distinct policy
  violation. `exclude` is defined only for a gated column referenced
  directly in the flat `SELECT` list; if a gated column with
  `on_role_mismatch: exclude` appears only inside an aggregate or other
  computed expression (e.g. `COUNT(diagnosis_code)`), that usage is
  unsupported for `exclude` and MUST be treated as `reject` instead —
  the whole query is rejected with `reason_code: ROLE_GATE_MISMATCH`
  rather than silently rewriting the expression, since doing so would
  change the aggregate's meaning without the caller's knowledge.
- **FR-009**: The system MUST reject any query referencing a table or
  column that has no active approved policy, defaulting closed. This
  default-closed check applies at column granularity, not whole-schema
  granularity: for a partially classified schema (some columns
  `approved`/`auto_approved`, others still `pending_review`), a query
  touching only approved columns MUST still be evaluated normally
  (`allow`/`block`/`role_gate` per FR-008); a query touching any column
  absent from the published policy artifact — including one still
  `pending_review` — MUST be rejected with `reason_code: NO_ACTIVE_POLICY`
  for that column, without requiring the entire schema to reach 100%
  classification first.
- **FR-010**: The system MUST log every classification decision and every
  enforcement decision (allow/block/mask, and why) in a queryable audit
  log. `mask` is reserved for a future milestone — Milestone 1's policy
  actions are limited to `allow`/`block`/`role_gate` (FR-008), so no
  enforcement decision ever logs `mask` yet. Every enforcement decision's
  "why" MUST be one of a fixed,
  versioned reason-code enum (`COLUMN_BLOCKED`, `NO_ACTIVE_POLICY`,
  `DML_REJECTED`, `MULTIPLE_STATEMENTS_REJECTED`, `ROLE_GATE_MISMATCH`,
  `SCHEMA_NOT_CLASSIFIED`, `QUESTION_NOT_MAPPED`, `ENFORCEMENT_ERROR`),
  each paired with a human-readable message template — never a free-form
  string alone — so that querying by decision type (NFR-004) does not
  depend on string matching.
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
  LLM-reported metadata about the statement's nature (Scenario 9). This
  check MUST also reject, unconditionally and before any other check,
  any input that parses into more than one SQL statement (e.g., a
  `SELECT` followed by a stacked `DROP TABLE`) — only the first statement
  being inspected is explicitly disallowed, since that would reopen the
  self-report/bypass failure mode Constitution Principle I exists to
  prevent; this is logged with its own reason,
  `MULTIPLE_STATEMENTS_REJECTED`. A question that cannot be mapped to any
  table in the domain's active policy MUST NOT execute any SQL and MUST
  NOT reveal schema details that a policy would otherwise block
  (Scenario 10).

## Non-Functional Requirements / Constraints

- **NFR-001**: Classification of a schema of up to 50 tables MUST complete
  in under 5 minutes end-to-end (heuristic + LLM-assisted passes).
- **NFR-002**: Policy enforcement checks on a single query MUST add no
  more than 200ms of latency (deterministic checks only — no LLM calls
  permitted in the enforcement path itself, per Constitution Principle I).
  This is a measured performance target validated in eval/CI, not a
  separate runtime timeout enforced in the request path; there is no
  distinct "budget exceeded" behavior beyond FR-007's existing fail-closed
  `ENFORCEMENT_ERROR` path, which already applies if the enforcement
  component errors for any reason. Measured as p95 latency over a
  single-query, no-concurrent-load benchmark run in the eval/CI script.
- **NFR-003**: All policy artifacts MUST be version-controlled and
  diffable (plain YAML or JSON, not a binary format).
- **NFR-004**: The audit log MUST be queryable by domain, time range, and
  decision type (allow/block/mask) without requiring log-scraping.

## Key Entities

- **Column Classification**: `{table, column, classification, confidence,
  source (heuristic|llm|human), reviewed_by, reviewed_at}`
- **Policy Artifact**: `{domain, version, tables: [{table_name, columns:
  {...}, row_policy_template}], approved_by, approved_at}`
- **Audit Log Entry**: `{timestamp, domain, query_id, decision, reason_code,
  reason_message, policy_version_used}` — `reason_code` is a fixed,
  versioned enum value (`COLUMN_BLOCKED`, `NO_ACTIVE_POLICY`,
  `DML_REJECTED`, `MULTIPLE_STATEMENTS_REJECTED`, `ROLE_GATE_MISMATCH`,
  `SCHEMA_NOT_CLASSIFIED`, `QUESTION_NOT_MAPPED`, `ENFORCEMENT_ERROR`),
  and `reason_message` is the associated human-readable message rendered
  from that code's template, per FR-010.

Two supporting, non-persisted concepts are also defined in `data-model.md`
but are intentionally not listed above since they aren't stored business
entities: **Caller** (the per-request role and, when required by a
table's row-policy template, tenant_id, both from FR-008's auth stub) and
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
  production authentication. The stub's header values (`X-Steward-Role`,
  `X-Steward-Tenant`) are assumed trustworthy and unspoofed for this
  milestone; no signature, session, or identity-provider verification
  guards them — that hardening belongs to the out-of-scope "real auth
  integration" item above, not to this milestone's enforcement guarantee.

## Success Criteria

- Classifier precision and recall, measured against hand-labeled ground
  truth (20–30 columns per domain), meet or exceed a target agreed upon
  in `plan.md` (suggested starting bar: precision ≥ 0.85, recall ≥ 0.85
  on `pii_direct` classifications specifically, since false negatives
  there are the highest-consequence error).
- All eleven behavioral scenarios above pass as automated tests.
- Deterministic column resolution is separately tested against joins,
  CTEs, subqueries, and `SELECT *` expansion (not only the flat-query
  shapes the eleven scenarios happen to use) for each of: the
  no-active-policy check, the `role_gate` check, and row-policy predicate
  injection.
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

### Session 2026-07-24

- **Q: When the policy enforcement path itself fails — the active policy
  artifact can't be loaded, or the enforcement component hits an
  unexpected internal error — what should happen to the query?**
  **A**: Fail closed uniformly. Both a policy-load failure and an
  unexpected internal enforcement error reject the query before
  execution, logged under a distinct reason (`ENFORCEMENT_ERROR`),
  consistent with FR-009's default-closed behavior — an enforcement-path
  failure is never allowed to behave like an implicit pass. Affects
  FR-007.

- **Q: When a single query trips more than one independent
  column/table-level policy violation (e.g., one referenced column has
  no approved policy while a different column is role-gated against the
  caller), what should the enforcement node report?**
  **A**: A fixed severity ranking, not AST scan order: `ENFORCEMENT_ERROR`
  / no-active-policy default-closed (FR-009) / explicit `block` (FR-008)
  rank highest (any one alone rejects the whole query), then `role_gate`
  mismatch (FR-008), then row-policy predicate injection (Scenario 5,
  which doesn't itself cause rejection). The FR-014 non-`SELECT`/DML
  check and the Scenario 10 question-to-schema mapping check remain
  structurally prior to this ranking, as FR-014 already specifies.
  Affects FR-007, FR-008, FR-009, FR-014.

- **Q: Does FR-014's non-`SELECT` rejection also cover a single input
  containing multiple SQL statements (e.g., a `SELECT` followed by a
  stacked `DROP TABLE`)?**
  **A**: Yes, unconditionally. Any input that parses into more than one
  SQL statement is rejected outright, before any per-statement check
  runs, logged with its own reason (`MULTIPLE_STATEMENTS_REJECTED`) —
  never evaluated as "check only the first statement," since that would
  reopen exactly the self-report/bypass failure mode Constitution
  Principle I exists to prevent. Affects FR-014.

- **Q: When the LLM-generated SQL already contains its own predicate on
  the row-policy's governed column (e.g., a wrong or conflicting
  `tenant_id = 'x'`), how should the injected row-policy predicate
  combine with it?**
  **A**: AND-merge, not overwrite. The enforcement component wraps the
  LLM's existing `WHERE` clause in parentheses and ANDs it with the
  policy's own predicate, at the AST level, without attempting to detect
  or strip anything the LLM wrote. This can only ever narrow the result
  set, never widen it, regardless of what the LLM's clause contains —
  correct even when the LLM's predicate can't be reliably identified and
  removed from an arbitrary boolean expression. Affects Scenario 5.

- **Q: Should the audit log's enforcement "reason" (e.g.,
  "column blocked by policy: X", "schema not yet classified",
  `enforcement_error`, `multiple_statements_rejected`) be a fixed,
  enumerable scheme, or free-form text?**
  **A**: A fixed, versioned reason-code enum — `COLUMN_BLOCKED`,
  `NO_ACTIVE_POLICY`, `DML_REJECTED`, `MULTIPLE_STATEMENTS_REJECTED`,
  `ROLE_GATE_MISMATCH`, `SCHEMA_NOT_CLASSIFIED`, `QUESTION_NOT_MAPPED`,
  `ENFORCEMENT_ERROR` — each paired with a human-readable message
  template. This is what makes NFR-004's "queryable... by decision type"
  requirement objectively testable, rather than dependent on exact
  string/substring matching. Affects FR-010, NFR-004, Key Entities
  (Audit Log Entry).

**Impact of this session**: FR-007 and FR-014 gained explicit
fail-closed/rejection requirements for enforcement-path failures and
multi-statement input; FR-007–FR-009/FR-014 gained a defined
violation-reporting precedence; Scenario 5 gained an explicit AND-merge
predicate-injection rule; and the audit log's `reason_code` field is now
a fixed enum rather than free text (FR-010).

### Session 2026-07-27

- **Q: How is `current_tenant` (used in row-policy predicate injection,
  Scenario 5) resolved from the caller/auth stub, and what happens if
  it's absent or malformed for a domain whose policy requires it?**
  **A**: A second auth-stub header, `X-Steward-Tenant`, parsed alongside
  `X-Steward-Role` into the `Caller` object. If a query touches a table
  whose `row_policy_template` needs it and the header is absent or
  malformed, the query is rejected fail-closed with
  `reason_code: ENFORCEMENT_ERROR` (FR-007) — treated as an
  enforcement-path resolution failure, not a distinct policy violation, so
  no new reason code was introduced. Affects FR-008, Scenario 5, Key
  Entities (Caller).

- **Q: What happens when a `role_gate` column with
  `on_role_mismatch: exclude` is referenced only inside an
  aggregate/computed expression (e.g. `COUNT(diagnosis_code)`), where
  dropping the raw column would change the aggregate's semantics?**
  **A**: Treated as unsupported for `exclude` and rejected as if
  `reject` had been configured — the whole query fails closed with
  `reason_code: ROLE_GATE_MISMATCH`. No SQL-rewriting/substitution logic
  (e.g. `COUNT(x)` → `COUNT(*)`) is introduced in Milestone 1; no
  scenario currently exercises `exclude` at all, so this closes a gap
  without adding new required behavior. Affects FR-008.

- **Q: When a policy publish (admin action) occurs concurrently with an
  in-flight query evaluation, is the query pinned to one policy version
  for its full evaluation, or could it see a partial update?**
  **A**: Pinned. The active policy version is resolved once, at the
  start of a query's enforcement evaluation, and used for every check in
  that evaluation; a concurrent publish has no effect on the in-flight
  query. This requires no new locking/coordination mechanism — it
  follows directly from the existing manifest-pointer resolution design
  (research.md §6) — and gives each query exactly one deterministic
  `policy_version_used` value for its audit log entry. Affects FR-007.

- **Q: If the deterministic enforcement check cannot complete within
  NFR-002's 200ms latency budget, what should happen — is that a
  fail-closed timeout, or is the budget undefined at runtime?**
  **A**: NFR-002 is a measured performance target validated in eval/CI,
  not a runtime timeout enforced in the request path. No new
  timeout/circuit-breaker mechanism is introduced; if the enforcement
  component errors for any reason, FR-007's existing fail-closed
  `ENFORCEMENT_ERROR` path already applies, so there's no separate
  "budget exceeded" behavior to define. Affects NFR-002.

- **Q: Is NFR-002's "≤200ms" enforcement-latency budget defined with a
  measurement methodology (percentile, load condition) sufficient to make
  pass/fail objective?**
  **A**: p95 latency, single query, no concurrent load — measured in the
  eval/CI benchmark script. Affects NFR-002.

**Impact of this session**: FR-008 and Scenario 5 gained an explicit
tenant-resolution mechanism (`X-Steward-Tenant` header) and fail-closed
behavior for row-policy injection; FR-008 gained a defined fail-closed
rule for `role_gate`/`exclude` columns referenced only inside aggregate
expressions; FR-007 gained an explicit policy-version-pinning guarantee
for in-flight queries; and NFR-002 gained both a defined runtime-timeout
posture (measured SLO, not a request-path cutoff) and a concrete
measurement methodology.

### Session 2026-07-28

- **Q: For a schema that's partially classified (some columns approved,
  others still pending_review), does FR-009's default-closed rule apply
  at column granularity within an otherwise-active policy?**
  **A**: Yes, column granularity. Approved/auto_approved columns remain
  enforceable per FR-008 (`allow`/`block`/`role_gate`); any column absent
  from the published artifact — including one still `pending_review` — is
  implicitly `block` for that column alone, without gating the rest of an
  otherwise-published schema. Affects FR-009.

- **Q: When multiple approved policy versions exist for a domain, which
  one is "the active policy artifact" FR-007 refers to — always the
  latest, or can an admin roll back to an earlier version?**
  **A**: Always the most recently published version. No rollback action
  exists in Milestone 1; the manifest pointer only ever advances forward
  on publish. Affects FR-007.

- **Q: Should every enforcement-path rejection share one consistent HTTP
  response contract, and how should Scenario 10's "question not mapped"
  case be treated?**
  **A**: Uniform 403 + 200 split. Every enforcement rejection
  (`COLUMN_BLOCKED`, `NO_ACTIVE_POLICY`, `DML_REJECTED`,
  `MULTIPLE_STATEMENTS_REJECTED`, `ROLE_GATE_MISMATCH`,
  `ENFORCEMENT_ERROR`) returns HTTP 403 with body
  `{reason_code, reason_message, query_id}`. `QUESTION_NOT_MAPPED`
  (Scenario 10) returns HTTP 200 with the same body shape, since it is a
  routing miss, not a policy violation. Affects FR-007.

- **Q: How much SQL structural complexity must deterministic column
  resolution provably handle in Milestone 1 — flat SELECT only, or
  joins/CTEs/subqueries/SELECT * too, with dedicated test coverage?**
  **A**: Full support, tested. Joins, CTEs, subqueries, and `SELECT *`
  must all resolve to concrete `table.column` for the no-active-policy
  check, the `role_gate` check, and row-policy injection alike, and the
  eval/BDD suite must include dedicated coverage per shape, not only the
  flat-query examples the eleven scenarios happen to use. Affects FR-007,
  Success Criteria.

- **Q: What happens when `X-Steward-Role` is present but holds a value
  other than `analyst`/`admin`, as distinct from the header being
  absent?**
  **A**: Treated identically to a missing header — defaults to
  `analyst`. No separate "invalid role value" error path exists. Affects
  FR-008.

**Impact of this session**: FR-007, FR-008, and FR-009 each gained an
explicit rule closing a gap `security.md`'s pre-implementation checklist
had flagged (partial-classification column granularity, active-policy-
version resolution, the enforcement HTTP response contract, deterministic
column-resolution scope, and unrecognized-role handling); Success Criteria
gained a dedicated column-resolution test-coverage requirement.

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

### 2026-07-24 — `/speckit.analyze` remediation

- **Reason-code casing** normalized: FR-007 and FR-014 previously used
  lowercase `enforcement_error`/`multiple_statements_rejected` while
  FR-010 and Key Entities used the uppercase enum spelling
  (`ENFORCEMENT_ERROR`/`MULTIPLE_STATEMENTS_REJECTED`) for the same
  codes. All in-line mentions (including the 2026-07-24 Clarifications
  session Q&A) now use the uppercase form consistently.
- **Scenario 11** added: the 2026-07-24 clarification session added
  FR-007's enforcement-path-failure fail-closed requirement
  (`ENFORCEMENT_ERROR`) and FR-007's severity-ranked violation-reporting
  precedence, but neither had a corresponding behavioral scenario —
  a zero-coverage gap against Constitution Principle VI. Scenario 11
  covers the fail-closed requirement directly; the severity-ranking rule
  is covered by a dedicated unit test task in `tasks.md` (T052a) rather
  than a new scenario, since it is an internal precedence rule, not a
  distinct user-observable flow.
- **Scenario 9** extended to also cover stacked multi-statement input
  (`MULTIPLE_STATEMENTS_REJECTED`), closing the same class of
  zero-coverage gap for FR-014's multi-statement-rejection requirement.
- Success Criteria updated from ten to eleven required passing
  scenarios.