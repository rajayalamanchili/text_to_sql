"""Auth-stub FastAPI dependency (FR-008, data-model.md#Caller, research.md §7).

Milestone 1 uses a request-header stub, not real identity/auth: the
caller's role and tenant come from `X-Steward-Role`/`X-Steward-Tenant`,
assumed trustworthy and unspoofed for this milestone (spec.md
"Out of Scope") — no signature/session/identity-provider verification
guards them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from src.config.domains import DomainConfig, UnknownDomainError, get_domain
from src.services.audit.audit_log import ActorRole

ROLE_HEADER = "X-Steward-Role"
TENANT_HEADER = "X-Steward-Tenant"


class Caller(BaseModel):
    """Per-request identity, constructed by `get_caller`. Not persisted
    (data-model.md#Caller)."""

    model_config = {"frozen": True}

    role: ActorRole
    tenant_id: str | None = None


def get_caller(
    x_steward_role: str | None = Header(default=None, alias=ROLE_HEADER),
    x_steward_tenant: str | None = Header(default=None, alias=TENANT_HEADER),
) -> Caller:
    """Parse the auth-stub headers into a `Caller`.

    A missing or unrecognized `X-Steward-Role` value is treated
    identically — both default to `analyst`, the more restrictive role
    (FR-008, fail-closed; spec.md Clarifications, Session 2026-07-28).
    `X-Steward-Tenant` is passed through as the caller's `tenant_id`
    (blank/whitespace-only treated as absent); whether a tenant is
    *required* or well-formed for a given query's tables is an
    enforcement-time concern (Scenario 5), not this dependency's.
    """
    try:
        role = ActorRole(x_steward_role) if x_steward_role else ActorRole.ANALYST
    except ValueError:
        role = ActorRole.ANALYST

    tenant_id = x_steward_tenant.strip() if x_steward_tenant and x_steward_tenant.strip() else None

    return Caller(role=role, tenant_id=tenant_id)


class AdminRoleRequiredError(HTTPException):
    """Raised by `require_admin` for a non-admin caller on an admin-only
    endpoint (contracts/api.md: `{ error: "admin role required" }`,
    Scenario 8). Rendered by the handler registered in `main.py` so the
    403 body matches the contract's `error` key rather than FastAPI's
    default `detail` key."""

    def __init__(self) -> None:
        super().__init__(status_code=403, detail="admin role required")


def require_admin(caller: Annotated[Caller, Depends(get_caller)]) -> Caller:
    """Gate an admin-only endpoint (FR-013). A non-admin caller gets a
    403 and must leave the underlying record unchanged — enforced by the
    caller never reaching the record mutation below this dependency."""
    if caller.role != ActorRole.ADMIN:
        raise AdminRoleRequiredError()
    return caller


def get_domain_config(domain: str) -> DomainConfig:
    """Resolve the `{domain}` path param to its `DomainConfig`.

    404s on an unconfigured domain name (FR-011) rather than letting an
    unknown domain silently proceed — a fail-closed default at the API
    boundary, mirrored by every domain-scoped endpoint that depends on
    this."""
    try:
        return get_domain(domain)
    except UnknownDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
