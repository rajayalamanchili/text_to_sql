"""FastAPI app skeleton (plan.md Project Structure).

Domain-specific routers (schema, classify, review_queue, policy, query,
audit) are added here via `app.include_router(...)` as their own tasks
build them — none exist yet at this stage.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api import classify, policy, query, review_queue, schema
from src.api.deps import AdminRoleRequiredError
from src.services.audit.audit_log import configure_logging

configure_logging()

app = FastAPI(
    title="Steward — Schema Classification & Policy Enforcement Engine",
    description=(
        "Milestone 1 of Steward: classify schema sensitivity, route "
        "low-confidence columns to human review, and deterministically "
        "enforce the resulting policy at query time. Demonstrates "
        "governance patterns — not a certified HIPAA/PCI-DSS/GDPR/SOX-"
        "compliant system (Constitution Principle VII)."
    ),
    version="0.1.0",
)

_allowed_origins = [
    origin.strip()
    for origin in os.environ.get("STEWARD_CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AdminRoleRequiredError)
async def handle_admin_role_required(request: Request, exc: AdminRoleRequiredError) -> JSONResponse:
    del request
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(schema.router)
app.include_router(classify.router)
app.include_router(review_queue.router)
app.include_router(policy.router)
app.include_router(query.router)

# Remaining domain routers are registered below as their tasks land, e.g.:
#     from src.api import audit
#     ...
