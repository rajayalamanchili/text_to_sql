# Quickstart: Validate the Classification & Policy Enforcement Engine

Proves the milestone works end-to-end: classify a domain schema, review a
low-confidence column, publish a policy, and demonstrate deterministic
enforcement overriding an incorrect/malicious query — mirroring the 10
scenarios in `spec.md`.

## Prerequisites

- Docker Compose stack running: 2× Postgres (healthcare, fintech), backend,
  frontend (see `tech-stack.md` → Infrastructure & local development).
- Synthetic data already seeded for both domains (`domains/healthcare/seed.py`,
  `domains/fintech/seed.py`).
- `X-Steward-Role` header available to set on requests (`analyst` or
  `admin`) — no real auth system required at Milestone 1.
- `ANTHROPIC_API_KEY` set in `.env` (see `.env.example`). Without it,
  classification falls back to `NullLLMClient` and most non-keyword
  business columns (e.g. `claim_id`, `claim_date`) stay stuck in
  `pending_review` instead of auto-approving via the LLM-assisted pass —
  see step 3's no-key fallback if you're intentionally running without one.

## Setup

```bash
docker compose up -d
# Wait for both Postgres instances + backend to report healthy.
```

## Scenario walkthrough

Run every command below from the repo root (the directory containing this
`specs/` folder and `./policies`), not from `backend/` — steps 4a and 6
read/write `./policies/<domain>/...` directly and will raise
`FileNotFoundError` from anywhere else.

### 1. Enumerate + classify a domain schema (Scenarios 1–3, 6)

```bash
curl -X POST localhost:8000/domains/healthcare/schema/enumerate
curl -X POST localhost:8000/domains/healthcare/classify
# fintech is classified here too — step 2's review queue and steps 5/6/9's
# fintech/query calls both need it, and step 4 publishes both domains
curl -X POST localhost:8000/domains/fintech/schema/enumerate
curl -X POST localhost:8000/domains/fintech/classify
```

**Expect**: `patient_ssn` classified `pii_direct`, confidence ≥ 0.9, not in
the review queue (Scenario 1). `patient_notes` is NOT auto-classified
`business` (Scenario 3) — check via the review queue or policy output.

Confirm via `GET /domains/{domain}/classifications`:

```bash
curl -s "localhost:8000/domains/healthcare/classifications?table=patients&column=patient_ssn" \
  | python3 -m json.tool
```

**Expect**: one item, `"classification": "pii_direct"`, `"confidence" >= 0.9`,
`"status": "auto_approved"` (not `"pending_review"`).

```bash
curl -s "localhost:8000/domains/healthcare/classifications?table=patients&column=patient_notes" \
  | python3 -m json.tool
```

**Expect**: `"status": "pending_review"` (or any non-`business` classification)
— never an unreviewed `"status": "auto_approved"` with `"classification": "business"`.

### 2. Inspect the human-review queue (Scenario 2)

```bash
curl -H "X-Steward-Role: admin" localhost:8000/domains/fintech/review-queue
```

**Expect**: the fintech `notes` column present with `status: pending_review`
and `confidence < 0.85`.

### 3. Approve as admin, confirm role gate (Scenario 8)

With `ANTHROPIC_API_KEY` set (see Prerequisites), the LLM-assisted pass
should push most plain business columns (`claim_id`, `claim_date`,
`customer_id`, ...) to combined confidence ≥ 0.85 on their own — leaving
only genuinely ambiguous columns, like fintech's `notes` (free text, low
cardinality), actually requiring human review. Confirm the queue is down
to just that kind of column before approving:

```bash
curl -s -H "X-Steward-Role: admin" localhost:8000/domains/fintech/review-queue | python3 -m json.tool
curl -s -H "X-Steward-Role: admin" localhost:8000/domains/healthcare/review-queue | python3 -m json.tool
```

**Expect**: only a small number of genuinely ambiguous columns per domain
(fintech's `notes` among them) — plain business columns like `claim_id`
should already show `auto_approved` in step 1's classification check, not
appear here. If most non-keyword columns are still pending here, the key
likely isn't reaching the backend container — see the no-key fallback below.

Use the `id` of the `notes` item from the response above as `<column_id>`
below.

```bash
# Rejected: analyst cannot approve
curl -X POST -H "X-Steward-Role: analyst" \
  localhost:8000/domains/fintech/review-queue/<column_id>/approve
# expect 403

# Accepted: admin can approve
curl -X POST -H "X-Steward-Role: admin" \
  localhost:8000/domains/fintech/review-queue/<column_id>/approve
# expect 200, reviewed_by set
```

Repeat the approve call for any other item still in either domain's
review queue, then confirm both are empty before step 4:

```bash
curl -s -H "X-Steward-Role: admin" localhost:8000/domains/fintech/review-queue | python3 -m json.tool
curl -s -H "X-Steward-Role: admin" localhost:8000/domains/healthcare/review-queue | python3 -m json.tool
# expect: {"items": []} for both
```

**No-key fallback**: without `ANTHROPIC_API_KEY`, classification falls
back to `NullLLMClient` — every column that doesn't hit a heuristic
name-pattern keyword stays at its heuristic score, below the 0.85
auto-approval bar, and lands in `pending_review`, likely most columns in
both domains. Approving each individually isn't practical at that volume,
and blanket-approving without inspection isn't real review — it's a
demo-only substitute for the LLM-assisted pass, not a stand-in for
Scenario 2's actual human-review guarantee:

```bash
for domain in fintech healthcare; do
  for column_id in $(curl -s -H "X-Steward-Role: admin" "localhost:8000/domains/$domain/review-queue" \
      | python3 -c 'import json,sys; print("\n".join(i["id"] for i in json.load(sys.stdin)["items"]))'); do
    curl -s -X POST -H "X-Steward-Role: admin" \
      "localhost:8000/domains/$domain/review-queue/$column_id/approve" > /dev/null
  done
done
curl -s -H "X-Steward-Role: admin" localhost:8000/domains/fintech/review-queue | python3 -m json.tool
curl -s -H "X-Steward-Role: admin" localhost:8000/domains/healthcare/review-queue | python3 -m json.tool
# expect: {"items": []} for both
```

### 4. Publish the policy artifact (FR-006)

```bash
curl -X POST -H "X-Steward-Role: admin" \
  localhost:8000/domains/healthcare/policy/publish
# fintech too — steps 5/6/9 query fintech and need its policy active
curl -X POST -H "X-Steward-Role: admin" \
  localhost:8000/domains/fintech/policy/publish
```

**Expect**: a new versioned `policies/healthcare/<n>/policy.yaml` and
`policies/fintech/<n>/policy.yaml`, each matching
`contracts/policy-artifact.schema.yaml`'s shape, manifests updated.

### 4a. Manually configure the `diagnosis_code` role gate (Scenario 7 prep)

`/policy/publish` only ever derives two actions from a classification —
`business` → `allow`, everything else → `block` (fail-closed default,
Constitution Principle II). `role_gate` is never auto-derived; it's always
a manual, post-publish edit to the active version's YAML (`tasks.md`
T064). Without this step, `diagnosis_code` publishes as a plain `block`
and step 8 will see `COLUMN_BLOCKED` for both roles instead of the
role-gated behavior it's meant to demonstrate. `PolicyStore` re-reads the
file from disk on every request (no cache), so this takes effect
immediately — no republish needed. Run from the repo root, where
`./policies` is docker-compose-mounted.

The `backend` container runs as root, so files it wrote via step 4's
publish call are root-owned on your host — if the script below fails with
`PermissionError`, reclaim ownership first:

```bash
sudo chown -R $(id -u):$(id -g) policies/
```

```bash
python3 -c '
import yaml
manifest = yaml.safe_load(open("policies/healthcare/manifest.yaml"))
version = manifest["active_version"]
path = f"policies/healthcare/{version}/policy.yaml"
artifact = yaml.safe_load(open(path))
patients = next(t for t in artifact["tables"] if t["table_name"] == "patients")
patients["columns"]["diagnosis_code"]["action"] = "role_gate"
patients["columns"]["diagnosis_code"]["roles"] = ["admin"]
yaml.safe_dump(artifact, open(path, "w"), sort_keys=False)
print(f"updated {path}: diagnosis_code -> role_gate [admin]")
'
```

Verify:

```bash
curl -s localhost:8000/domains/healthcare/policy | python3 -c '
import json, sys
artifact = json.load(sys.stdin)
patients = next(t for t in artifact["tables"] if t["table_name"] == "patients")
col = patients["columns"]["diagnosis_code"]
assert col["action"] == "role_gate", col
assert col["roles"] == ["admin"], col
print("OK:", col)
'
```

### 5. Deterministic guardrail overrides a bad query (Scenario 4)

```bash
curl -X POST -H "X-Steward-Role: analyst" -H "Content-Type: application/json" \
  -d '{"sql": "SELECT member_ssn FROM claims"}' \
  localhost:8000/domains/fintech/query
```

**Expect**: `403`, `reason: "column blocked by policy: member_ssn"` — reject
happens regardless of any LLM self-report (Constitution Principle I).

### 6. Row-level predicate injection (Scenario 5)

Requires the `claims` table's `row_policy_template` to be set first — like
step 4a, this is never auto-derived by `/policy/publish` (see that step's
explanation) and is lost on every republish, so redo this after any
republish of the fintech policy:

```bash
sudo chown -R $(id -u):$(id -g) policies/   # only if step 4's publish left root-owned files
python3 -c '
import yaml
manifest = yaml.safe_load(open("policies/fintech/manifest.yaml"))
version = manifest["active_version"]
path = f"policies/fintech/{version}/policy.yaml"
artifact = yaml.safe_load(open(path))
claims = next(t for t in artifact["tables"] if t["table_name"] == "claims")
claims["row_policy_template"] = "tenant_id = :current_tenant"
yaml.safe_dump(artifact, open(path, "w"), sort_keys=False)
print(f"updated {path}: claims.row_policy_template set")
'
```

A plain `{"question": "show me all claims"}` does NOT work here: `claims`
always has at least one non-`business` column (`member_ssn`, at minimum —
likely also `tenant_id`/`claim_status` under the heuristic/no-key
fallback), so step 3's token-match SQL proposer falls back to `SELECT *`
(no column tokens in the question), which pulls in a blocked column and
gets rejected `COLUMN_BLOCKED` before row-policy injection is even
relevant. Reference only `business`-classified columns instead — exactly
like the row-policy BDD test does — to isolate the row-policy behavior
from column-block enforcement:

```bash
curl -X POST -H "X-Steward-Role: analyst" -H "X-Steward-Tenant: tenant-001" \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT claim_id, claim_amount, claim_date, customer_id FROM claims"}' \
  localhost:8000/domains/fintech/query
```

**Expect**: `200`, rows returned. The submitted SQL never mentions
`tenant_id`, yet the row count differs from the same query run with
`X-Steward-Tenant: tenant-002` — confirming the `tenant_id =
:current_tenant` predicate was injected and scoped the results. Omitting
`X-Steward-Tenant` entirely on this same query is expected to fail closed:

```bash
curl -X POST -H "X-Steward-Role: analyst" -H "Content-Type: application/json" \
  -d '{"sql": "SELECT claim_id, claim_amount, claim_date, customer_id FROM claims"}' \
  localhost:8000/domains/fintech/query
# expect 403, reason_code: ENFORCEMENT_ERROR
```

### 7. Unclassified schema defaults closed (Scenario 6)

```bash
curl -X POST -H "X-Steward-Role: analyst" -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM new_unclassified_table"}' \
  localhost:8000/domains/healthcare/query
```

**Expect**: `403`, `reason: "schema not yet classified"`.

### 8. Role-gated column (Scenario 7)

Requires step 4a's manual role-gate edit to be in place first.

```bash
# Rejected: analyst lacks the gated role
curl -X POST -H "X-Steward-Role: analyst" -H "Content-Type: application/json" \
  -d '{"sql": "SELECT diagnosis_code FROM patients"}' \
  localhost:8000/domains/healthcare/query
# expect 403, reason: "column requires role: admin"

# Succeeds: admin has the gated role
curl -X POST -H "X-Steward-Role: admin" -H "Content-Type: application/json" \
  -d '{"sql": "SELECT diagnosis_code FROM patients"}' \
  localhost:8000/domains/healthcare/query
# expect 200
```

### 9. DML statement rejected unconditionally (Scenario 9)

```bash
curl -X POST -H "X-Steward-Role: analyst" -H "Content-Type: application/json" \
  -d '{"sql": "DELETE FROM transactions WHERE id = 1"}' \
  localhost:8000/domains/fintech/query
```

**Expect**: `403`, `reason: "DML statement rejected: read-only queries only"`
— rejected purely on the parsed statement's AST type, before any column/table
policy lookup runs (Constitution Principle I).

### 10. Irrelevant question does not leak schema (Scenario 10)

```bash
curl -X POST -H "X-Steward-Role: analyst" -H "Content-Type: application/json" \
  -d '{"question": "what is the weather today?"}' \
  localhost:8000/domains/healthcare/query
```

**Expect**: `200`, `reason: "question not mapped to schema"` — no SQL is
generated or executed, and no policy-blocked table/column names appear in
the response.

### 11. Query the audit log (NFR-004)

```bash
curl -H "X-Steward-Role: admin" \
  "localhost:8000/audit-log?domain=fintech&decision=block"
```

**Expect**: entries for every block/allow/classify decision produced by the
steps above, filterable by domain, time range, and decision type without any
log-scraping.

## Automated validation (required before this milestone is done)

Run from `backend/` (its `.venv` has the project's dependencies; the repo
root has none installed). `pytest` has no `--bdd` flag — the BDD scenarios
under `tests/integration` collect automatically via each test module's
`scenarios(...)` call, so a plain `pytest tests/integration` run already
includes them. Both eval commands also need the domain database URLs
exported — pointed at the docker-compose Postgres instances' host-mapped
ports (`5432` healthcare, `5433` fintech; see `docker-compose.yml`), not
the in-container `HEALTHCARE_DATABASE_URL`/`FINTECH_DATABASE_URL` values
from `.env`, which resolve container hostnames (`healthcare-db`,
`fintech-db`) unreachable from the host:

```bash
set -a; source ../.env; set +a
export HEALTHCARE_DATABASE_URL="postgresql://${HEALTHCARE_DB_USER}:${HEALTHCARE_DB_PASSWORD}@localhost:${HEALTHCARE_DB_PORT}/${HEALTHCARE_DB_NAME}"
export FINTECH_DATABASE_URL="postgresql://${FINTECH_DB_USER}:${FINTECH_DB_PASSWORD}@localhost:${FINTECH_DB_PORT}/${FINTECH_DB_NAME}"
cd backend

# Behavioral scenarios — executes spec.md's 10 Given/When/Then scenarios,
# plus additional edge-case scenarios per feature file, directly
.venv/bin/pytest tests/integration -q

# Classifier precision/recall against hand-labeled ground truth (both domains)
.venv/bin/python eval/classifier_eval.py --domain healthcare
.venv/bin/python eval/classifier_eval.py --domain fintech
```

**Expect**: all scenarios pass (16 as of this writing — 10 from spec.md
plus edge cases for Scenarios 5, 7, 8, 11); precision/recall on
`pii_direct` ≥ 0.85 each, per domain (spec Success Criteria). These BDD
runs republish both domains' policies as part of their own `Given` steps,
which advances `active_version` past whatever step 4/6/4a left active —
redo steps 4a/6's manual edits against the new active version if you want
to keep demonstrating those scenarios manually afterward.
