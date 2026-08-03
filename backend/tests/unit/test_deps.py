from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from src.api.deps import Caller, get_caller
from src.services.audit.audit_log import ActorRole


def test_missing_role_defaults_to_analyst():
    caller = get_caller(x_steward_role=None, x_steward_tenant=None)

    assert caller.role == ActorRole.ANALYST


def test_unrecognized_role_defaults_to_analyst():
    caller = get_caller(x_steward_role="superuser", x_steward_tenant=None)

    assert caller.role == ActorRole.ANALYST


def test_recognized_admin_role_is_preserved():
    caller = get_caller(x_steward_role="admin", x_steward_tenant=None)

    assert caller.role == ActorRole.ADMIN


def test_missing_tenant_is_none():
    caller = get_caller(x_steward_role="analyst", x_steward_tenant=None)

    assert caller.tenant_id is None


def test_blank_tenant_is_treated_as_absent():
    caller = get_caller(x_steward_role="analyst", x_steward_tenant="   ")

    assert caller.tenant_id is None


def test_tenant_value_is_stripped_and_preserved():
    caller = get_caller(x_steward_role="analyst", x_steward_tenant=" tenant-42 ")

    assert caller.tenant_id == "tenant-42"


def test_caller_is_frozen():
    caller = Caller(role=ActorRole.ANALYST, tenant_id=None)

    try:
        caller.role = ActorRole.ADMIN
        raised = False
    except Exception:
        raised = True

    assert raised


def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(caller: Annotated[Caller, Depends(get_caller)]):
        return {"role": caller.role.value, "tenant_id": caller.tenant_id}

    return app


def test_dependency_wires_through_real_headers():
    client = TestClient(_build_test_app())

    response = client.get(
        "/whoami",
        headers={"X-Steward-Role": "admin", "X-Steward-Tenant": "acme"},
    )

    assert response.status_code == 200
    assert response.json() == {"role": "admin", "tenant_id": "acme"}


def test_dependency_defaults_when_headers_absent():
    client = TestClient(_build_test_app())

    response = client.get("/whoami")

    assert response.status_code == 200
    assert response.json() == {"role": "analyst", "tenant_id": None}
