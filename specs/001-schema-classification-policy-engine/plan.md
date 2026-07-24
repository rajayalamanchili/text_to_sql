# Implementation Plan: Schema Sensitivity Classification & Policy Enforcement Engine

**Branch**: `001-schema-classification-policy-engine` | **Date**: 2026-07-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-schema-classification-policy-engine/spec.md`

## Summary

Build the domain-agnostic classification + policy enforcement engine that is
Milestone 1 of Steward: enumerate an arbitrary relational schema, classify
each column's sensitivity via a heuristic pass followed by a conditional
LLM-assisted pass, route low-confidence results to a human-review queue
(admin-only approval), persist approved classifications as versioned YAML
policy artifacts, and deterministically enforce those policies against every
generated SQL query — via `sqlglot` AST inspection and predicate injection,
never LLM self-reporting — before execution. Validated identically against
two independently configured domains (healthcare, fintech) with zero
domain-specific code paths in the engine.

## Technical Context

**Language/Version**: Python 3.11+ (backend engine/API), TypeScript (admin
review UI)

**Primary Dependencies**: FastAPI, LangGraph, `sqlglot`, Pydantic v2,
`structlog` (backend); Next.js/React, Tailwind CSS, `openapi-typescript`
generated client (frontend) — all per `tech-stack.md` (locked, authoritative).

**Storage**: PostgreSQL — one instance/schema per domain (healthcare,
fintech) plus an `audit_log` table; versioned YAML policy artifacts
committed to git (not database-backed) per `tech-stack.md`.

**Testing**: `pytest` (unit/integration), `pytest-bdd` (executes the 10
Given/When/Then scenarios in `spec.md` directly), a custom precision/recall
scoring script against hand-labeled ground truth for classifier eval.

**Target Platform**: Linux server; local dev via Docker Compose (2×
Postgres, backend, frontend).

**Project Type**: Web application (FastAPI backend + Next.js frontend).

**Performance Goals**: Classify a 50-table schema end-to-end in under 5
minutes (NFR-001); policy enforcement check adds ≤200ms per query, with zero
LLM calls in the enforcement path itself (NFR-002, Constitution Principle I).

**Constraints**: No raw row-level data or raw identifiable values ever sent
to an LLM (FR-001, FR-003) — LLM classification input is masked/aggregated
patterns only; no real PII/PHI/financial data at any stage, synthetic data
only (FR-012, Constitution Principle VII); enforcement path must be
deterministic and independent of LLM self-report (Constitution Principle I).

**Scale/Scope**: Up to 50 tables per domain schema; 2 domains at Milestone 1
(healthcare, fintech); 20–30 hand-labeled ground-truth columns per domain for
the classifier eval; 2 roles (`analyst`, `admin`) via auth stub.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design (see below).*

| # | Principle | Status | How this plan satisfies it |
|---|---|---|---|
| I | Deterministic Enforcement Over LLM Self-Policing | PASS | Enforcement is a dedicated LangGraph node that parses SQL with `sqlglot` and checks it against the loaded policy artifact — the LLM's generated SQL is only ever a *proposal*; no LLM output about its own safety is trusted (see research.md §5). |
| II | Classify Before You Generate | PASS | Query graph only ever runs against columns with an active approved policy; FR-009/Scenario 6 (unclassified → blocked) enforced by the same deterministic node — absence of a policy entry is a reject, not a pass-through. |
| III | Human Review Is First-Class | PASS | FR-005/FR-013: confidence < 0.85 routes to `pending_review` status with no active policy until an `admin` approves via the review UI (Scenario 2, 8). |
| IV | One Engine, Many Policies | PASS | Domain-specific data lives entirely in `policies/<domain>/` YAML and `domains/<domain>/` config+seed scripts; engine source (`backend/src/`) has no `if domain == "healthcare"` branches — verified by FR-011's explicit test. |
| V | Spec Before Code | PASS | This plan follows an approved, clarified `spec.md`; `tasks.md` (next command) will not be generated until this plan is complete. |
| VI | Evaluation Is a Merge Gate | PASS (planned) | CI (GitHub Actions, per `tech-stack.md`) runs `pytest-bdd` scenario suite + classifier precision/recall script on every PR; both are part of this milestone's Definition of Done, not follow-up work. |
| VII | Synthetic Data, Honest Claims | PASS | Healthcare data from Synthea, fintech from Faker/PaySim-style generation (FR-012); no real data path exists anywhere in `domains/`. |
| VIII | Observability and Auditability by Default | PASS | Every classification and enforcement decision writes to the `audit_log` Postgres table via `structlog`-emitted structured events (FR-010, NFR-004); see data-model.md. |
| IX | Bounded Autonomy | N/A | No agentic retry/tool-use loop exists in Milestone 1 — the LLM-assisted classification pass (FR-003) is a single bounded call per column, not a loop. Revisit at Milestone 3. |
| X | Milestones Are Sequential | PASS | This is Milestone 1; no Milestone 2+ capability (RAG, agentic loop, MCP) appears in this plan's scope or structure. |

No violations requiring justification — Complexity Tracking is not needed.

**Post-Design Re-check** (after Phase 1): `data-model.md` and `contracts/`
introduce no new domain-specific engine logic, no LLM involvement in the
enforcement path, and no unbounded loops — all ten principles above still
hold as designed.

**`/speckit.analyze` remediation (2026-07-23)**: Two issues surfaced by
analysis have been resolved:
- `spec.md` Scenario 7's role-gate example was corrected (it had briefly
  become self-contradictory); it now uses two distinct roles from FR-008's
  fixed `{analyst, admin}` set, consistent with `contracts/policy-artifact.schema.yaml`.
- Principle VI requires eval coverage for "irrelevant" and "DML-attempt"
  questions, which no scenario previously exercised — directly relevant to
  Principle I's rationale (the prior prototype's DML-self-report flaw).
  `spec.md` now includes Scenario 9 (DML-attempt rejected unconditionally)
  and Scenario 10 (irrelevant question, no schema leak/bypass), backed by
  new FR-014. This plan's enforcement design (research.md §5) already
  parses every statement's AST before evaluating column/table policy, so
  supporting FR-014 is an additive check in the same enforcement node, not
  a new architectural component.

**`/speckit.analyze` follow-up pass (2026-07-23)**: Three lower-severity
items from the same analysis are also resolved: FR-008 now defines the
reject-vs-exclude `role_gate` configuration Scenario 7 referenced (see
spec.md); the `policy/` structure below no longer names an unimplemented
`policy_loader.py` alongside `policy_store.py`; and `spec.md`'s Key Entities
section now cross-references `Caller` and `Domain` (defined in
data-model.md) for completeness.

## Project Structure

### Documentation (this feature)

```text
specs/001-schema-classification-policy-engine/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/
├── src/
│   ├── models/            # Pydantic models: ColumnClassification, PolicyArtifact,
│   │                      # AuditLogEntry, Caller/Role
│   ├── services/
│   │   ├── classification/  # heuristic_classifier.py, llm_classifier.py, confidence.py
│   │   ├── policy/          # policy_store.py (versioned YAML read/write + load/manifest resolution)
│   │   └── enforcement/     # sqlglot-based column check + row-predicate injection
│   ├── graph/              # LangGraph definitions: classification_graph.py, query_graph.py
│   └── api/                # FastAPI routers: schema, review_queue, policy, query, audit
├── policies/               # versioned YAML policy artifacts, one dir per domain
│   ├── healthcare/
│   └── fintech/
├── domains/                # domain config + synthetic data generation (no engine logic)
│   ├── healthcare/          # Synthea-derived schema.sql + seed script
│   └── fintech/             # Faker/PaySim-style schema.sql + seed script
└── tests/
    ├── contract/            # API contract tests
    ├── integration/          # pytest-bdd step defs for the 10 spec.md scenarios
    └── unit/                 # heuristic classifier, confidence combination, sqlglot enforcement

frontend/
├── src/
│   ├── app/
│   │   └── admin-review/   # FR-013 human-review queue UI (Next.js route)
│   ├── components/
│   └── services/            # OpenAPI-generated API client
└── tests/
```

**Structure Decision**: Web application layout (backend + frontend), per the
template's Option 2, since this feature ships both a FastAPI engine and the
FR-013 admin review UI on the locked Next.js/TypeScript stack. The admin
review UI is a distinct route (`frontend/src/app/admin-review/`) inside the
one shared frontend codebase per `tech-stack.md`'s note, not a separate app —
keeping it isolated from the future end-user query UI's scope.
