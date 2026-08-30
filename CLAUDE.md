# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Sandboxed Batch Document Agents (see `SPEC.md` for the full design). All
slices described in SPEC.md have landed: the Postgres data layer
(`backend/src/sbda/db/`, Alembic migrations, seed script), the pure
`backend/src/sbda/core/` logic package (validation, naming, rollup, truncate,
errors, report schema — no I/O, no Temporal/Modal/boto3/Anthropic imports),
the S3/MinIO storage client (`backend/src/sbda/storage/`), the FastAPI layer
(`backend/src/sbda/api/`) implementing every endpoint in SPEC.md §5.2, the
Temporal workflows and activities (`backend/src/sbda/temporal/` —
`SubmissionWorkflow` / `FileAnalysisWorkflow`, split across four dedicated
task queues, see SPEC.md §6.1), the Modal sandbox layer
(`backend/src/sbda/sandboxes/`), the agentic loop
(`backend/src/sbda/agent/` — prompts, tool schemas, sandbox-side runtime),
and the React SPA (`frontend/`).

`api/deps.py` still defines `TemporalClientInterface` and a
`StubTemporalClient` fallback (it logs instead of starting a workflow), but
`api/main.py`'s lifespan now wires in the real `RealTemporalClient`
(`sbda/temporal/client.py`) whenever it can connect to Temporal Cloud; the
stub only kicks in if that connection fails at startup.

Temporal is Cloud-hosted (namespace `sandboxed-batch-document-agents.ast5h`),
not run via `docker compose` — only Postgres and MinIO are containerized
locally (`docker-compose.yml`).

## Build / lint / test

All Python commands run from `backend/` (a `uv`-managed project, Python
3.12), or via the root `Makefile` targets, which `cd` into `backend/` for you.

```bash
cd backend
uv sync --extra dev        # install deps into backend/.venv

# from repo root:
make up                    # docker compose up -d (postgres, minio)
make migrate                # alembic upgrade head
make seed                   # insert the two seed tenants (Company A / Company B)
make api                    # uvicorn sbda.api.main:app --reload, :8000
make worker-workflow        # temporal worker: workflow tasks
make worker-activities      # temporal worker: provision_sandbox/exec_tool/mark_* DB
make worker-llm             # temporal worker: call_claude
make worker-terminate       # temporal worker: terminate_sandbox
make web                    # vite dev server, :5173

make test-unit               # tests/unit — pure sbda.core logic, no services needed
make test-api                 # tests/api — needs `make up` (real Postgres) first; S3 is mocked (moto)
make test-activities           # tests/activities — Modal/Temporal activities, mocked
make test-workflows             # tests/workflows — Temporal workflow replay tests
make test-web                    # vitest (frontend)
make test                         # everything (backend + frontend)
```

Run a single test:

```bash
cd backend
uv run pytest -c pyproject.toml ../tests/unit/test_naming.py -q
uv run pytest -c pyproject.toml ../tests/unit/test_naming.py::test_traversal_no_dot_dot_or_slash_survives -q
```

(the `-c pyproject.toml` is required for anything invoked from `backend/`
against a `../tests/...` path — see the comment above `test-unit` in the
`Makefile`.)

Lint: `cd backend && uv run ruff check src ../tests`.

Coverage (SPEC.md §14.7 documents the 90%/`sbda/core/` / 70%-overall target;
it is not CI-enforced — `fail_under = 0` in `backend/pyproject.toml` — so run
it manually to check):
`uv run pytest -c pyproject.toml ../tests/unit ../tests/api --cov=sbda --cov-report=term-missing`.

Note: this environment's Rust toolchain can't build `cbor2`'s or
`cryptography`'s latest sdists (missing the `edition2024` cargo feature);
`backend/pyproject.toml` pins `[tool.uv].override-dependencies` to the last
versions with prebuilt wheels. If your environment has a newer Rust
toolchain, those overrides can be dropped.

Frontend commands run from `frontend/` directly (`npm test`, `npm run build`
to type-check and build the SPA) — see `README.md` for the full local
dev/test loop across both halves of the stack.

## Architecture

Three tables in Postgres (`sbda.db.models`): `tenants`, `submissions`,
`files` — Postgres is the eventually-consistent read model; Temporal
workflow history is the source of truth for execution. See `SPEC.md` §1 and
§3 for the full picture.

`sbda/core/` is deliberately dependency-free (no Temporal, Modal, boto3, or
Anthropic imports) so its unit tests run in under a second with no services.
`sbda/api/`, `sbda/db/`, and `sbda/storage/` are thin plumbing around it.
`sbda/temporal/` hosts the workflows/activities and the four-queue worker
topology (SPEC.md §6); `sbda/sandboxes/` defines the Modal image the
`provision_sandbox` activity boots; `sbda/agent/` is the sandbox-side
agentic loop that calls Claude and executes tools inside it.
`sbda/api/deps.py::TemporalClientInterface` is the seam between the API and
the real Temporal client.
