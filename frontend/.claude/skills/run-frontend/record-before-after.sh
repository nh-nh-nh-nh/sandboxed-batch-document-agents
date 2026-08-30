#!/usr/bin/env bash
# Records the same demo interaction against a base ref ("before") and the
# current working tree ("after"), for embedding in a PR description.
#
# Usage: record-before-after.sh <base-ref> [out-dir]
#
# Run from the frontend/ directory. Requires the current worktree's mock
# API + dev server to be reachable (start them first, see SKILL.md).
set -euo pipefail

BASE_REF="${1:?usage: record-before-after.sh <base-ref> [out-dir]}"
OUT_DIR="${2:-/tmp/pr-recording}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"

mkdir -p "$OUT_DIR"

echo "== after (current worktree) =="
APP_URL="${AFTER_APP_URL:-http://localhost:5173}" \
  node "$SKILL_DIR/driver.mjs" record "$OUT_DIR/after" after

echo "== before ($BASE_REF, isolated worktree) =="
WORKTREE_DIR="$(mktemp -d)/before-worktree"
git -C "$REPO_ROOT" worktree add --detach "$WORKTREE_DIR" "$BASE_REF" >/dev/null

cleanup() {
  # `npx vite &` backgrounds the npm-exec wrapper, not the vite process it
  # spawns — npm doesn't forward SIGTERM, so $! never kills the real
  # listener. Killing by port catches the actual process either way.
  lsof -ti:"$BEFORE_API_PORT" -sTCP:LISTEN 2>/dev/null | xargs -r kill
  lsof -ti:"$BEFORE_VITE_PORT" -sTCP:LISTEN 2>/dev/null | xargs -r kill
  git -C "$REPO_ROOT" worktree remove --force "$WORKTREE_DIR" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# $BASE_REF predates this skill, so the driver/mock-api aren't there yet —
# copy them in, and reuse node_modules instead of a fresh install.
mkdir -p "$WORKTREE_DIR/frontend/.claude/skills/run-frontend"
cp "$SKILL_DIR"/*.mjs "$WORKTREE_DIR/frontend/.claude/skills/run-frontend/"
if [ -d "$REPO_ROOT/frontend/node_modules" ]; then
  cp -R "$REPO_ROOT/frontend/node_modules" "$WORKTREE_DIR/frontend/node_modules"
else
  (cd "$WORKTREE_DIR/frontend" && npm install)
fi

BEFORE_API_PORT="${BEFORE_API_PORT:-8100}"
BEFORE_VITE_PORT="${BEFORE_VITE_PORT:-5273}"

(cd "$WORKTREE_DIR/frontend" && MOCK_API_PORT="$BEFORE_API_PORT" node .claude/skills/run-frontend/mock-api.mjs) &
(cd "$WORKTREE_DIR/frontend" && VITE_API_BASE_URL="http://localhost:$BEFORE_API_PORT" \
  node node_modules/vite/bin/vite.js --port "$BEFORE_VITE_PORT") &

timeout 30 bash -c "until curl -sf http://localhost:$BEFORE_API_PORT/api/tenants >/dev/null; do sleep 1; done"
timeout 30 bash -c "until curl -sf http://localhost:$BEFORE_VITE_PORT >/dev/null; do sleep 1; done"

APP_URL="http://localhost:$BEFORE_VITE_PORT" \
  node "$SKILL_DIR/driver.mjs" record "$OUT_DIR/before" before

echo "wrote $OUT_DIR/before/before.gif and $OUT_DIR/after/after.gif"
