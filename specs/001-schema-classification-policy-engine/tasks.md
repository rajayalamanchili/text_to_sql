# Tasks: Schema Sensitivity Classification & Policy Enforcement Engine

**Input**: Design documents from `/specs/001-schema-classification-policy-engine/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present)

**Tests**: Included and REQUIRED, not optional — spec.md's Success Criteria states
"All ten behavioral scenarios above pass as automated tests," and Constitution
Principle VI ("Evaluation Is a Merge Gate") makes the eval suite mandatory for
milestone completion.

**Organization**: Tasks are grouped by user story, derived from `spec.md`'s 10
behavioral scenarios, sequenced for incremental delivery. Priorities reflect what
must exist, in order, for the engine's core guarantee (classify → review → enforce,
fail closed) to be real and demoable.

**2026-07-23 update**: Following `/speckit.analyze`, this file adds T053–T057
(DML-attempt rejection, irrelevant-question handling, and the previously-missing
`GET /audit-log` endpoint) and renumbers all subsequent tasks (former T053–T066
are now T058–T071). T064 (formerly T059) is also updated: the `spec.md` Scenario 7
inconsistency it referenced has been corrected, so it is now a normal task rather
than a blocked one.

**2026-07-23 follow-up pass**: T063's description now names the
`on_role_mismatch` config (FR-008) it implements, and T072 was added to give
FR-012 (synthetic-data-only) a dedicated regression safeguard.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Paths follow the Web application structure from `plan.md` (`backend/`, `frontend/`)

## User Stories (priority order)

| Story | Scenarios covered | Priority | Delivers |
|---|---|---|---|
| US1 | 1, 2, 3 | P1 (MVP) | Heuristic + LLM-assisted classification pipeline with conservative, auditable confidence scoring |
| US2 | 8 (FR-013) | P1 | Human-review queue + admin-only approval workflow |
| US3 | 4, 6, 9, 10 | P1 (MVP) | Policy publishing + deterministic column-level enforcement (default-closed, DML-rejecting, schema-mapping-aware) + queryable audit log |
| US4 | 5 | P2 | Row-level predicate injection |
| US5 | 7 | P2 | Role-gated column access |

US1–US3 together are the smallest slice that proves Constitution Principles
I–III end to end (classify, review, enforce-closed) and are treated as the MVP.
US4/US5 extend enforcement to row-level and role-based policy but are not
required to prove the core guardrail claim.

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Create backend Python project (`uv`, `pyproject.toml`, FastAPI/LangGraph/sqlglot/Pydantic/structlog deps) per `plan.md` structure in `backend/`
- [ ] T002 Create frontend Next.js (TypeScript, Tailwind) project per `plan.md` structure in `frontend/`
- [ ] T003 [P] Configure Python linting/formatting (ruff) in `backend/pyproject.toml`
- [ ] T004 [P] Configure TypeScript linting/formatting (eslint/prettier) in `frontend/`
- [ ] T005 Docker Compose config for 2× Postgres (healthcare, fintech), backend, frontend in `docker-compose.yml`
- [ ] T006 [P] GitHub Actions CI skeleton in `.github/workflows/ci.yml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T007 Domain config loader (`healthcare`/`fintech` directory convention, FR-011) in `backend/src/config/domains.py`
- [ ] T008 [P] Postgres `audit_log` table migration (data-model.md#AuditLogEntry) in `backend/src/db/migrations/0001_audit_log.sql`
- [ ] T009 [P] `structlog` configuration + `AuditLogEntry` model and writer (research.md §8) in `backend/src/services/audit/audit_log.py`
- [ ] T010 [P] `Caller`/`Role` model + auth-stub FastAPI dependency parsing `X-Steward-Role`, defaulting to `analyst` (research.md §7) in `backend/src/api/deps.py`
- [ ] T011 FastAPI app skeleton + router registration in `backend/src/api/main.py` (depends on T010)
- [ ] T012 [P] Healthcare domain schema + Synthea-derived seed script (research.md §10) in `domains/healthcare/schema.sql`, `domains/healthcare/seed.py`
- [ ] T013 [P] Fintech domain schema + Faker/PaySim-style seed script (research.md §10) in `domains/fintech/schema.sql`, `domains/fintech/seed.py`
- [ ] T014 Wire both domain Postgres instances + seed scripts into Docker Compose init (depends on T005, T012, T013) in `docker-compose.yml`

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - Classify a domain schema (Priority: P1) 🎯 MVP

**Goal**: Given an arbitrary schema, produce a correct, conservative,
confidence-scored classification per column via heuristic + conditional
LLM-assisted passes — never silently marking risky/unknown columns safe.

**Independent Test**: Run enumerate + classify against the healthcare domain.
`patient_ssn` → `pii_direct`, confidence ≥ 0.9, not in review queue (Scenario 1).
A low-confidence fintech `notes` column lands in `pending_review`, confidence
< 0.85 (Scenario 2). `patient_notes` is never auto-classified `business`
(Scenario 3).

### Tests for User Story 1

- [ ] T015 [P] [US1] BDD step defs for Scenario 1 (obvious PII classified correctly) in `backend/tests/integration/test_scenario1_pii_direct.py`
- [ ] T016 [P] [US1] BDD step defs for Scenario 2 (ambiguous column → human review) in `backend/tests/integration/test_scenario2_review_queue.py`
- [ ] T017 [P] [US1] BDD step defs for Scenario 3 (adversarial column not misclassified safe) in `backend/tests/integration/test_scenario3_adversarial.py`

### Implementation for User Story 1

- [ ] T018 [P] [US1] `ColumnClassification` Pydantic model (data-model.md) in `backend/src/models/column_classification.py`
- [ ] T019 [US1] Schema enumeration service, no LLM calls, no raw row data (FR-001) in `backend/src/services/enumeration/schema_enumerator.py` (depends on T007)
- [ ] T020 [P] [US1] Heuristic classifier: name-pattern dictionary + type/cardinality signals + capped 0.95 confidence + adversarial free-text default to `sensitive_category` (research.md §1–2) in `backend/src/services/classification/heuristic_classifier.py` (depends on T018)
- [ ] T021 [P] [US1] Value-pattern masking utility: length buckets + regex-generalized pattern classes, never raw values (research.md §3) in `backend/src/services/classification/masking.py`
- [ ] T022 [US1] LLM-assisted classifier consuming only masked input (FR-003) in `backend/src/services/classification/llm_classifier.py` (depends on T021)
- [ ] T023 [US1] Confidence combination logic: agree → max, disagree → more-sensitive category wins + min confidence (research.md §4) in `backend/src/services/classification/confidence.py` (depends on T020, T022)
- [ ] T024 [US1] Classification LangGraph graph: enumerate → heuristic → confidence gate → llm (conditional) → persist (research.md §9) in `backend/src/graph/classification_graph.py` (depends on T019, T023)
- [ ] T025 [US1] `POST /domains/{domain}/schema/enumerate` endpoint (contracts/api.md) in `backend/src/api/schema.py` (depends on T019, T011)
- [ ] T026 [US1] `POST /domains/{domain}/classify` endpoint (contracts/api.md) in `backend/src/api/classify.py` (depends on T024)
- [ ] T027 [US1] Persist classification results + `classify_*` audit log entries in `backend/src/services/classification/persistence.py` (depends on T009, T018)
- [ ] T028 [P] [US1] Hand-labeled ground truth set (20–30 columns) for healthcare in `backend/eval/ground_truth/healthcare.csv`
- [ ] T029 [P] [US1] Hand-labeled ground truth set (20–30 columns) for fintech in `backend/eval/ground_truth/fintech.csv`
- [ ] T030 [US1] Classifier precision/recall eval script (Success Criteria: ≥0.85 on `pii_direct`) in `backend/eval/classifier_eval.py` (depends on T028, T029)

**Checkpoint**: US1 fully functional and testable independently of review UI or enforcement.

---

## Phase 4: User Story 2 - Human review queue & admin approval (Priority: P1)

**Goal**: `pending_review` columns are visible with their source signals in an
admin UI; only an `admin`-role user can approve, reject, or reclassify one.

**Independent Test**: An `analyst`-role approve attempt returns 403 and leaves
the record `pending_review`; an `admin`-role approve returns 200, sets
`reviewed_by`/`reviewed_at`, and is recorded in the audit log (Scenario 8).

### Tests for User Story 2

- [ ] T031 [P] [US2] BDD step defs for Scenario 8 (only admin can approve) in `backend/tests/integration/test_scenario8_admin_approval.py`

### Implementation for User Story 2

- [ ] T032 [US2] `GET /domains/{domain}/review-queue` endpoint (contracts/api.md) in `backend/src/api/review_queue.py` (depends on T018, T011)
- [ ] T033 [US2] `POST .../review-queue/{column_id}/approve` endpoint, admin-only (contracts/api.md) in `backend/src/api/review_queue.py` (depends on T032)
- [ ] T034 [US2] `POST .../review-queue/{column_id}/reject` endpoint, admin-only in `backend/src/api/review_queue.py` (depends on T032)
- [ ] T035 [US2] `POST .../review-queue/{column_id}/reclassify` endpoint, admin-only in `backend/src/api/review_queue.py` (depends on T032)
- [ ] T036 [US2] Audit logging for approve/reject/reclassify actions, recording actor identity (FR-013) in `backend/src/services/audit/audit_log.py` (depends on T033, T034, T035)
- [ ] T037 [P] [US2] Admin review queue Next.js route in `frontend/src/app/admin-review/page.tsx`
- [ ] T038 [P] [US2] Review queue table component (column, proposed classification, confidence, source signals) in `frontend/src/app/admin-review/components/ReviewQueueTable.tsx`
- [ ] T039 [US2] Approve/reject/reclassify actions wired to generated OpenAPI client in `frontend/src/app/admin-review/actions.ts` (depends on T032-T035, T037)
- [ ] T040 [US2] Role-based UI guard hiding approve/reject controls from non-admin callers in `frontend/src/app/admin-review/page.tsx` (depends on T037)

**Checkpoint**: US1 + US2 both work independently — schema can be classified and reviewed end to end.

---

## Phase 5: User Story 3 - Policy publishing, deterministic enforcement & auditability (Priority: P1)

**Goal**: Approved classifications publish into a versioned policy artifact;
every query is deterministically checked against it — blocked columns are
rejected regardless of LLM behavior, any table/column with no active policy
defaults to blocked, any non-`SELECT` statement is rejected outright, an
off-schema question never touches the database, and every decision is
queryable in the audit log.

**Independent Test**: Publish a policy, then submit a query referencing a
`block`-policy column — expect 403 with reason `"column blocked by policy: <col>"`
(Scenario 4). Submit a query against an unclassified table — expect 403 with
reason `"schema not yet classified"` (Scenario 6). Submit a `DELETE` statement —
expect 403 with reason `"DML statement rejected: read-only queries only"`
(Scenario 9). Ask an off-schema question — expect no SQL execution and a
`"question not mapped to schema"` response (Scenario 10). Query
`GET /audit-log` and confirm all of the above decisions appear, filterable
by domain/time/decision (NFR-004).

### Tests for User Story 3

- [ ] T041 [P] [US3] BDD step defs for Scenario 4 (deterministic guardrail overrides incorrect LLM proposal) in `backend/tests/integration/test_scenario4_block_override.py`
- [ ] T042 [P] [US3] BDD step defs for Scenario 6 (unclassified column defaults to blocked) in `backend/tests/integration/test_scenario6_default_closed.py`

### Implementation for User Story 3

- [ ] T043 [P] [US3] `PolicyArtifact`/`PolicyTable`/`PolicyColumn` Pydantic models (data-model.md) in `backend/src/models/policy_artifact.py`
- [ ] T044 [US3] Policy store: versioned YAML read/write + manifest-based active-version resolution (research.md §6) in `backend/src/services/policy/policy_store.py` (depends on T043)
- [ ] T045 [US3] `POST /domains/{domain}/policy/publish` endpoint, admin-only, built from all `approved` classifications (contracts/api.md) in `backend/src/api/policy.py` (depends on T044, T027)
- [ ] T046 [US3] `GET /domains/{domain}/policy` endpoint in `backend/src/api/policy.py` (depends on T044)
- [ ] T047 [US3] `sqlglot`-based column resolver: `SELECT *`, joins, CTEs, subqueries → concrete `table.column` (research.md §5) in `backend/src/services/enforcement/column_resolver.py`
- [ ] T048 [US3] Deterministic enforcement node: `allow`/`block` decision + default-closed for any unresolved or policy-absent column (FR-007, FR-009) in `backend/src/services/enforcement/enforcer.py` (depends on T047, T044)
- [ ] T049 [US3] Minimal SQL proposal step (accepts `question` or raw `sql`, per spec "Out of Scope" — not production NL→SQL quality) in `backend/src/services/generation/sql_proposal.py`
- [ ] T050 [US3] Query LangGraph graph: generate → deterministic enforce → execute (only if passed) → audit (research.md §9) in `backend/src/graph/query_graph.py` (depends on T048, T049)
- [ ] T051 [US3] `POST /domains/{domain}/query` endpoint (contracts/api.md) in `backend/src/api/query.py` (depends on T050)
- [ ] T052 [US3] Enforcement-decision audit logging (allow/block + reason) in `backend/src/services/audit/audit_log.py` (depends on T048)
- [ ] T053 [P] [US3] BDD step defs for Scenario 9 (DML-attempt statement rejected unconditionally) in `backend/tests/integration/test_scenario9_dml_rejected.py`
- [ ] T054 [P] [US3] BDD step defs for Scenario 10 (irrelevant question does not leak schema or bypass enforcement) in `backend/tests/integration/test_scenario10_irrelevant_question.py`
- [ ] T055 [US3] DML/non-`SELECT` statement guard: reject any statement whose `sqlglot`-parsed root is not a `SELECT`, before any column/table policy check (FR-014, research.md §5) in `backend/src/services/enforcement/enforcer.py` (depends on T047)
- [ ] T056 [US3] Irrelevant-question handling in the query graph: no schema-relevant mapping → return `"question not mapped to schema"` without generating or executing SQL (FR-014, Scenario 10) in `backend/src/graph/query_graph.py` (depends on T050)
- [ ] T057 [US3] `GET /audit-log` endpoint with domain/time-range/decision-type filters (contracts/api.md, NFR-004) in `backend/src/api/audit.py` (depends on T008, T009)

**Checkpoint**: US1 + US2 + US3 complete — this is the MVP. The core Constitution Principle I/II/VIII guarantee (classify, review, enforce-closed, DML-safe, auditable) is fully demoable.

---

## Phase 6: User Story 4 - Row-level policy enforcement (Priority: P2)

**Goal**: A table's `row_policy_template` predicate is injected into every
executed query deterministically, regardless of what the LLM-generated SQL
did or didn't scope.

**Independent Test**: Ask a question that never mentions tenant scoping;
verify the executed query includes the injected `tenant_id = :current_tenant`
predicate and never returns cross-tenant rows (Scenario 5).

### Tests for User Story 4

- [ ] T058 [P] [US4] BDD step defs for Scenario 5 (row-level policy applied regardless of LLM predicates) in `backend/tests/integration/test_scenario5_row_policy.py`

### Implementation for User Story 4

- [ ] T059 [US4] Row-predicate injector: AST-level `WHERE`-clause manipulation, not string concatenation (research.md §5.3) in `backend/src/services/enforcement/row_predicate_injector.py` (depends on T047)
- [ ] T060 [US4] Wire row-predicate injection into the enforcement node in `backend/src/services/enforcement/enforcer.py` (depends on T048, T059)
- [ ] T061 [US4] Add `tenant_id` `row_policy_template` to the fintech policy artifact in `policies/fintech/<version>/policy.yaml` (depends on T044)

**Checkpoint**: US1–US4 all independently functional.

---

## Phase 7: User Story 5 - Role-gated column access (Priority: P2)

**Goal**: A `role_gate` column is visible/allowed only to the roles listed on
its policy entry.

**Independent Test**: The same query is rejected (or the column silently
excluded, per FR-008 configuration) for a caller without the required role
(`analyst`), and succeeds for a caller with it (`admin`) (Scenario 7).

### Tests for User Story 5

- [ ] T062 [P] [US5] BDD step defs for Scenario 7 (role-gated column visible only to correct role) in `backend/tests/integration/test_scenario7_role_gate.py`

### Implementation for User Story 5

- [ ] T063 [US5] `role_gate` enforcement branch in the enforcement node, checked against the caller's role from the auth stub, honoring the column's `on_role_mismatch` setting (`reject` by default, `exclude` if explicitly configured; FR-008) in `backend/src/services/enforcement/enforcer.py` (depends on T048)
- [ ] T064 [US5] Finalize the `diagnosis_code` gated-role config (`roles: [admin]`, per spec.md Scenario 7 as corrected on 2026-07-23) in `policies/healthcare/<version>/policy.yaml` (depends on T044)

**Checkpoint**: All 5 user stories independently functional — all 10 `spec.md` scenarios have a corresponding passing test.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T065 [P] Update `README.md` with setup + quickstart pointers
- [ ] T066 GitHub Actions CI: run the full `pytest-bdd` suite + `classifier_eval.py` on every PR, failing eval blocks merge (Constitution Principle VI) in `.github/workflows/ci.yml` (depends on T006, T030, T015-T017, T031, T041-T042, T053-T054, T058, T062)
- [ ] T067 [P] Cross-domain regression check: assert zero domain-specific conditionals in engine source (FR-011, Success Criteria) in `backend/tests/unit/test_no_domain_conditionals.py`
- [ ] T068 [P] NFR-001 timing test: 50-table schema classifies end-to-end in under 5 minutes in `backend/tests/integration/test_nfr001_classification_latency.py`
- [ ] T069 [P] NFR-002 latency test: enforcement check adds ≤200ms per query in `backend/tests/integration/test_nfr002_enforcement_latency.py`
- [ ] T070 [P] Security test: assert the masking utility never emits raw sample values into an LLM prompt (FR-003, Principle I) in `backend/tests/unit/test_masking_no_raw_values.py`
- [ ] T071 Run `quickstart.md` validation end-to-end (including Scenarios 9, 10, and the `GET /audit-log` walkthrough) and record results
- [ ] T072 [P] Synthetic-data safeguard test: assert `domains/healthcare/seed.py` and `domains/fintech/seed.py` only construct data via the checked-in Synthea/Faker generators and never read a non-local or externally-supplied connection string (FR-012, Constitution Principle VII) in `backend/tests/unit/test_synthetic_data_only.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories.
- **US1 (Phase 3)**: Depends on Foundational only.
- **US2 (Phase 4)**: Depends on Foundational + US1's `ColumnClassification` model and persisted data (T018, T027) to have something to review.
- **US3 (Phase 5)**: Depends on Foundational + US2's `approved` classifications (T027, T036) as publish input.
- **US4 (Phase 6)**: Depends on US3's column resolver and enforcement node (T047, T048).
- **US5 (Phase 7)**: Depends on US3's enforcement node (T048); independent of US4.
- **Polish (Phase 8)**: Depends on all desired user stories being complete.

### User Story Dependencies

Unlike a typical CRUD feature, these five stories form a genuine pipeline
(classify → review → enforce → row-policy/role-gate extensions), so they are
**sequential by design**, not parallel-by-team. US4 and US5 are mutually
independent of each other once US3 is done and can be split across two
developers.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (BDD steps reference
  endpoints/services that don't exist yet).
- Models before services; services before endpoints; core before integration.
- Story complete before moving to next priority.

### Parallel Opportunities

- All `[P]`-marked Setup tasks (T003, T004, T006) in parallel.
- All `[P]`-marked Foundational tasks (T008–T010, T012–T013) in parallel.
- Within US1: T015–T017 (tests), and T018/T020/T021 (independent files) in parallel.
- Within US2: T037–T038 (frontend files) in parallel with backend T032–T036.
- Within US3: T041–T042 and T053–T054 (tests), and T043, in parallel.
- Within Polish: T065, T067–T070, T072 in parallel.

---

## Parallel Example: User Story 1

```bash
# Tests together:
Task: "BDD step defs for Scenario 1 in backend/tests/integration/test_scenario1_pii_direct.py"
Task: "BDD step defs for Scenario 2 in backend/tests/integration/test_scenario2_review_queue.py"
Task: "BDD step defs for Scenario 3 in backend/tests/integration/test_scenario3_adversarial.py"

# Independent model/service files together:
Task: "ColumnClassification model in backend/src/models/column_classification.py"
Task: "Heuristic classifier in backend/src/services/classification/heuristic_classifier.py"
Task: "Value-pattern masking utility in backend/src/services/classification/masking.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2 + US3)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (CRITICAL — blocks everything).
3. Complete Phase 3: US1 (classification pipeline) → validate independently.
4. Complete Phase 4: US2 (review + approval) → validate independently.
5. Complete Phase 5: US3 (policy publish + enforcement + audit query) → validate independently.
6. **STOP and VALIDATE**: run `quickstart.md` steps 1–7 (enforcement, DML-rejection,
   irrelevant-question, and audit-log query scenarios). This MVP alone already
   proves Constitution Principles I–III and VIII.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → classify a schema, inspect results directly via API (no UI needed yet).
3. US2 → review queue usable end to end (MVP milestone: classify + govern).
4. US3 → **MVP complete**: enforcement guardrail is real and demoable (Scenarios 4/6/9/10), and the audit trail is queryable (NFR-004).
5. US4 → row-level policy (Scenario 5).
6. US5 → role gating (Scenario 7).
7. Polish → CI gate, NFR checks, cross-domain regression proof, full quickstart run.

---

## Notes

- `[P]` tasks touch different files with no unmet dependencies.
- `[Story]` labels map every implementation task to one of spec.md's 10 scenarios for traceability.
- T053–T057 and the corrected T064 were added/updated on 2026-07-23 following
  `/speckit.analyze`: the prior version of this file had zero task coverage for
  DML-attempt/irrelevant-question eval (Constitution Principle VI) and for the
  `GET /audit-log` endpoint (NFR-004), and T059 (now T064) referenced a
  since-corrected spec inconsistency.
- T072 was added in a `/speckit.analyze` follow-up pass on 2026-07-23: FR-012
  (synthetic-data-only) previously had no dedicated regression safeguard task.
- Commit after each task or logical group; stop at any checkpoint to validate a story independently.
- Avoid: same-file conflicts within a `[P]` batch, and any engine code path that branches on domain name (Constitution Principle IV, checked by T067).
