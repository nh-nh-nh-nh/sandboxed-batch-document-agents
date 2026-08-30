---
name: run-frontend
description: Build, run, and drive the SBDA frontend SPA (Vite + React). Use when asked to start the frontend, take a screenshot of the UI, record a before/after demo of a frontend change, or embed those recordings in a PR description.
---

The frontend (`frontend/`) is a Vite + React SPA with no working backend yet
(`backend/` doesn't exist — see root `README.md`). It's driven headlessly with
a Playwright script, `.claude/skills/run-frontend/driver.mjs`, against a small
zero-dependency mock API, `.claude/skills/run-frontend/mock-api.mjs`, that
stands in for the real one. All paths below are relative to `frontend/`.

## Prerequisites

Already-installed devDependencies (`playwright`, `gifenc`, `pngjs`) plus the
Chromium binary Playwright needs:

```bash
npm install
npx playwright install chromium
```

## Build

```bash
npm run build   # tsc --noEmit && vite build
```

## Run (agent path)

Start the mock API and the dev server pointed at it, in the background:

```bash
node .claude/skills/run-frontend/mock-api.mjs > /tmp/mock-api.log 2>&1 &
VITE_API_BASE_URL=http://localhost:8000 npm run dev > /tmp/vite.log 2>&1 &
timeout 30 bash -c 'until curl -sf http://localhost:8000/api/tenants >/dev/null; do sleep 1; done'
timeout 30 bash -c 'until curl -sf http://localhost:5173 >/dev/null; do sleep 1; done'
```

Then drive it:

```bash
node .claude/skills/run-frontend/driver.mjs shot /tmp/shot.png
node .claude/skills/run-frontend/driver.mjs record /tmp/recording demo
```

| command | what it does |
|---|---|
| `shot <out.png>` | one screenshot of the loaded app |
| `record <out-dir> [gif-name]` | walks a fixed demo flow (open app → expand submission history → expand a batch → open a file's report → close it), saving `frame-NN.png` per step plus `<gif-name>.gif` stitched from them |

Stop the servers with `lsof -ti:5173,8000 -sTCP:LISTEN | xargs -r kill`.

### Before/after recordings for a PR

This is the primary reason this skill exists: for a frontend PR, record the
same demo flow against the base ref and the current branch, so both go in
the PR description.

```bash
node .claude/skills/run-frontend/mock-api.mjs > /tmp/mock-api.log 2>&1 &
VITE_API_BASE_URL=http://localhost:8000 npm run dev > /tmp/vite.log 2>&1 &
timeout 30 bash -c 'until curl -sf http://localhost:5173 >/dev/null; do sleep 1; done'

bash .claude/skills/run-frontend/record-before-after.sh main /tmp/pr-recording
# -> /tmp/pr-recording/after/after.gif   (current worktree, servers above)
# -> /tmp/pr-recording/before/before.gif (base ref, isolated git worktree + its own ports)
```

`record-before-after.sh <base-ref> [out-dir]` checks out `<base-ref>` into a
throwaway `git worktree` (never touches your working tree), copies this
skill's driver into it (the base ref may predate the skill), runs its own
mock API + dev server on ports 8100/5273, records, and cleans everything up
— including the worktree — on exit.

**Embedding in the PR description:** GitHub renders `![]()` images whose src
is a `raw.githubusercontent.com` URL for a file that's actually in the
pushed branch, so commit the recordings into the branch alongside the code
change (a real PR body can't reference `/tmp` — only what's in the repo):

```bash
mkdir -p /tmp/pr-recording-committed
cp /tmp/pr-recording/before/before.gif /tmp/pr-recording/after/after.gif /tmp/pr-recording-committed/
git add /tmp/pr-recording-committed  # (copy into the repo first, e.g. docs/pr-media/<slug>/)
```

then reference them in the PR body as:

```markdown
### Before
![before](https://raw.githubusercontent.com/<owner>/<repo>/<branch>/docs/pr-media/<slug>/before.gif)

### After
![after](https://raw.githubusercontent.com/<owner>/<repo>/<branch>/docs/pr-media/<slug>/after.gif)
```

The URL only resolves once `<branch>` is pushed — commit the gifs in the
same push as the code change, then run `gh pr create --body-file <file>`.
(This embedding step is the documented, standard GitHub behavior for
inline media in PR bodies; it wasn't exercised against a live PR in this
session since that requires pushing to the user's remote — do that only
with explicit go-ahead, same as any other push.)

## Run (human path)

```bash
VITE_API_BASE_URL=http://localhost:8000 npm run dev   # -> http://localhost:5173, Ctrl-C to stop
```

Useless without the mock API (or a real backend) also running — the SPA has
no built-in fallback data.

## Test

```bash
npm test    # vitest — 44 tests, all pass
npm run build   # tsc --noEmit && vite build
```

## Gotchas

- **`frontend/src/lib/` was silently gitignored.** The repo root
  `.gitignore` has a Python-project template with a bare `lib/` rule (no
  leading slash), which matches `frontend/src/lib/` too — every file in
  it (`format.ts`, `status.ts`, `validate.ts`) was untracked and missing
  from the repo even though every component imports from it, so the app
  couldn't build or run at all. Fixed by adding `!frontend/src/lib/` to
  `.gitignore` and reconstructing the three files from their test specs
  (`src/__tests__/{format,status,validate}.test.ts`) and SPEC.md §5.2 for
  the exact constants (`MAX_FILE_BYTES=1048576`, `MAX_FILES_PER_SUBMISSION=100`).
  If a future `git status` shows `src/lib/` as untracked again, this is
  why — check `.gitignore` before assuming the files were deleted.
- **The dev server needs `VITE_API_BASE_URL` set**, or every fetch goes to
  `http://localhost:5173/api/...` (same origin as Vite, which 404s) instead
  of the mock API on :8000. `api/client.ts` reads
  `import.meta.env.VITE_API_BASE_URL ?? ""`.
- **`getByText(/^History/)` doesn't match** the History toggle button —
  it renders as `<span>▸</span> History (1)`, so Playwright's accessible
  name starts with the triangle glyph, not "History". Use
  `getByRole("button", { name: /History/ })` instead.
- **`npx vite &` backgrounds the wrong PID.** `npx`/`npm exec` don't
  forward `SIGTERM` to the process they spawn, so `kill $!` leaves the
  real Vite listener (and the port) alive. `record-before-after.sh` kills
  by port (`lsof -ti:PORT -sTCP:LISTEN | xargs kill`) instead, and calls
  `node node_modules/vite/bin/vite.js` directly to sidestep the wrapper
  in the first place.

## Troubleshooting

- **`page.waitForSelector: Timeout ... waiting for locator('text=Company A')`**:
  the app never rendered — almost always a Vite import error (check
  `/tmp/vite.log`) or the mock API not reachable (check `VITE_API_BASE_URL`
  and that `mock-api.mjs` is actually listening on the port it's pointed
  at). `driver.mjs record` now catches this and records the error overlay
  as a single frame instead of crashing, which is exactly what you want
  for a "before" recording of a broken build.
- **`SyntaxError: Named export 'GIFEncoder' not found`**: `gifenc` is
  CommonJS; import the default and destructure (`import gifenc from
  "gifenc"; const { GIFEncoder, ... } = gifenc;`), not named imports.
