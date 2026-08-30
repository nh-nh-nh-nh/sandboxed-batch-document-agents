# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Sandboxed Batch Document Agents (see `SPEC.md` for the full design). This is
being built in slices; this file documents what exists so far.

**Implemented in this slice ("backend foundation"):** repo scaffolding
(`backend/pyproject.toml`, `docker-compose.yml`, `.env.example`, `Makefile`),
the Postgres data layer (`backend/src/sbda/db/`, Alembic migrations, seed
script), the pure `backend/src/sbda/core/` logic package (validation, naming,
rollup, truncate, errors, report schema — no I/O, no Temporal/Modal/boto3/
Anthropic imports), the S3/MinIO storage client (`backend/src/sbda/storage/`),
and the FastAPI layer (`backend/src/sbda/api/`) implementing every endpoint in
SPEC.md §5.2.

**Not yet implemented (other slices):** `backend/src/sbda/temporal/` (the
SubmissionWorkflow / FileAnalysisWorkflow and their activities),
`backend/src/sbda/sandboxes/` (the Modal image), `backend/src/sbda/agent/`
(prompts, tool schemas, sandbox-side runtime), and `frontend/` (the React
SPA). Until the Temporal slice lands, `api/deps.py` exposes a
`TemporalClientInterface` + `StubTemporalClient` that logs instead of
starting a real workflow — see that file's docstring for how to wire in the
real client.

## Build / lint / test

All Python commands run from `backend/` (a `uv`-managed project, Python
3.12), or via the root `Makefile` targets, which `cd` into `backend/` for you.

```bash
cd backend
uv sync --extra dev        # install deps into backend/.venv

# from repo root:
make up                    # docker compose up -d (postgres, minio, temporal, ...)
make migrate                # alembic upgrade head
make seed                   # insert the two seed tenants (Company A / Company B)
make api                    # uvicorn sbda.api.main:app --reload, :8000

make test-unit               # tests/unit — pure sbda.core logic, no services needed
make test-api                 # tests/api — needs `make up` (real Postgres) first; S3 is mocked (moto)
make test                     # everything
```

Run a single test:

```bash
cd backend
uv run pytest ../tests/unit/test_naming.py -q
uv run pytest ../tests/unit/test_naming.py::test_traversal_no_dot_dot_or_slash_survives -q
```

Lint: `cd backend && uv run ruff check src ../tests`.

Coverage gate (SPEC.md §14.7): 90% on `sbda/core/`, 70% overall —
`uv run pytest ../tests/unit ../tests/api --cov=sbda --cov-report=term-missing`.

Note: this environment's Rust toolchain can't build `cbor2`'s or
`cryptography`'s latest sdists (missing the `edition2024` cargo feature);
`backend/pyproject.toml` pins `[tool.uv].override-dependencies` to the last
versions with prebuilt wheels. If your environment has a newer Rust
toolchain, those overrides can be dropped.

## Architecture

Three tables in Postgres (`sbda.db.models`): `tenants`, `submissions`,
`files` — Postgres is the eventually-consistent read model; Temporal
workflow history (once the Temporal slice lands) is the source of truth for
execution. See `SPEC.md` §1 and §3 for the full picture.

`sbda/core/` is deliberately dependency-free (no Temporal, Modal, boto3, or
Anthropic imports) so its unit tests run in under a second with no services.
Everything in `sbda/api/`, `sbda/db/`, and `sbda/storage/` is thin plumbing
around it. `sbda/api/deps.py::TemporalClientInterface` is the seam where the
Temporal-workflow slice plugs in.
