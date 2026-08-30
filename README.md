# Sandboxed Batch Document Agents

A multi-tenant, durable, batch document-analysis platform. See [`SPEC.md`](./SPEC.md)
for the full design — this file is the quickstart and manual verification guide.

## Quickstart

```bash
cp .env.example .env        # fill in ANTHROPIC_API_KEY, MODAL_TOKEN_*, TEMPORAL_API_KEY
make up                     # docker compose up -d  (postgres, minio — Temporal is Cloud-hosted)
make migrate                # alembic upgrade head
make seed                   # insert Company A + Company B tenants

make api                    # uvicorn, :8000
make worker-workflow        # temporal worker: workflow tasks
make worker-activities      # temporal worker: provision_sandbox/exec_tool/mark_* DB
make worker-llm             # temporal worker: call_claude
make worker-terminate       # temporal worker: terminate_sandbox
make web                    # vite dev server, :5173
```

Each `make worker-*` is a separate process polling its own task queue
(SPEC.md §6.1) — all four need to be running for a submission to complete.

Then open **http://localhost:5173** — the split-screen UI, one panel per
seeded tenant (Company A / Company B).

### Credentials you need

| variable | why |
|---|---|
| `ANTHROPIC_API_KEY` | the agentic loop calls `claude-sonnet-5` per file |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | each file is analyzed inside a Modal sandbox |
| `TEMPORAL_API_KEY` | every worker and the API connect to the Temporal Cloud namespace `sandboxed-batch-document-agents.ast5h` |

Postgres and MinIO are containerized by `make up` and need no credentials of
their own beyond the defaults in `.env.example`. Temporal is **not**
containerized — both local dev and production connect to the same Temporal
Cloud namespace. Each worker fails fast at startup with a clear message if a
credential its role needs is missing (`workflow` needs only
`TEMPORAL_API_KEY`; `activities`/`terminate` also need the `MODAL_TOKEN_*`
pair; `llm` also needs `ANTHROPIC_API_KEY`).

### Running the test suites

```bash
make test              # everything (backend + frontend)
make test-unit          # tests/unit only — no Docker, no credentials, no network
make test-api            # tests/api — needs `make up` (real Postgres) first; S3 is mocked (moto)
make test-activities      # tests/activities — Modal/Temporal activities, mocked
make test-workflows        # tests/workflows — Temporal workflow replay tests
make test-web                # vitest (frontend)
```

`cd frontend && npm test` runs the same frontend suite directly, and
`cd frontend && npm run build` type-checks and builds the SPA.

## What's here

Both halves of the stack are implemented: `backend/` (FastAPI, Postgres
models, Temporal workflows/activities, the Modal sandbox layer, and the
agentic loop) and `frontend/` (the React SPA), against the API contract in
`SPEC.md` §5. The frontend's own test suite has no runtime dependency on the
backend being up to build, lint, or pass (`msw` mocks every `fetch` call);
see `CLAUDE.md` for what's implemented where.
