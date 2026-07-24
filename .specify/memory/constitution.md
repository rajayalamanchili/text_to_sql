# Project Constitution

**Project**: Steward — Governed, Domain-Agnostic Natural-Language Data Access
**Status**: Ratified for Milestone 1
**Last amended**: 2026-07-22

## Purpose

This document defines the non-negotiable principles governing **Steward**,
a platform that lets non-technical users ask questions of a database in
plain English while every answer stays inside the access boundaries a
data governance team has approved.
Every `spec.md`, `plan.md`, and `tasks.md` produced for any feature must be
checked against these principles before implementation begins. Where a
plan conflicts with a principle below, the plan must change — not the
principle — unless this document is explicitly amended first, with a
recorded rationale.

---

## Core Principles

### I. Deterministic Enforcement Over LLM Self-Policing
Any decision that affects data exposure, security, or compliance MUST be
enforced by deterministic, testable code — never by trusting an LLM's own
report about itself (e.g., an LLM stating a query "is safe" or "is not a
DML statement"). LLMs may *propose*; only non-LLM code may *approve*.

**Rationale**: LLMs are probabilistic and can be manipulated, hallucinate,
or simply be wrong under distribution shift. A governance system that
relies on a model grading its own homework has no real guardrail — it has
a suggestion. This is the single most important principle in this
project and directly corrects the design flaw identified in the prior
prototype, where DML-blocking relied on a self-reported LLM flag.

### II. Classify Before You Generate
No schema, table, or column may be exposed to an LLM prompt until it has
been run through the sensitivity classification pipeline and has an
assigned classification with an associated confidence score. Unclassified
columns default to **blocked**, never to **allowed**.

**Rationale**: A domain-agnostic system, by definition, encounters schemas
it has never seen. The default behavior under uncertainty must fail
closed, not fail open.

### III. Human Review Is a First-Class State, Not a Gap
Any classification below the confidence threshold defined in the
classifier spec MUST route to an explicit human-review queue before its
governing policy is considered active. The system MUST NOT claim or
imply full unattended automation of sensitivity classification.

**Rationale**: Overclaiming automated compliance is both dishonest and a
real risk if the project is ever evaluated as more than a portfolio
piece. A documented human-in-the-loop step is a feature, not an
admission of weakness.

### IV. One Engine, Many Policies
The enforcement engine (classification pipeline, policy loader, query
guardrails, audit logging) MUST be domain-agnostic. All domain-specific
knowledge (which columns are sensitive, what row-level predicates apply,
what business glossary terms mean) MUST live in versioned, external
policy artifacts — never hardcoded into the engine's source.

**Rationale**: This is what separates a platform from a script. Adding a
third domain must require writing a new policy file, not new engine code.

### V. Spec Before Code
No implementation task begins without an approved `spec.md` for that
feature, followed by `plan.md` and `tasks.md`. Every `plan.md` MUST
include an explicit Constitution Check section confirming alignment with
this document before `/speckit.tasks` is run.

**Rationale**: Traceability from requirement to enforcement is itself
part of the product's value proposition in a regulated-data context.

### VI. Evaluation Is a Merge Gate, Not a Nice-to-Have
No feature or milestone is considered complete until its associated
evaluation suite passes, including:
- Classifier precision/recall against hand-labeled ground truth, per domain.
- Behavioral scenario tests (Gherkin-style) covering relevant, irrelevant,
  DML-attempt, and policy-boundary questions.
- Regression checks confirming prior milestones' eval suites still pass.

**Rationale**: Without this gate, the eval suite is the first thing
sacrificed under time pressure — and it is the single artifact that
proves the system works, as opposed to appearing to work.

### VII. Synthetic Data, Honest Claims
This project MUST NOT use real PII, PHI, or real financial account data
at any stage. All datasets are synthetic (e.g., Synthea for healthcare,
Faker/PaySim-style generation for fintech). All project documentation
MUST state plainly that this system demonstrates governance *patterns*
and is not a certified HIPAA, PCI-DSS, GDPR, or SOX-compliant product.

**Rationale**: Credibility depends on not overclaiming regulatory status
that has not been audited or certified.

### VIII. Observability and Auditability by Default
Every classification decision, policy enforcement action (block, mask,
allow), and executed query MUST be logged with enough context to answer,
after the fact: what was asked, what policy applied, what was allowed or
blocked, and why. Logs are a required output of every feature that
touches data, not an optional add-on.

**Rationale**: In a regulated-data product, "we can't tell you why that
query was allowed" is itself a failure, independent of whether the
underlying decision was correct.

### IX. Bounded Autonomy
Any agentic behavior — retry loops, tool-use loops, multi-step
self-correction — MUST operate within an explicit, spec-defined iteration
cap, timeout, and cost/token budget. Unconstrained loops are prohibited
regardless of the accuracy gains they might offer.

**Rationale**: Autonomy without a budget is a cost and security liability,
not a capability. This principle governs the platform's approach to
agentic and harness/loop design introduced in later milestones.

### X. Milestones Are Sequential and Individually Complete
New capability layers (schema-retrieval RAG, agentic self-correction
loops, MCP exposure) MUST NOT begin implementation until the current
milestone's full evaluation suite is passing. Each milestone must be a
complete, demo-able, independently defensible system at the point work
stops.

**Rationale**: Parallel, partially-integrated feature development creates
combinatorial debugging risk and risks abandoning the evaluation suite —
the project's core differentiator — under time pressure.

---

## Governance

- This constitution supersedes informal preferences expressed in any
  individual `spec.md` or `plan.md`.
- `tech-stack.md` records the project's cross-feature technology
  decisions. Every `/speckit.plan` MUST be consistent with it; a plan
  that deviates without first amending `tech-stack.md` fails the
  Constitution Check.
- `roadmap.md` records the milestone sequence and each milestone's
  definition of done. Per Principle X, no feature belonging to a later
  milestone may begin implementation until the current milestone's
  definition of done, as recorded there, is met.
- Amendments require: a written rationale, an updated version note below,
  and re-verification that all in-flight `plan.md` documents still comply.
- `/speckit.analyze` MUST be run before `/speckit.implement` for every
  feature, and any flagged constitutional violation MUST be resolved
  before implementation proceeds.

**Version**: 1.0.0 — Ratified 2026-07-22