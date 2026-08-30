"""`make seed` — insert exactly two tenants (SPEC.md §3.1)."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from sbda.db.engine import get_sessionmaker
from sbda.db.models import Tenant

SEED_TENANTS = [
    {"slug": "company-a", "display_name": "Company A"},
    {"slug": "company-b", "display_name": "Company B"},
]


async def seed() -> None:
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        for spec in SEED_TENANTS:
            result = await session.execute(select(Tenant).where(Tenant.slug == spec["slug"]))
            if result.scalar_one_or_none() is not None:
                continue
            session.add(Tenant(slug=spec["slug"], display_name=spec["display_name"]))
        await session.commit()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
