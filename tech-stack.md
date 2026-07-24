# Tech Stack

**Project**: Steward
**Status**: Locked for Milestone 1 — changes require updating this file
with rationale, not silent drift inside an individual feature's `plan.md`
**Last amended**: 2026-07-23

## Purpose

This document is the single source of truth for cross-feature technology
choices. Every `/speckit.plan` run for every feature MUST treat this file
as authoritative and MUST NOT introduce an alternative for anything
listed here without first amending this document. Per Constitution
Principle IV ("One Engine, Many Policies"), the goal is one consistent
engine — inconsistent per-feature tech choices undermine that directly.

---

## Backend (engine, policy enforcement, orchestration)

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Mature ecosystem for SQL parsing, LangGraph, and eval tooling (see below). |
| Orchestration | LangGraph | Already proven in the prior prototype; explicit graph structure supports the deterministic-enforcement-node pattern required by Constitution Principle I. |
| API framework | FastAPI | Async-native, typed request/response models via Pydantic, auto-generated OpenAPI spec that can be diffed against the hand-written API spec. |
| SQL parsing/validation | `sqlglot` | Deterministic AST-level SQL inspection — this is what replaces LLM self-reported DML/safety flags with a real, testable check (Constitution Principle I, directly fixes the prior prototype's core flaw). |
| Data validation | Pydantic v2 | Typed schemas for policy artifacts, classification records, and API contracts. |
| LLM provider | Anthropic Claude (primary), OpenAI (secondary/configurable) | Provider-agnostic interface required; do not hardcode a single vendor into engine logic. |
| Package management | `uv` | Fast, reproducible dependency resolution; lockfile committed. |

## Frontend

| Concern | Choice | Rationale |
|---|---|---|
| Language | TypeScript | Per your explicit direction — type-safe contract with the FastAPI backend via generated types from the OpenAPI spec. |
| Framework | Next.js (React) | Standard, well-documented, good fit for both the end-user query UI and the Milestone 1 admin review UI. |
| Styling | Tailwind CSS | Fast to build with, low bespoke-CSS maintenance burden for a solo project. |
| API client | Generated from OpenAPI spec (e.g., `openapi-typescript`) | Keeps frontend/backend contract in sync automatically rather than hand-maintained, reducing drift risk. |

**Note**: the Milestone 1 admin review UI (FR-013) and the eventual
end-user query UI are the same frontend stack but are **separate Next.js
routes/apps within one frontend codebase** — not two different
technologies. Keep them logically separate so the admin UI doesn't grow
end-user-product scope by accident.

## Data layer

| Concern | Choice | Rationale |
|---|---|---|
| Database (per domain) | PostgreSQL | Realistic enterprise-grade RDBMS; single engine works across both healthcare and fintech domain databases, each as a separate Postgres instance/schema. |
| Healthcare synthetic data | Synthea | Widely used, credible synthetic-PHI generator; avoids ever touching real patient data (Constitution Principle VII). |
| Fintech synthetic data | Faker-generated schema + PaySim-style transaction patterns | Realistic without licensing or real-account-data risk. |
| Policy artifact storage | Versioned YAML files in git (Milestone 1) | Diffable, reviewable via PR, satisfies NFR-003. Migration to a database-backed policy store is a candidate for a later milestone if needed — not assumed now. |
| Future RAG vector store (Milestone 2) | `pgvector` extension on the existing Postgres instances | Avoids introducing a second database technology just for embeddings; deferred until Milestone 2 begins. |

## Testing & evaluation

| Concern | Choice | Rationale |
|---|---|---|
| Unit/integration tests | `pytest` | Standard, well-supported. |
| Behavioral scenario tests | `pytest-bdd` | Directly executes the Given/When/Then scenarios written in each feature's `spec.md`, keeping spec and test in lockstep (Constitution Principle V). |
| Classifier accuracy eval | Custom scoring script against hand-labeled ground truth (precision/recall) | No existing off-the-shelf tool fits this narrow task well; keep it simple and inspectable. |
| Future RAG retrieval eval (Milestone 2) | Ragas or a custom precision/recall-at-K script | Decide at Milestone 2 planning time; not needed yet. |
| CI | GitHub Actions | Runs the behavioral scenario suite and classifier eval on every PR; failing eval blocks merge (Constitution Principle VI enforced mechanically, not just by discipline). |

## Observability

| Concern | Choice | Rationale |
|---|---|---|
| Logging | Python `structlog`, JSON-formatted | Structured logs are required for the audit log's queryability (NFR-004) without building a bespoke log-query system. |
| Audit log storage | Postgres table (`audit_log`), same instance pattern as domain data | Keeps infra minimal; queryable via plain SQL, satisfies NFR-004 without adding a new system. |
| Metrics/tracing (later milestones) | OpenTelemetry, deferred | Not required for Milestone 1; revisit when the agentic loop (Milestone 3) introduces variable-length execution paths worth tracing. |

## Auth (Milestone 1 scope only)

| Concern | Choice | Rationale |
|---|---|---|
| Role identification | Request header / config-value stub asserting `analyst` or `admin` | Sufficient to prove role-gate enforcement logic (FR-008, FR-013) without building real identity infrastructure, which is explicitly out of scope per the spec. |
| Future real auth | Not decided — deferred | Do not pre-select an auth provider (Auth0, Clerk, etc.) until a milestone actually requires it; premature choice here risks unused complexity. |

## Infrastructure & local development

| Concern | Choice | Rationale |
|---|---|---|
| Local dev environment | Docker Compose (Postgres ×2 domains, backend, frontend) | One-command local spin-up, matches how a reviewer would actually try the project. |
| Deployment target | Not yet decided | Deliberately deferred — Milestone 1's success criteria do not require a live deployment; revisit once the milestone sequence is further along. |

## Explicitly not yet decided (do not pre-select)

- RAG embedding model and chunking strategy — Milestone 2 planning.
- Agentic loop framework specifics (may extend existing LangGraph nodes
  rather than adopt a new library) — Milestone 3 planning.
- MCP SDK specifics (Python vs. TypeScript MCP server) — Milestone 4
  planning.

Per Constitution Principle X, these are intentionally left open rather
than decided now, so that Milestone 1 stays scoped to what it actually
needs.

---

**Version**: 1.0.0 — Locked 2026-07-23, scoped to Milestone 1