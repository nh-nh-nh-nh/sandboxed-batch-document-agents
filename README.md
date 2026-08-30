# Sandboxed Batch Document Agents

A multi-tenant, durable, batch document-analysis platform. See [`SPEC.md`](./SPEC.md)
for the full design — this file is the quickstart and manual verification guide.

## Quickstart

```bash
cp .env.example .env        # fill in ANTHROPIC_API_KEY and MODAL_TOKEN_*
make up                     # docker compose up -d  (postgres, minio, temporal, temporal-ui)
make migrate                # alembic upgrade head
make seed                   # insert Company A + Company B tenants
make fixtures                # generate sample spreadsheets into fixtures/

make api                    # uvicorn, :8000
make worker                 # temporal worker
make web                    # vite dev server, :5173
```

Then open **http://localhost:5173** — the split-screen UI, one panel per
seeded tenant (Company A / Company B).

### Credentials you need

| variable | why |
|---|---|
| `ANTHROPIC_API_KEY` | the agentic loop calls `claude-sonnet-5` per file |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | each file is analyzed inside a Modal sandbox |

Postgres, MinIO, and Temporal are containerized by `make up` and need no
credentials of their own beyond the defaults in `.env.example`. The worker
fails fast at startup with a clear message if either credential above is
missing.

### Running the test suites

```bash
make test          # everything (backend + frontend)
make test-unit      # tests/unit only — no Docker, no credentials, no network
make test-web       # vitest (frontend)
```

`cd frontend && npm test` runs the same frontend suite directly, and
`cd frontend && npm run build` type-checks and builds the SPA.

## Manual verification: dispatch fairness (§14.8)

This is the one property that has to be demonstrated live — it lives in the
Temporal server's scheduler, not in this codebase, so no automated test can
assert it.

1. Bring the full stack up (`make up migrate seed fixtures api worker web`)
   and confirm `matching.enableFairness=true` is set — the worker logs a
   startup warning if it isn't (see `infra/dynamicconfig/development.yaml`
   and `docker-compose.yml`'s `temporal` service).
2. Open the UI at `http://localhost:5173` and the Temporal UI at
   `http://localhost:8080`.
3. In the **Company A** panel, stage all 8 fixture files repeatedly (or any
   ~20 files — duplicates are fine, the loop only cares about volume) and
   submit. You now have a backlog of `FileAnalysisWorkflow` children queued
   under the `company-a` fairness key.
4. A few seconds later, before Company A's backlog drains, submit **1 file**
   in the **Company B** panel.
5. Watch both the UI's `BatchTable` and the Temporal UI's task-queue view:
   Company B's single file should start (transition out of `PENDING`/
   "Queued") well before Company A's 20-file backlog finishes, rather than
   queueing FIFO behind all of it. With `WORKER_MAX_CONCURRENT_ACTIVITIES=16`
   (the default), this is visible as B's file getting a slice of that
   concurrency alongside A's files, not after them.
6. **Contrast run.** Stop the stack, flip `matching.enableFairness` to
   `false` in `infra/dynamicconfig/development.yaml`, `make up` again, and
   repeat steps 3–5. This time Company B's file should sit in `PENDING`
   until Company A's backlog has worked through the same amount of queue
   position — plain FIFO. This side-by-side is the only honest way to show
   the property, since fairness is a Temporal server behavior this repo only
   configures, not implements.

## What's not built here

This branch (`feat/frontend`) implements only `frontend/`, `fixtures/generate.py`,
and this README, against the API contract in `SPEC.md` §5. `backend/` (FastAPI,
Postgres models, Temporal workflows/activities, the Modal sandbox layer, and the
agentic loop) is owned by other branches and is expected to land separately —
the frontend has no runtime dependency on it being present to build, lint, or
pass its own test suite (`msw` mocks every `fetch` call).
