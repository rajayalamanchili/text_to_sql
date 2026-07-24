# Research: Schema Classification & Policy Enforcement Engine

All cross-feature technology choices (language, frameworks, DB, testing
stack) are already locked in `tech-stack.md` and are not re-litigated here.
This document resolves the feature-specific design questions the spec leaves
open (the "how", where the spec defines the "what").

## 1. Heuristic classification signals (FR-002)

- **Decision**: Combine three weighted signals into a heuristic score per
  column: (a) name-pattern match against a curated, per-category
  keyword/regex dictionary (e.g. `ssn|social_security` → `pii_direct`;
  `email|phone|address|zip` → `pii_indirect`; `diagnosis|icd|cpt|account_number|balance` →
  `sensitive_category`); (b) data type (string/text vs. numeric/date); (c)
  cardinality ratio (`distinct_count / row_count`) — near-1.0 uniqueness on a
  string column is a strong `pii_direct` signal (Scenario 1). Heuristic
  confidence is capped at 0.95 so heuristics alone never claim absolute
  certainty, leaving room for the LLM pass or human review to override.
- **Rationale**: The dictionary and thresholds live in a config file
  consulted by generic engine code, not per-domain conditionals — required
  by Constitution Principle IV.
- **Alternatives considered**: A trained ML classifier (rejected — no
  labeled training corpus exists yet at Milestone 1, disproportionate
  complexity); pure regex without cardinality/type signals (rejected — fails
  Scenario 3, since an adversarially-named free-text column may not match
  any keyword).

## 2. Free-text / adversarial column default (Scenario 3)

- **Decision**: Any string/text column that (a) does not confidently match a
  dictionary term and (b) has type/cardinality signals consistent with
  free-text narrative (large max length, low pattern repetition) is
  heuristically capped at confidence ≤ 0.6 and defaulted to
  `sensitive_category` — **never** `business` — pending the LLM pass or human
  review.
- **Rationale**: Directly implements Constitution Principle II's fail-closed
  default at the heuristic layer itself, not only at the enforcement layer;
  matches Scenario 3's explicit requirement that unknown free text is never
  silently classified safe.

## 3. LLM-assisted pass input masking (FR-003)

- **Decision**: When triggered (heuristic confidence below threshold), the
  LLM prompt receives only: column name, inferred data type, cardinality
  ratio, a bucketed value-length distribution (min/max/avg character length),
  and regex-generalized pattern classes derived from sample values (e.g. a
  column of digit strings is described as matching `\d{3}-\d{2}-\d{4}`, not
  shown any actual digits). The LLM returns a proposed classification,
  confidence, and a rationale string — the rationale is stored for audit
  purposes only and is never treated as an enforcement input (Constitution
  Principle I).
- **Alternatives considered**: Sending ad hoc redacted raw samples (rejected
  — redaction bugs are precisely the leak class this system exists to
  prevent); sending only the column name with no statistical signal
  (rejected — materially weaker than heuristics alone).

## 4. Combining heuristic + LLM confidence (FR-002, FR-003, FR-005)

- **Decision**:
  - If the heuristic pass alone clears the 0.85 threshold, the LLM pass is
    skipped; combined classification/confidence = heuristic's.
  - If the LLM pass runs and its proposed category **agrees** with the
    heuristic's, combined confidence = `max(heuristic, llm)`.
  - If the two **disagree** on category, the more sensitive category always
    wins regardless of either confidence score, using the fixed risk order
    `business < pii_indirect < sensitive_category < pii_direct` (an
    `unclassified` proposal from either pass is never used as the winner),
    and combined confidence = `min(heuristic, llm)` — biasing toward review,
    not auto-approval.
- **Rationale**: Simple, fully auditable rule that never lets an
  optimistic/wrong pass silently outvote a conservative one — directly
  implements Constitution Principle II/III and FR-005's stated intent that
  Milestone 1 favors manual review over risky auto-approval.
- **Alternatives considered**: A learned/weighted ensemble (rejected —
  unjustifiable complexity and non-auditability for a milestone whose
  explicit goal is conservative, explainable behavior).

## 5. Deterministic SQL enforcement (FR-007, FR-008, FR-009, FR-014, Scenarios 4–7, 9–10)

- **Decision**: Every candidate query is parsed into a `sqlglot` AST
  (dialect matched to the target domain's Postgres). The enforcement node:
  1. Checks the parsed AST's root statement type first: anything other than
     `SELECT` (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`,
     etc.) is rejected immediately with reason `"DML statement rejected:
     read-only queries only"` — before any column/table policy lookup runs
     (FR-014, Scenario 9). This check is purely structural (AST node type),
     never based on anything the LLM reports about its own query.
  2. Resolves every column reference to a concrete `table.column`, expanding
     `SELECT *`, joins, CTEs, and subqueries using the schema metadata
     captured at enumeration time (FR-001) — never by asking the LLM what
     columns it used.
  3. Looks up each resolved `table.column` in the domain's active policy
     artifact; rejects the whole query on `block`, rejects or filters on
     `role_gate` if the caller's role (from the auth stub) isn't listed,
     passes through on `allow`.
  4. For every referenced table carrying a `row_policy_template`, injects the
     templated predicate (e.g. `tenant_id = :current_tenant`) into the
     query's `WHERE` clause via AST manipulation (creating the clause if
     absent) — never string concatenation, to avoid injection-adjacent bugs
     in the guardrail itself.
  5. Any column or table that cannot be resolved to a known, policy-covered
     entity causes the whole query to be rejected outright (default closed,
     FR-009/Scenario 6).
  - Separately, the SQL proposal step (upstream of enforcement) returns "question
    not mapped to schema" without ever invoking SQL generation or execution
    when the question references no known table/column — so an irrelevant
    question never reaches the database and never reveals policy-blocked
    schema details (FR-014, Scenario 10).
- **Rationale**: This is the mechanism that satisfies Constitution Principle
  I — a real, testable, AST-level check replaces the prior prototype's
  LLM-self-report flaw named in the constitution's rationale.
- **Alternatives considered**: Regex-based SQL inspection (rejected —
  fragile against the exact adversarial cases, e.g. subqueries/aliases,
  Scenario 4 is meant to cover); trusting an LLM-reported list of columns
  used (explicitly rejected by Constitution Principle I itself).

## 6. Policy artifact resolution (FR-006, FR-007)

- **Decision**: Policy artifacts live at
  `policies/<domain>/<version>/policy.yaml` (git-versioned, per
  `tech-stack.md`). Each domain has a `policies/<domain>/manifest.yaml`
  pointing at the currently-active version, giving "the active policy
  artifact for a domain" (FR-007) a single deterministic resolution path
  with no ambiguity about which version is live.
- **Alternatives considered**: A `current` symlink (rejected — less
  portable across OSes and harder to diff/review in a PR than an explicit
  manifest file).

## 7. Role auth stub (FR-008)

- **Decision**: Caller role is supplied via an `X-Steward-Role` request
  header, validated against the fixed enum `{analyst, admin}`. A FastAPI
  dependency parses it into a typed `Caller` object. A missing or invalid
  header defaults to `analyst` (the more restrictive role, no
  review-approval rights) — fail closed, consistent with Principle II
  applied to auth as well as data.
- **Alternatives considered**: Defaulting an absent header to `admin`
  (rejected outright — violates fail-closed default).

## 8. Audit log shape and querying (FR-010, NFR-004)

- **Decision**: A single Postgres table,
  `audit_log(id, timestamp, domain, query_id, actor_role, decision, reason,
  policy_version_used, raw_query_hash)`, populated by `structlog`-emitted
  structured events at both the classification and enforcement decision
  points. A thin FastAPI `GET /audit-log` endpoint filters by domain, time
  range, and decision type directly via SQL — satisfying NFR-004 without a
  bespoke log-query system.
- **Alternatives considered**: File-based JSON logs only (rejected — not
  queryable without log-scraping, which NFR-004 explicitly rules out).

## 9. LangGraph graph shape

- **Decision**: Two separate, small graphs rather than one combined graph,
  mirroring the spec's two temporally distinct pipelines:
  - **Classification graph**: `enumerate_schema → heuristic_classify →
    [confidence gate] → llm_classify (conditional) → persist_pending_or_active`.
  - **Query graph**: `generate_sql (LLM proposal) → deterministic_enforce
    (sqlglot check + predicate injection) → execute (only if enforcement
    passes) → audit_log`.
- **Rationale**: Keeps the deterministic enforcement node as a single,
  isolated, independently testable graph node (Principle I), and keeps
  "classify before you generate" (Principle II) as two genuinely separate
  pipelines rather than steps inside one entangled graph.
- **Alternatives considered**: One unified graph with a branch for
  classification vs. query (rejected — blurs the two concerns the
  constitution treats as distinct, and complicates testing the enforcement
  node in isolation).

## 10. Two-domain synthetic data generation (FR-011, FR-012)

- **Decision**: Healthcare domain schema/data loaded from a Synthea
  CSV/FHIR export into Postgres via `domains/healthcare/seed.py`, using
  Synthea's canonical table/column names (`patients`, `encounters`,
  `conditions`, etc.). Fintech domain schema is hand-designed
  (`accounts`, `transactions`, `customers`) and populated by
  `domains/fintech/seed.py` using Faker plus a PaySim-style transaction
  pattern generator. Both live under `domains/<domain>/` as data/config only
  — no engine code path branches on which domain is active.
- **Alternatives considered**: Hand-crafting both domains' data with Faker
  only (rejected — Synthea's realistic healthcare structure is exactly what
  makes Scenario 1/3 meaningful test cases; a purely synthetic Faker schema
  wouldn't exercise the same adversarial-naming realism).

**Output**: All `NEEDS CLARIFICATION` items are resolved above. No open
unknowns remain blocking Phase 1 design.
