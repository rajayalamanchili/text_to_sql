# Roadmap

**Project**: Steward
**Governing rule**: per Constitution Principle X, a milestone does not
begin until the prior milestone's full evaluation suite is green. Do not
reorder or parallelize the milestones below without amending
`constitution.md` first.

---

## Milestone 1: Schema Classification & Policy Enforcement Engine
**Spec**: `specs/001-schema-classification-policy-engine/spec.md`
**Status**: Spec clarified, ready for `/speckit.plan`

**Scope**: Domain-agnostic sensitivity classifier (heuristic + LLM-assisted
+ human review), versioned policy artifacts, deterministic policy
enforcement at query time, audit logging, role-gated admin review UI.
Validated against two configured domains (healthcare, fintech).

**Definition of done**:
- Classifier precision/recall ≥ target (see spec Success Criteria) against
  hand-labeled ground truth, both domains.
- All 8 behavioral scenarios in `spec.md` pass as automated tests.
- Same engine codebase runs both domains with zero domain-specific
  conditionals in engine source.
- CI gate enforces the above on every PR.

**Explicitly not included**: SQL generation quality tuning, schema
retrieval at scale, agentic retry loops, MCP exposure, end-user frontend.

---

## Milestone 2: RAG-Based Schema Retrieval
**Spec**: not yet written — do not begin until Milestone 1 DoD is met
**Status**: Not started

**Scope**: For schemas too large to fit entirely in a prompt, embed
table/column metadata (post-classification, so only approved-visible
columns are ever embedded) and retrieve the top-K relevant tables per
question. Adds a retrieval-accuracy eval layer.

**Definition of done** (draft, to be formalized in its own `spec.md`):
- Retrieval precision/recall-at-K meets a target against a labeled set of
  (question → correct tables) pairs, per domain.
- Milestone 1's full eval suite still passes (regression check).
- Retrieval never surfaces a column that Milestone 1's policy engine
  would block — this is a required cross-milestone test, not assumed.

**Explicitly not included**: agentic retry loops, MCP exposure.

---

## Milestone 3: Bounded Agentic Self-Correction Loop
**Spec**: not yet written — do not begin until Milestone 2 DoD is met
**Status**: Not started

**Scope**: Replace the fixed linear generate→validate→execute path with a
bounded retry loop (on SQL execution error, re-prompt with the error,
retry up to a hard iteration cap) and an explicit clarification path for
ambiguous questions. Introduces cost/latency/iteration budgets per
Constitution Principle IX.

**Definition of done** (draft):
- Loop convergence rate (fraction of initially-failing queries that
  succeed within the iteration cap) meets a target.
- Hard budget enforcement verified by test (loop cannot exceed cap
  regardless of model behavior).
- Every retry iteration re-checks policy enforcement — a retry MUST NOT
  bypass Milestone 1's guardrails (explicit adversarial test case
  required).
- Milestones 1 and 2 eval suites still pass.

**Explicitly not included**: MCP exposure, multi-agent sub-agent
architecture (deferred further, not currently roadmapped — revisit only
if a concrete need emerges).

---

## Milestone 4: MCP Server Exposure
**Spec**: not yet written — do not begin until Milestone 3 DoD is met
**Status**: Not started

**Scope**: Expose the query engine as an MCP server (e.g., `query_claims`,
`query_transactions` tools) so any MCP-compatible client can call it.
Policy enforcement must behave identically regardless of caller (frontend
vs. MCP client) — this is the test that proves enforcement lives at the
right layer.

**Definition of done** (draft):
- Identical policy enforcement behavior verified via test, comparing
  frontend-originated and MCP-originated requests for the same question
  and role.
- Milestones 1–3 eval suites still pass.

---

## Parallel, independent track: TypeScript Frontend
**Spec**: not yet written — independently scoped, not gated by the
milestone sequence above, but the Milestone 1 admin review UI (FR-013)
is the first concrete piece of this track and ships as part of
Milestone 1.

**Scope**: End-user natural-language query interface, built on the same
Next.js/TypeScript stack as the Milestone 1 admin UI (see
`tech-stack.md`). Can be developed incrementally alongside the engine
milestones since it is a consumer of the API, not a dependency of it —
but per Constitution Principle X, its own scope should still be
milestone-gated internally (e.g., "basic query + result display" before
"visualization," rather than building the whole UI at once).

---

## Out of current roadmap (not planned, not rejected)
- Full multi-agent sub-agent architecture (schema agent / policy agent /
  generation agent split) — noted in earlier design discussion as
  lower priority than the bounded loop; only add a spec for this if
  Milestone 3's simpler loop proves insufficient.
- Production authentication/identity integration.
- Cloud deployment target selection.

Keeping this section explicit is intentional: it documents what was
considered and deliberately deferred, rather than leaving it ambiguous
whether it was forgotten.

---

**Version**: 1.0.0 — 2026-07-23