"""FastAPI app: CORS, lifespan, routers (SPEC.md §2, §5)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sbda.api.routes_submissions import router as submissions_router
from sbda.api.routes_tenants import router as tenants_router
from sbda.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("sbda API starting up")
    yield
    logger.info("sbda API shutting down")


def create_app() -> FastAPI:
    app = FastAPI(title="Sandboxed Batch Document Agents", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(tenants_router)
    app.include_router(submissions_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
