"""`POST /domains/{domain}/schema/enumerate` (contracts/api.md, FR-001)."""

from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import Caller, get_caller, get_domain_config
from src.config.domains import DomainConfig
from src.services.enumeration.schema_enumerator import enumerate_schema

router = APIRouter(prefix="/domains/{domain}", tags=["schema"])


@router.post("/schema/enumerate")
def enumerate_domain_schema(
    domain: Annotated[DomainConfig, Depends(get_domain_config)],
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    """Enumerate all tables/columns for `domain` (FR-001). Calls no LLM
    and returns no row-level data, only structural metadata."""
    del caller  # not role-gated (contract §Auth header); accepted for consistency
    if not domain.database_url:
        raise HTTPException(
            status_code=503, detail=f"no database configured for domain {domain.name!r}"
        )
    with psycopg.connect(domain.database_url) as conn:
        snapshot = enumerate_schema(domain.name, conn)
    return {"tables": [table.model_dump() for table in snapshot.tables]}
