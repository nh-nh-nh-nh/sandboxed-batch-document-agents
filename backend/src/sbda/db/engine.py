"""Async SQLAlchemy engine + sessionmaker."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sbda.config import settings


@lru_cache
def get_engine(database_url: str | None = None) -> AsyncEngine:
    return create_async_engine(database_url or settings.database_url, pool_pre_ping=True)


def get_sessionmaker(
    database_url: str | None = None,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(database_url), expire_on_commit=False, class_=AsyncSession
    )


async def get_session(database_url: str | None = None) -> AsyncIterator[AsyncSession]:
    session_factory = get_sessionmaker(database_url)
    async with session_factory() as session:
        yield session
