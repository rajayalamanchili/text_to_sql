# Security & Policy Enforcement Checklist: Schema Sensitivity Classification & Policy Enforcement Engine

**Purpose**: Pre-implementation requirements-quality gate for the policy
enforcement / security surface of Milestone 1 — deterministic enforcement,
fail-closed defaults, DML rejection, role-gating, and row-level policy
injection (Constitution Principle I). Intended to be run before
`/speckit.analyze` and `/speckit.implement`, by the feature author or a
reviewer, to surface ambiguity/gaps in `spec.md`, `plan.md`, and
`contracts/` while they are still cheap to fix.
**Created**: 2026-07-24
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [contracts/api.md](../contracts/api.md) · [contracts/policy-artifact.schema.yaml](../contracts/policy-artifact.schema.yaml)

**Note**: This checklist tests whether the *requirements* for policy
enforcement are complete, clear, consistent, and measurable — not whether
any implementation of them works. Items are phrased as questions about the
spec/plan/contracts, not as test steps against running code.

## Requirement Completeness

- [x] CHK001 Is a requirement defined for enforcement behavior when the active policy artifact fails to load (missing file, corrupt YAML, schema-validation failure) — not merely "no policy exists for this column"? [Gap, Spec §FR-007]
  - Resolved 2026-07-24: FR-007 now mandates fail-closed with reason `enforcement_error` (Clarifications, Session 2026-07-24).
- [x] CHK002 Is a requirement defined for what happens when the policy enforcement component itself raises an unexpected error (a bug, not a policy violation) — is fail-closed the mandated behavior there too, or is this left to implementation discretion? [Gap, Spec §FR-007, Constitution Principle II]
  - Resolved 2026-07-24: same FR-007 update covers internal errors uniformly with policy-load failures.
- [x] CHK003 Are requirements defined for multi-statement input (e.g., a stacked `SELECT ...; DROP TABLE ...;` payload) rather than only single-statement DML/SELECT classification? [Gap, Spec §FR-014, Scenario 9]
  - Resolved 2026-07-24: FR-014 now rejects any multi-statement input unconditionally, reason `MULTIPLE_STATEMENTS_REJECTED`.
- [ ] CHK004 Is there a requirement covering how `current_tenant` (used in row-policy predicate injection) is resolved from the caller/auth stub, and what happens if it is absent or malformed for a domain whose policy requires it? [Gap, Spec §FR-008, Key Entities: Caller]
- [ ] CHK005 Is a requirement defined for the caller's role being present but unrecognized (neither `analyst` nor `admin`) in the auth-stub header, as distinct from the role being absent? [Gap, Spec §FR-008]
- [x] CHK006 Is there a requirement establishing an overall enforcement pipeline order (e.g., DML/read-only check → schema-mapping check → default-closed/no-policy check → column policy check → role-gate check → row-policy injection) so precedence is unambiguous across scenarios, rather than only implied by per-scenario examples? [Gap, Spec §FR-007, FR-008, FR-009, FR-014]
  - Resolved 2026-07-24: FR-014 keeps DML/schema-mapping structurally first; FR-007 defines a severity ranking (not scan order) for column/table-level violations (Clarifications, Session 2026-07-24).

## Requirement Clarity

- [ ] CHK007 Is "active policy artifact" (FR-007) defined precisely enough to resolve which version is active when multiple approved policy versions exist for a domain (e.g., latest vs. an explicit rollback target)? [Clarity, Spec §FR-007]
- [x] CHK008 Are the audit-log "reason" strings (e.g., "column blocked by policy: member_ssn", "schema not yet classified", "DML statement rejected: read-only queries only") specified as a fixed, enumerable reason-code scheme, or only as illustrative example text per scenario? [Clarity, Spec §FR-010, Scenarios 4/6/9/10]
  - Resolved 2026-07-24: FR-010 and Key Entities now mandate a fixed reason-code enum (Clarifications, Session 2026-07-24).
- [ ] CHK009 Is "cannot be mapped to any table in the domain's active policy" (FR-014, Scenario 10) defined with enough precision to be testable, given that SQL-generation/mapping quality is explicitly out of scope for this milestone? [Ambiguity, Spec §FR-014, Out of Scope]
- [ ] CHK010 Is the row-policy template's placeholder syntax (e.g., `:current_tenant` in `tenant_id = :current_tenant`) formally specified — allowed placeholder names, escaping rules, and injection point (WHERE-clause AST vs. string substitution)? [Clarity, Spec §Key Entities: Policy Artifact, Scenario 5]

## Requirement Consistency

- [x] CHK011 Do FR-008's `on_role_mismatch: reject | exclude` default and FR-009's default-closed rule agree on precedence when a query touches both a no-policy column and a role-gated column in the same statement? [Consistency, Spec §FR-008, FR-009]
  - Resolved 2026-07-24: severity ranking in FR-007 (no-active-policy/`block`/`enforcement_error` rank above `role_gate`) resolves this precedence.
- [ ] CHK012 Is the response contract for enforcement rejections (HTTP status, error body shape) consistent across Scenarios 4, 6, 7, 9, and 10, or does each imply a different shape without a unifying requirement? [Consistency, Spec §FR-007–FR-009, FR-014, contracts/api.md]
- [ ] CHK013 Are "block" (column-level, FR-008) and "reject the whole query" (query-level, FR-009/on_role_mismatch=reject) kept terminologically distinct in the requirements, so a reader can't conflate a column-scoped decision with a query-scoped decision? [Consistency, Spec §FR-008, FR-009]
- [ ] CHK014 Does the Success Criteria's "all ten behavioral scenarios pass" requirement align with FR-014's two independent guarantees (DML rejection AND irrelevant-question handling), or could a plan satisfy one half while leaving the other under-specified? [Consistency, Spec §Success Criteria, FR-014]

## Acceptance Criteria Quality / Measurability

- [ ] CHK015 Is NFR-002's "≤200ms" enforcement-latency budget defined with a measurement methodology (percentile, load condition, query complexity assumed) sufficient to make pass/fail objective? [Measurability, Spec §NFR-002]
- [ ] CHK016 Can "deterministically evaluates every generated SQL query" (FR-007) be objectively verified, or does it require an implicit definition of "every" (e.g., does it include queries generated by a future retry loop, out of scope here, or only the single-shot path)? [Measurability, Spec §FR-007]
- [ ] CHK017 Is there a measurable acceptance bar for the row-policy injection guarantee in Scenario 5 (e.g., "cannot return rows outside the caller's tenant") beyond the single illustrative example — does it specify how this is verified for arbitrary query shapes (joins, subqueries, CTEs)? [Measurability, Spec §Scenario 5]

## Scenario Coverage / Edge Case Coverage

- [x] CHK018 Are requirements defined for a query where the LLM-generated SQL already contains its own (possibly conflicting or incorrect) tenant predicate — is override-vs-AND-merge behavior specified? [Edge Case, Gap, Spec §Scenario 5]
  - Resolved 2026-07-24: Scenario 5 and the Clarifications session now specify AST-level AND-merge, never overwrite.
- [ ] CHK019 Are requirements defined for a role-gated column referenced only inside an aggregate/computed expression (e.g., `COUNT(diagnosis_code)`) under `on_role_mismatch: exclude`, where dropping the raw column changes the semantics of the aggregate? [Edge Case, Gap, Spec §FR-008, Scenario 7]
- [ ] CHK020 Are requirements defined for a schema that is *partially* classified (some columns approved, others still `pending_review`) — is the default-closed rule (FR-009/Scenario 6) applied at column granularity within an otherwise-active policy, not only at whole-schema granularity? [Coverage, Gap, Spec §FR-009, Scenario 6]
- [ ] CHK021 Are requirements defined for enforcement behavior when a policy publish (admin action) occurs concurrently with an in-flight query evaluation — is a query pinned to one policy version for its full evaluation, or could it see a partial update? [Coverage, Gap, Spec §FR-006, FR-007]
- [ ] CHK022 Beyond the ten named scenarios, does the spec require any adversarial/fuzz-style negative testing of the enforcement path (malformed SQL, deeply nested subqueries, non-ASCII identifiers) commensurate with Constitution Principle I calling this the project's core differentiator? [Coverage, Gap, Spec §Success Criteria, Constitution Principle I]
- [ ] CHK023 Is column resolution scope (FR-007/research.md §5) required to cover columns referenced only within CTEs, subqueries, or `SELECT *` expansions — not just top-level `SELECT` list columns — for both the no-policy default-closed check and the role-gate check? [Coverage, Spec §FR-007, FR-009]

## Non-Functional Requirements

- [ ] CHK024 Is a requirement defined for what enforcement should do if the deterministic check cannot complete within the NFR-002 latency budget (timeout behavior) — fail closed, or is this undefined? [Gap, Spec §NFR-002]
- [ ] CHK025 Are audit-log completeness requirements (NFR-004, FR-010) explicit that *every* enforcement rejection path (including FR-014's DML and irrelevant-question paths, added later than the original FR-007/FR-009/FR-010 trio) must produce a log entry, or could a newer rejection path be exempt by omission? [Consistency, Gap, Spec §NFR-004, FR-010, FR-014]

## Dependencies & Assumptions

- [ ] CHK026 Is the assumption that the auth-stub role header is always trustworthy (never spoofable within Milestone 1's scope) explicitly documented, given that role-gating (FR-008) and review-approval authority (FR-013) both depend on it? [Assumption, Spec §FR-008, FR-013]
- [ ] CHK027 Is the dependency of row-policy injection (Scenario 5) on the `Caller`/`Domain` concepts (data-model.md, not persisted per spec.md Key Entities) made explicit in `spec.md` itself, or only cross-referenced indirectly? [Dependency, Spec §Key Entities]

## Ambiguities & Conflicts

- [ ] CHK028 Does "the rejection does NOT depend on the LLM having correctly self-reported anything" (Scenario 4) leave any ambiguity about what non-LLM-derived signals (if any) the enforcement node IS permitted to use, beyond the parsed SQL AST and the policy artifact? [Ambiguity, Spec §Scenario 4, Constitution Principle I]
- [x] CHK029 Is there a conflict between FR-008's default role-gate behavior (`reject`, whole query fails) and Scenario 7's phrasing ("the query is rejected (or the column is silently excluded... per FR-008 configuration)") that could lead a reader to treat `exclude` as equally default rather than an explicit opt-in? [Conflict, Ambiguity, Spec §FR-008, Scenario 7]
  - Resolved 2026-07-24: the FR-007 severity-ranking clarification reaffirms `role_gate` mismatch defaults to `reject`, ranked below outright `block`/no-policy, not equal to `exclude`.

## Notes

- Check items off as completed: `[x]`
- Add findings inline as sub-bullets under the relevant item when discussed with the author.
- This checklist focuses on the **policy enforcement & security** surface only; classification/human-review requirement quality, and full-spec/audit-observability coverage, are candidates for separate checklists (e.g., `classification.md`, `observability.md`).
