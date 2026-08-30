from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _csv(name: str, content: bytes = b"a,b\n1,2\n") -> tuple[str, tuple]:
    return ("files", (name, content, "text/csv"))


async def test_happy_path_inserts_submission_and_files(app_client, tenant):
    client, ctx = app_client
    resp = await client.post(
        f"/api/tenants/{tenant.id}/submissions",
        files=[_csv("a.csv"), _csv("b.csv")],
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["file_count"] == 2
    assert len(body["files"]) == 2
    assert body["status"] == "PENDING"
    assert ctx["temporal"].calls[0]["tenant_id"] == tenant.id


async def test_zero_files_returns_400(app_client, tenant):
    client, _ = app_client
    resp = await client.post(f"/api/tenants/{tenant.id}/submissions", files=[])
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "NO_FILES"


async def test_101_files_returns_400(app_client, tenant):
    client, _ = app_client
    files = [_csv(f"f{i}.csv") for i in range(101)]
    resp = await client.post(f"/api/tenants/{tenant.id}/submissions", files=files)
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "TOO_MANY_FILES"


async def test_bad_extension_returns_400_naming_file(app_client, tenant):
    client, _ = app_client
    resp = await client.post(
        f"/api/tenants/{tenant.id}/submissions",
        files=[_csv("good.csv"), ("files", ("bad.pdf", b"%PDF-1.4", "application/pdf"))],
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "UNSUPPORTED_EXTENSION"
    assert "bad.pdf" in detail["message"]


async def test_oversized_file_returns_413_and_cleans_up_s3(app_client, tenant):
    client, ctx = app_client
    max_bytes = ctx["settings"].max_file_bytes
    resp = await client.post(
        f"/api/tenants/{tenant.id}/submissions",
        files=[_csv("small.csv"), ("files", ("big.csv", b"x" * (max_bytes + 1), "text/csv"))],
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"] == "FILE_TOO_LARGE"

    objs = ctx["s3"].list_objects_v2(Bucket=ctx["settings"].s3_bucket)
    assert objs.get("KeyCount", 0) == 0


async def test_db_failure_after_upload_triggers_s3_cleanup(app_client, tenant, monkeypatch):
    client, ctx = app_client

    async def failing_commit(self):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)

    resp = await client.post(
        f"/api/tenants/{tenant.id}/submissions",
        files=[_csv("a.csv")],
    )
    assert resp.status_code == 500

    objs = ctx["s3"].list_objects_v2(Bucket=ctx["settings"].s3_bucket)
    assert objs.get("KeyCount", 0) == 0


async def test_duplicate_idempotency_key_returns_original_no_second_workflow(app_client, tenant):
    client, ctx = app_client
    key = str(uuid.uuid4())

    resp1 = await client.post(
        f"/api/tenants/{tenant.id}/submissions",
        files=[_csv("a.csv")],
        headers={"Idempotency-Key": key},
    )
    assert resp1.status_code == 202
    submission_id = resp1.json()["id"]

    resp2 = await client.post(
        f"/api/tenants/{tenant.id}/submissions",
        files=[_csv("different.csv")],
        headers={"Idempotency-Key": key},
    )
    assert resp2.status_code == 200
    assert resp2.json()["id"] == submission_id
    assert len(ctx["temporal"].calls) == 1  # no second workflow start

    objs = ctx["s3"].list_objects_v2(Bucket=ctx["settings"].s3_bucket)
    assert objs.get("KeyCount", 0) == 1  # nothing uploaded for the retry


async def test_different_idempotency_key_creates_second_submission(app_client, tenant):
    client, ctx = app_client

    resp1 = await client.post(
        f"/api/tenants/{tenant.id}/submissions",
        files=[_csv("a.csv")],
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    resp2 = await client.post(
        f"/api/tenants/{tenant.id}/submissions",
        files=[_csv("a.csv")],
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp1.status_code == 202
    assert resp2.status_code == 202
    assert resp1.json()["id"] != resp2.json()["id"]
    assert len(ctx["temporal"].calls) == 2


async def test_workflow_already_started_error_is_swallowed(app_client, tenant):
    client, ctx = app_client
    ctx["temporal"].raise_already_started = True
    resp = await client.post(f"/api/tenants/{tenant.id}/submissions", files=[_csv("a.csv")])
    assert resp.status_code == 202


async def test_cross_tenant_submission_read_is_404(app_client, tenant, other_tenant):
    client, _ = app_client
    resp = await client.post(f"/api/tenants/{tenant.id}/submissions", files=[_csv("a.csv")])
    submission_id = resp.json()["id"]

    cross = await client.get(f"/api/tenants/{other_tenant.id}/submissions/{submission_id}")
    assert cross.status_code == 404


async def test_cross_tenant_file_report_read_is_404(app_client, tenant, other_tenant):
    client, _ = app_client
    resp = await client.post(f"/api/tenants/{tenant.id}/submissions", files=[_csv("a.csv")])
    file_id = resp.json()["files"][0]["id"]

    cross = await client.get(f"/api/tenants/{other_tenant.id}/files/{file_id}/report")
    assert cross.status_code == 404


async def test_get_submission_omits_report_and_sets_has_report(app_client, tenant):
    client, _ = app_client
    resp = await client.post(f"/api/tenants/{tenant.id}/submissions", files=[_csv("a.csv")])
    submission_id = resp.json()["id"]

    detail = await client.get(f"/api/tenants/{tenant.id}/submissions/{submission_id}")
    body = detail.json()
    assert "report" not in body["files"][0]
    assert body["files"][0]["has_report"] is False


async def test_get_file_report_404_when_null(app_client, tenant):
    client, _ = app_client
    resp = await client.post(f"/api/tenants/{tenant.id}/submissions", files=[_csv("a.csv")])
    file_id = resp.json()["files"][0]["id"]

    report_resp = await client.get(f"/api/tenants/{tenant.id}/files/{file_id}/report")
    assert report_resp.status_code == 404


async def test_history_endpoint_newest_first_and_paginates(app_client, tenant):
    client, _ = app_client
    ids = []
    for i in range(3):
        resp = await client.post(f"/api/tenants/{tenant.id}/submissions", files=[_csv(f"{i}.csv")])
        ids.append(resp.json()["id"])

    history = await client.get(f"/api/tenants/{tenant.id}/submissions?limit=2&offset=0")
    body = history.json()
    assert len(body) == 2
    assert body[0]["id"] == ids[-1]  # newest first
    assert "files" not in body[0]

    page2 = await client.get(f"/api/tenants/{tenant.id}/submissions?limit=2&offset=2")
    assert len(page2.json()) == 1


async def test_duplicate_filenames_get_distinct_s3_keys(app_client, tenant):
    client, ctx = app_client
    resp = await client.post(
        f"/api/tenants/{tenant.id}/submissions",
        files=[_csv("same.csv", b"1"), _csv("same.csv", b"22")],
    )
    assert resp.status_code == 202
    objs = ctx["s3"].list_objects_v2(Bucket=ctx["settings"].s3_bucket)
    keys = [o["Key"] for o in objs["Contents"]]
    assert len(set(keys)) == 2


async def test_tenant_not_found_is_404(app_client):
    client, _ = app_client
    resp = await client.get(f"/api/tenants/{uuid.uuid4()}/submissions")
    assert resp.status_code == 404


async def test_list_tenants(app_client, tenant, other_tenant):
    client, _ = app_client
    resp = await client.get("/api/tenants")
    assert resp.status_code == 200
    slugs = {t["slug"] for t in resp.json()}
    assert {"company-a", "company-b"} <= slugs


async def test_health_endpoint(app_client):
    client, _ = app_client
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
