# Steward

Domain-agnostic, governed natural-language data access platform. Users ask
questions of a database in plain English; every answer stays inside access
boundaries a governance policy has approved — enforced deterministically
against the parsed SQL's AST, not by trusting an LLM to police its own
output.

**Status**: Milestone 1 (schema classification & policy enforcement engine)
— in progress. See `roadmap.md` for the full milestone sequence.

## Start here

| Doc | What it's for |
|---|---|
| [`constitution.md`](constitution.md) | Governing engineering principles (deterministic enforcement, fail-closed defaults, evaluation-as-merge-gate, ...) |
| [`roadmap.md`](roadmap.md) | Milestone sequence and each milestone's definition of done |
| [`tech-stack.md`](tech-stack.md) | Locked technology decisions — don't introduce an alternative without amending this file |
| [`CLAUDE.md`](CLAUDE.md) | How to work in this repo (spec-driven workflow, non-negotiable engineering rules) |
| [`specs/001-schema-classification-policy-engine/spec.md`](specs/001-schema-classification-policy-engine/spec.md) | Current milestone's scope, behavioral scenarios, and requirements |
| [`specs/001-schema-classification-policy-engine/quickstart.md`](specs/001-schema-classification-policy-engine/quickstart.md) | Hands-on walkthrough of every scenario against a running stack |

## Quickstart

```bash
cp .env.example .env   # fill in local-only Postgres credentials; docker
                        # compose refuses to start without them
docker compose up -d   # 2x Postgres (healthcare, fintech), backend, frontend
```

Backend API: `http://localhost:8000` (OpenAPI docs at `/docs`).
Frontend: `http://localhost:3000` (admin review queue at `/admin-review`).

Then walk through
[`specs/001-schema-classification-policy-engine/quickstart.md`](specs/001-schema-classification-policy-engine/quickstart.md)
to classify a schema, review a low-confidence column, publish a policy, and
see deterministic enforcement override a bad query end to end.

An `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) is optional — without one,
the LLM-assisted classification pass is skipped and columns fall back
conservatively to human review rather than being silently auto-approved
(`backend/src/services/classification/anthropic_client.py`).

## Local development

Backend (from `backend/`, requires [`uv`](https://docs.astral.sh/uv/)):

```bash
uv sync                    # install dependencies
uv run pytest tests/unit   # fast, no external services required
uv run pytest tests/integration  # pytest-bdd scenario suite; needs the
                                  # docker compose stack running (skips,
                                  # not fails, if the domain DBs aren't
                                  # reachable — see tests/integration/conftest.py)
uv run ruff check .        # lint
uv run ruff format .       # format
```

Classifier precision/recall eval against hand-labeled ground truth (from the
repo root, needs the docker compose stack running):

```bash
python backend/eval/classifier_eval.py --domain healthcare
python backend/eval/classifier_eval.py --domain fintech
```

Frontend (from `frontend/`):

```bash
npm install
npm run dev     # http://localhost:3000
npm run lint
npm run format:check
```

## Repository layout

```text
backend/     FastAPI engine — classification pipeline, policy store,
             deterministic SQL enforcement (sqlglot), LangGraph orchestration
frontend/    Next.js — the Milestone 1 admin review UI (frontend/src/app/admin-review)
domains/     Per-domain config + synthetic data generation (healthcare, fintech) —
             no engine logic; see tech-stack.md for why healthcare uses a
             Python-native Synthea-style generator instead of the real tool
policies/    Versioned, git-diffable YAML policy artifacts, one dir per domain
specs/       Spec-driven feature work: spec.md -> plan.md -> tasks.md per feature
```

Full structure and rationale: `specs/001-schema-classification-policy-engine/plan.md`
→ Project Structure.

## Working in this repo

This project is spec-driven (see `CLAUDE.md`): implementation work is scoped
by an approved `spec.md` under `specs/<feature-name>/`, followed by `plan.md`
and `tasks.md`. Check `roadmap.md`'s milestone gate before starting anything
outside the current milestone's scope.
