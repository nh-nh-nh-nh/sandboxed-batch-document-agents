"""FastAPI app: CORS, lifespan, routers (SPEC.md §2, §5)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from temporalio.client import Client

from sbda.api.deps import set_temporal_client
from sbda.api.routes_submissions import router as submissions_router
from sbda.api.routes_tenants import router as tenants_router
from sbda.config import settings
from sbda.temporal.client import RealTemporalClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("sbda API starting up")
    if settings.temporal_api_key:
        client = await Client.connect(
            settings.temporal_address,
            namespace=settings.temporal_namespace,
            tls=settings.temporal_tls,
            api_key=settings.temporal_api_key,
        )
        set_temporal_client(RealTemporalClient(client))
        logger.info("sbda API connected to Temporal at %s", settings.temporal_address)
    else:
        logger.warning(
            "sbda API starting without TEMPORAL_API_KEY set — submissions will "
            "be accepted but no workflow will actually run (StubTemporalClient)"
        )
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
