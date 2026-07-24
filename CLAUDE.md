# Steward

Domain-agnostic, governed natural-language data access platform. Users
ask questions of a database in plain English; every answer stays inside
access boundaries a governance policy has approved — enforced
deterministically, not by trusting the LLM to police itself.

See @constitution.md for governing principles, @roadmap.md for the
milestone sequence and each milestone's definition of done, and
@tech-stack.md for locked technology decisions.

## How to work in this repo

- **This is spec-driven.** No implementation task begins without an
  approved `spec.md` under `specs/<feature-name>/`, followed by
  `plan.md` and `tasks.md`. If you're asked to implement something that
  doesn't have a spec yet, say so and propose running `/speckit.specify`
  first rather than improvising code.
- **Always run `/speckit.analyze` before `/speckit.implement`.** It
  checks `plan.md`/`tasks.md` against `constitution.md`. Report what it
  flags; don't silently proceed past a flagged violation.
- **Respect the milestone gate (Constitution Principle X).** Check
  `roadmap.md` before starting work. Do not begin Milestone 2 (RAG),
  Milestone 3 (agentic loop), or Milestone 4 (MCP) code until the
  current milestone's Definition of Done — full eval suite passing — is
  met. If asked to jump ahead, flag this explicitly rather than complying
  silently.
- **`tech-stack.md` is locked, not a suggestion.** Don't introduce an
  alternative library, framework, or service for anything already
  decided there (e.g., don't swap in a different SQL parser, a different
  orchestration framework, or a different frontend stack) without first
  updating `tech-stack.md` and stating the rationale.

## Non-negotiable engineering rules (see constitution.md for full rationale)

- **Never let the LLM police its own output for security decisions.**
  Any check that determines whether a query is safe to execute (DML
  detection, PII exposure, policy compliance) must be deterministic code
  (e.g., `sqlglot` AST inspection, policy-file lookup) — never an
  LLM-reported flag taken at face value.
- **Fail closed.** Any table or column without an approved policy
  artifact is blocked by default, not allowed by default.
- **No real PII/PHI/financial data, ever.** All test and demo data is
  synthetic (Synthea for healthcare, Faker/PaySim-style generation for
  fintech). Never wire in a real data source, even for "just testing."
- **Every classification and enforcement decision is logged**, with
  enough context to answer "what was asked, what policy applied, what
  was allowed or blocked, and why" after the fact.
- **Any agentic/loop behavior needs an explicit iteration cap, timeout,
  and cost budget defined in its spec before it's implemented.**
  Unbounded retry loops are not acceptable, even if they'd improve
  accuracy.
- **Don't overclaim compliance.** Nothing in this project is a
  certified HIPAA, PCI-DSS, GDPR, or SOX-compliant system. Docs, code
  comments, and UI copy should describe it as demonstrating governance
  *patterns*, not certifying compliance.

## When something seems ambiguous or underspecified

Prefer surfacing the ambiguity and proposing to run `/speckit.clarify`
over guessing and implementing — especially for anything touching policy
enforcement, classification thresholds, or role permissions. Getting
these wrong silently is much more costly here than in a typical project,
since they're the actual product differentiator, not incidental details.

## Useful context for any session

- Two domains are in scope: **healthcare** (synthetic Synthea data) and
  **fintech** (synthetic transaction data). The engine must stay
  domain-agnostic — if you find yourself writing a healthcare- or
  fintech-specific conditional inside engine code (not inside a policy
  artifact), stop and reconsider the design.
- Current milestone: **Milestone 1** — schema classification and policy
  enforcement engine. See `specs/001-schema-classification-policy-engine/spec.md`
  for the full scope, scenarios, and requirements.