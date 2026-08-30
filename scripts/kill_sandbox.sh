#!/usr/bin/env bash
# Given a Temporal (Cloud) workflow execution link for a FileAnalysisWorkflow
# run, pulls the live sandbox_id out of its event history (from the
# provision_sandbox / recover_sandbox activity results) and terminates that
# Modal sandbox — for demoing the sandbox-loss-recovery path.
#
# Usage:
#   ./kill_sandbox.sh <temporal-execution-url>
#   ./kill_sandbox.sh --workflow-id <id> [--run-id <id>]
#
# Example URL (Temporal Cloud UI):
#   https://cloud.temporal.io/namespaces/sandboxed-batch-document-agents.ast5h/workflows/file-analysis-<file_id>/<run_id>/history
#
# Requires: temporal CLI, jq, python3 with `modal` installed & configured.
# Reads TEMPORAL_ADDRESS / TEMPORAL_NAMESPACE / TEMPORAL_API_KEY from the
# environment or repo-root .env.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

: "${TEMPORAL_ADDRESS:?Set TEMPORAL_ADDRESS (or put it in .env)}"
: "${TEMPORAL_NAMESPACE:?Set TEMPORAL_NAMESPACE (or put it in .env)}"
: "${TEMPORAL_API_KEY:?Set TEMPORAL_API_KEY (or put it in .env)}"

WORKFLOW_ID=""
RUN_ID=""
YES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workflow-id) WORKFLOW_ID="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    -y|--yes) YES=1; shift ;;
    http*)
      URL="$1"
      # Expect .../workflows/<workflow_id>/<run_id>/... — run_id segment is
      # optional (Temporal Cloud UI omits it when showing "current run").
      WORKFLOW_ID="$(echo "$URL" | sed -E 's#.*/workflows/([^/]+)(/([^/]+))?.*#\1#')"
      MAYBE_RUN_ID="$(echo "$URL" | sed -E 's#.*/workflows/([^/]+)(/([^/]+))?.*#\3#')"
      # Guard against picking up a trailing path segment like "history" as run_id.
      if [[ -n "$MAYBE_RUN_ID" && "$MAYBE_RUN_ID" != "history" && "$MAYBE_RUN_ID" != "events" ]]; then
        RUN_ID="$MAYBE_RUN_ID"
      fi
      shift ;;
    *) echo "Unrecognized arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$WORKFLOW_ID" ]]; then
  echo "Usage: $0 <temporal-execution-url> | --workflow-id <id> [--run-id <id>]" >&2
  exit 1
fi

echo "workflow-id: $WORKFLOW_ID" >&2
echo "run-id:      ${RUN_ID:-<latest>}" >&2

TEMPORAL_ARGS=(
  --address "$TEMPORAL_ADDRESS"
  --namespace "$TEMPORAL_NAMESPACE"
  --api-key "$TEMPORAL_API_KEY"
  --workflow-id "$WORKFLOW_ID"
)
[[ -n "$RUN_ID" ]] && TEMPORAL_ARGS+=(--run-id "$RUN_ID")

HISTORY_JSON="$(mktemp)"
trap 'rm -f "$HISTORY_JSON"' EXIT

temporal workflow show "${TEMPORAL_ARGS[@]}" --output json > "$HISTORY_JSON"

# Map scheduledEventId -> activity type name, then pull sandbox_id out of the
# result payload of any provision_sandbox / recover_sandbox completion.
# temporal CLI's default JSON output ("shorthand payloads") already decodes
# payload .data to a plain JSON value; fall back to base64 decode if not.
SANDBOX_IDS="$(jq -r '
  (
    [.events[]
     | select(.eventType=="EVENT_TYPE_ACTIVITY_TASK_SCHEDULED")
     | {(.eventId|tostring): .activityTaskScheduledEventAttributes.activityType.name}
    ] | add // {}
  ) as $sched
  | .events[]
  | select(.eventType=="EVENT_TYPE_ACTIVITY_TASK_COMPLETED")
  | . as $e
  | ($sched[($e.activityTaskCompletedEventAttributes.scheduledEventId|tostring)] // "") as $name
  | select($name=="provision_sandbox" or $name=="recover_sandbox")
  | $e.activityTaskCompletedEventAttributes.result.payloads[0].data
' "$HISTORY_JSON" | while IFS= read -r data; do
    # data is either already a JSON object (shorthand) or a base64 string
    if echo "$data" | jq -e . >/dev/null 2>&1; then
      echo "$data" | jq -r '.sandbox_id // empty'
    else
      echo "$data" | base64 -d | jq -r '.sandbox_id // empty'
    fi
  done)"

if [[ -z "$SANDBOX_IDS" ]]; then
  echo "No provision_sandbox/recover_sandbox activity results found yet in this workflow's history." >&2
  echo "(It may not have started, or hasn't provisioned a sandbox yet — try again shortly.)" >&2
  exit 1
fi

echo "Sandbox generations seen (oldest first):" >&2
echo "$SANDBOX_IDS" | nl -ba >&2

LATEST_SANDBOX_ID="$(echo "$SANDBOX_IDS" | tail -n1)"
echo "" >&2
echo "Latest (current) sandbox_id: $LATEST_SANDBOX_ID" >&2

if [[ -z "$YES" ]]; then
  read -r -p "Terminate this sandbox now? [y/N] " CONFIRM
  [[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted." >&2; exit 1; }
fi

python3 -c "
import modal
sb = modal.Sandbox.from_id('$LATEST_SANDBOX_ID')
sb.terminate()
print('Terminated sandbox: $LATEST_SANDBOX_ID')
"
