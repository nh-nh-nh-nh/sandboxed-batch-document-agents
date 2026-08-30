"""`GET /api/tenants` (SPEC.md §5.2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sbda.api.deps import get_db
from sbda.db.models import Tenant

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


class TenantOut(BaseModel):
    id: uuid.UUID
    slug: str
    display_name: str

    model_config = {"from_attributes": True}


@router.get("", response_model=list[TenantOut])
async def list_tenants(db: AsyncSession = Depends(get_db)) -> list[Tenant]:
    result = await db.execute(select(Tenant).order_by(Tenant.slug))
    return list(result.scalars().all())
