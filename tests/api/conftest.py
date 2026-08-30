from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import boto3
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from sqlalchemy.ext.asyncio import create_async_engine

from sbda.api import deps
from sbda.api.main import create_app
from sbda.config import Settings
from sbda.db.models import Base, Tenant

TEST_DATABASE_URL = "postgresql+asyncpg://sbda:sbda@localhost:5432/sbda_test"
ADMIN_DATABASE_URL = "postgresql+asyncpg://sbda:sbda@localhost:5432/sbda"
TEST_BUCKET = "sbda-documents-test"


@pytest_asyncio.fixture
async def test_db_url() -> AsyncIterator[str]:
    """Create + drop an ephemeral test database around each test."""

    admin_engine = create_async_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(__import__("sqlalchemy").text("DROP DATABASE IF EXISTS sbda_test"))
        await conn.execute(__import__("sqlalchemy").text("CREATE DATABASE sbda_test"))
    await admin_engine.dispose()

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    yield TEST_DATABASE_URL

    # Dispose the app's cached engine for this URL so pooled connections
    # release the database before DROP DATABASE.
    from sbda.db.engine import get_engine

    await get_engine(TEST_DATABASE_URL).dispose()
    get_engine.cache_clear()

    admin_engine = create_async_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(
            __import__("sqlalchemy").text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = 'sbda_test' AND pid <> pg_backend_pid()"
            )
        )
        await conn.execute(__import__("sqlalchemy").text("DROP DATABASE IF EXISTS sbda_test"))
    await admin_engine.dispose()


@pytest.fixture
def moto_s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=TEST_BUCKET)
        yield client


class FakeTemporalClient:
    """Records `start_submission_workflow` calls; never touches a real
    Temporal server. Set `.raise_already_started` to exercise the
    WorkflowAlreadyStartedError-swallowing path, or `.raise_error` to
    exercise the "start failed outright" repair path (see
    routes_submissions.py::_ensure_workflow_started)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.raise_already_started = False
        self.raise_error: Exception | None = None

    async def start_submission_workflow(self, *, submission_id, tenant_id, files):
        self.calls.append(
            {"submission_id": submission_id, "tenant_id": tenant_id, "files": files}
        )
        if self.raise_error is not None:
            raise self.raise_error
        if self.raise_already_started:
            raise deps.WorkflowAlreadyStartedError()
        return f"fake-run-{len(self.calls)}"


@pytest_asyncio.fixture
async def app_client(test_db_url, moto_s3) -> AsyncIterator[tuple[AsyncClient, dict]]:
    test_settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=test_db_url,
        s3_bucket=TEST_BUCKET,
        s3_endpoint_url="",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        aws_region="us-east-1",
    )

    app = create_app()
    fake_temporal = FakeTemporalClient()

    app.dependency_overrides[deps.get_settings] = lambda: test_settings
    app.dependency_overrides[deps.get_temporal_client] = lambda: fake_temporal

    from sbda.storage.s3 import S3Client

    def _get_s3_client():
        client = S3Client.__new__(S3Client)
        client.bucket = TEST_BUCKET
        client._client = moto_s3
        return client

    app.dependency_overrides[deps.get_s3_client] = _get_s3_client

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, {"temporal": fake_temporal, "settings": test_settings, "s3": moto_s3}


@pytest_asyncio.fixture
async def tenant(test_db_url) -> Tenant:
    from sbda.db.engine import get_sessionmaker

    session_factory = get_sessionmaker(test_db_url)
    async with session_factory() as session:
        t = Tenant(id=uuid.uuid4(), slug="company-a", display_name="Company A")
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


@pytest_asyncio.fixture
async def other_tenant(test_db_url) -> Tenant:
    from sbda.db.engine import get_sessionmaker

    session_factory = get_sessionmaker(test_db_url)
    async with session_factory() as session:
        t = Tenant(id=uuid.uuid4(), slug="company-b", display_name="Company B")
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t
