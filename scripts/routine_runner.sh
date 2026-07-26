#!/bin/bash
# routine_runner.sh — Wrapper for scheduled local routines.
#
# Invoked by launchd. Handles:
#   1. Environment setup ($OV, PATH)
#   2. Single-owner eligibility check (non-owner machines exit before work)
#   3. Claim schedule gate for completed, fenced, or not-yet-due cycles
#   4. Hostname-based stagger (0-120s) to reduce race probability
#   5. Atomic owner claim reservation or DynamoDB acquire
#   6. Local claim detail write ($OV/_meta/routine_runs/<routine>/<cycle>.toml)
#   7. Headless execution through Codex
#   8. Lock release + claim file update
#
# Usage:
#   routine_runner.sh <routine-name> <command>
#   routine_runner.sh autoevo-nightly /autoevo-nightly
#   routine_runner.sh <name> "/run-routine <name>"
#
# Environment:
#   OV                       — vault root (required)
#   ATELIER_SKIP_LOCK_TOUCH  — set by this script; prevents session hooks
#                               from touching the session-active lock
#   ATELIER_COORDINATION     — override coordination mode (default: reads
#                               from routine_watch.toml). Cannot downgrade the
#                               shared "owner" fence to "none".
#   ATELIER_SKIP_STAGGER     — set to 1 to skip the hostname stagger (for
#                               manual test runs via launchctl start)
#   ATELIER_SKIP_CAFFEINATE  - set to 1 to disable the macOS wake assertion
#   ATELIER_PREFLIGHT_TIMEOUT_SECONDS
#                            - hard timeout for each ownership/config probe
#                               (default: 30)
#   ATELIER_ROUTINE_CYCLE    - internal sanitized model environment value;
#                               always derived from the validated selected cycle
# Unattended local routines always use Codex. `ATELIER_RUNTIME` and the local
# runtime preference apply only to interactive Atelier launchers.

set -euo pipefail

ROUTINE="${1:?Usage: routine_runner.sh <routine-name> <command>}"
COMMAND="${2:?Usage: routine_runner.sh <routine-name> <command>}"
if [[ ! "$ROUTINE" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "ERROR: invalid routine name: $ROUTINE" >&2
    exit 2
fi
if [[ ! "$COMMAND" =~ ^/[A-Za-z0-9][A-Za-z0-9._-]*([[:space:]][A-Za-z0-9][A-Za-z0-9._-]*)?$ ]]; then
    echo "ERROR: scheduled commands must use /<command> with at most one safe argument: $COMMAND" >&2
    exit 2
fi
CYCLE="$(date +%Y-%m-%d)"
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
ATELIER_DIR="$(dirname "$SCRIPTS_DIR")"

# --- environment setup ---------------------------------------------------

export ATELIER_SKIP_LOCK_TOUCH=1

# Source profile files in a subshell-safe way. `set -u` in the main script
# would abort on unset variables inside .zprofile/.profile, so we temporarily
# relax strictness. Only OV and PATH matter; everything else is noise.
set +eu
source "$HOME/.zprofile" 2>/dev/null || true
source "$HOME/.profile" 2>/dev/null || true
source "$ATELIER_DIR/harness/env.local.sh" 2>/dev/null || true
set -eu

# Runtime installers may put their CLI in ~/.local/bin, which only ~/.zshrc
# (interactive-only) adds to PATH, not the login profiles sourced above.
# Prepend it so launchd sees the same executable as an interactive shell.
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) [ -d "$HOME/.local/bin" ] && export PATH="$HOME/.local/bin:$PATH" ;;
esac

: "${OV:?ERROR: OV not set — export it from ~/.zprofile, ~/.profile, or ~/atelier/harness/env.local.sh}"

# Resolve calendar, wake, login, and reload invocations through one
# deterministic selector. Before 05:00 it catches up yesterday only when that
# cycle did not complete; from 05:00 onward it targets today immediately.
if [ "$ROUTINE" = "autoevo-nightly" ]; then
    if ! CYCLE_SELECTION=$(python3 "$SCRIPTS_DIR/routine_claim.py" "$ROUTINE" --select-cycle); then
        echo "ERROR: cannot select scheduled autoevo cycle" >&2
        exit 2
    fi
    CYCLE_ACTION=$(printf '%s' "$CYCLE_SELECTION" | python3 -c '
import json, sys
value = json.load(sys.stdin)
action = value.get("action")
if action not in {"run", "skip"}:
    raise SystemExit("cycle selection omitted a valid action")
print(action)
')
    CYCLE=$(printf '%s' "$CYCLE_SELECTION" | python3 -c '
import json, sys
value = json.load(sys.stdin)
cycle = value.get("cycle_id")
if not isinstance(cycle, str) or not cycle:
    raise SystemExit("cycle selection omitted cycle_id")
print(cycle)
')
    if [ "$CYCLE_ACTION" = "skip" ]; then
        echo "[$(date -Iseconds)] skipping scheduled catch-up: $CYCLE_SELECTION"
        exit 0
    fi
    echo "[$(date -Iseconds)] scheduled cycle selected: $CYCLE_SELECTION"
fi
if ! CYCLE=$(python3 "$SCRIPTS_DIR/routine_claim.py" "$ROUTINE" \
    --validate-cycle "$CYCLE"); then
    echo "ERROR: scheduled cycle is not a valid calendar date" >&2
    exit 2
fi

PREFLIGHT_TIMEOUT_SECONDS="${ATELIER_PREFLIGHT_TIMEOUT_SECONDS:-30}"
TIMEOUT_CMD=(python3 "$SCRIPTS_DIR/command_timeout.py" --seconds "$PREFLIGHT_TIMEOUT_SECONDS" --)

# --- single-owner gate ---------------------------------------------------
#
# This runs before claim creation and the stagger. A
# non-owner machine with an installed plist exits cleanly without touching
# shared run state. The check is repeated by routine_lock.py at acquire time so
# an ownership transfer racing this invocation still fails closed.

OWNER_RESULT=$("${TIMEOUT_CMD[@]}" python3 "$SCRIPTS_DIR/routine_owner.py" check --json 2>&1) || OWNER_EXIT=$?
OWNER_EXIT=${OWNER_EXIT:-0}
if [ "$OWNER_EXIT" -eq 1 ]; then
    echo "[$(date -Iseconds)] skipping: local routines owned by another machine ($OWNER_RESULT)"
    exit 0
fi
if [ "$OWNER_EXIT" -ne 0 ]; then
    echo "[$(date -Iseconds)] ERROR: routine owner check failed: $OWNER_RESULT" >&2
    exit 2
fi
if ! OWNER_MODE=$(printf '%s' "$OWNER_RESULT" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("coordination", ""))'); then
    echo "ERROR: owner check returned invalid JSON" >&2
    exit 2
fi
OWNER_GENERATION=$(printf '%s' "$OWNER_RESULT" | python3 -c 'import json, sys; value=json.load(sys.stdin).get("generation"); print(value if isinstance(value, int) else "")')
OWNER_GENERATION=${OWNER_GENERATION:-0}

RUNTIME="codex"

mkdir -p "$OV/cache" "$OV/_meta/routine_runs/$ROUTINE" "$OV/_meta/routine_failures/$ROUTINE"

CLAIM_DIR="$OV/_meta/routine_runs/$ROUTINE"
CLAIM_FILE="$CLAIM_DIR/$CYCLE.toml"
HOSTNAME="$(hostname)"
FAILURE_DIR="$OV/_meta/routine_failures/$ROUTINE"
AUTOEVO_EVENT_LOG=""
AUTOEVO_EVENT_LOG_REL=""

runner_event() {
    local line
    line="[$(date -Iseconds)] $*"
    printf '%s\n' "$line"
    if [ -n "$AUTOEVO_EVENT_LOG" ]; then
        printf '%s\n' "$line" >> "$AUTOEVO_EVENT_LOG"
    fi
}

# Hourly launchd checks are intentionally cheap after a cycle completes or
# while a deferred retry is cooling down. This gate runs after the owner check
# but before capability probes, stagger, lock acquisition, or model work.
if ! CLAIM_SCHEDULE_DECISION=$(python3 "$SCRIPTS_DIR/routine_claim.py" "$ROUTINE" \
    --cycle "$CYCLE" --schedule-decision); then
    echo "ERROR: cannot inspect canonical cycle claim: $CLAIM_FILE" >&2
    exit 2
fi
CLAIM_SCHEDULE_ACTION=$(printf '%s' "$CLAIM_SCHEDULE_DECISION" | python3 -c '
import json, sys
value = json.load(sys.stdin)
action = value.get("action")
if action not in {"run", "skip"}:
    raise SystemExit("claim schedule decision omitted a valid action")
print(action)
')
if [ "$CLAIM_SCHEDULE_ACTION" = "skip" ]; then
    echo "[$(date -Iseconds)] skipping scheduled check: $CLAIM_SCHEDULE_DECISION"
    exit 0
fi

write_failure_diagnostic() {
    local phase="$1"
    local error_json="$2"
    local diagnostic_file="$FAILURE_DIR/$(date +%Y%m%dT%H%M%S)-$HOSTNAME-$$.toml"
    cat > "$diagnostic_file" <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
recorded_at = "$(date -Iseconds)"
phase = "$phase"
status = "failed"
error = $error_json
EOF
    echo "[$(date -Iseconds)] diagnostic: $diagnostic_file" >&2
}

write_claim() {
    python3 "$SCRIPTS_DIR/routine_claim.py" "$ROUTINE" --cycle "$CYCLE" >/dev/null
}

# Resolve the private routine's declared support surface against the public
# capability profiles before claiming a cycle. This fails closed on missing
# CLIs, required Codex plugins, owner drift, or an unloaded launchd job.
if ! PROFILE_RECORD=$("${TIMEOUT_CMD[@]}" python3 "$SCRIPTS_DIR/routine_audit.py" resolve "$ROUTINE" \
    --surface local --check-system --runtime "$RUNTIME" --command "$COMMAND" --format tsv 2>&1); then
    SAFE_PROFILE_ERROR=$(printf '%s' "$PROFILE_RECORD" | python3 -c 'import json, sys; print(json.dumps("routine-preflight-failed: " + sys.stdin.read().replace("\n", " ")))')
    write_failure_diagnostic "capability-preflight" "$SAFE_PROFILE_ERROR"
    echo "ERROR: routine capability preflight failed: $PROFILE_RECORD" >&2
    exit 2
fi

IFS=$'\t' read -r ROUTINE_PROFILE CODEX_SANDBOX ATELIER_ACCESS_MODE WEB_SEARCH_MODE SHELL_NETWORK_MODE USER_CONFIG_MODE ROUTINE_TIMEOUT_SECONDS REASONING_EFFORT PROFILE_FINGERPRINT PERMISSION_ALLOWLIST <<< "$PROFILE_RECORD"
if [ -z "$ROUTINE_PROFILE" ] || [ -z "$CODEX_SANDBOX" ] || [ -z "$ATELIER_ACCESS_MODE" ] || [ -z "$WEB_SEARCH_MODE" ] || [ -z "$SHELL_NETWORK_MODE" ] || [ -z "$USER_CONFIG_MODE" ] || [ -z "$ROUTINE_TIMEOUT_SECONDS" ] || [ -z "$REASONING_EFFORT" ] || [ -z "$PROFILE_FINGERPRINT" ] || [ -z "$PERMISSION_ALLOWLIST" ]; then
    echo "ERROR: routine capability preflight returned an incomplete profile" >&2
    exit 2
fi
echo "[$(date -Iseconds)] preflight: profile=$ROUTINE_PROFILE sandbox=$CODEX_SANDBOX atelier_access=$ATELIER_ACCESS_MODE web=$WEB_SEARCH_MODE shell_network=$SHELL_NETWORK_MODE user_config=$USER_CONFIG_MODE permissions=$PERMISSION_ALLOWLIST timeout=${ROUTINE_TIMEOUT_SECONDS}s reasoning=$REASONING_EFFORT"

CAFFEINATE_PID=""
if [ "${ATELIER_SKIP_CAFFEINATE:-0}" != "1" ]; then
    if ! command -v caffeinate >/dev/null 2>&1; then
        write_failure_diagnostic "wake-assertion" '"caffeinate-not-found"'
        echo "ERROR: caffeinate is required for local routine execution." >&2
        exit 2
    fi
    caffeinate -i -w "$$" >/dev/null 2>&1 &
    CAFFEINATE_PID=$!
    echo "[$(date -Iseconds)] wake assertion: active"
fi

# --- stagger (hostname-based, 0-120s) ------------------------------------

if [ "${ATELIER_SKIP_STAGGER:-0}" != "1" ]; then
    HASH=$(echo -n "$(hostname)" | cksum | awk '{print $1}')
    DELAY=$((HASH % 120))
    echo "[$(date -Iseconds)] stagger: sleeping ${DELAY}s (hostname=$(hostname))"
    sleep "$DELAY"
fi

# --- DynamoDB lock --------------------------------------------------------
# Credentials come from a dedicated non-interactive AWS profile that boto3
# reads straight from ~/.aws/credentials. No aws-vault, no macOS Keychain:
# the Keychain is locked when the screen is locked at 05:00, which is what
# silently broke earlier runs. The profile is scoped to DynamoDB
# {Get,Put,Update}Item on the lock table only. One-time setup lives in
# scripts/launchd/README.md § Step 2.

LOCK_CMD=(uv run --directory "$ATELIER_DIR" python3 "$SCRIPTS_DIR/routine_lock.py")
LOCK_WITH_TIMEOUT=("${TIMEOUT_CMD[@]}" "${LOCK_CMD[@]}")

release_lock() {
    if ! RELEASE_RESULT=$("${LOCK_WITH_TIMEOUT[@]}" release "$ROUTINE" --cycle "$CYCLE" 2>&1); then
        return 1
    fi
    printf '%s' "$RELEASE_RESULT" | python3 -c '
import json, sys
value = json.load(sys.stdin)
valid = (
    value.get("released") is True
    and value.get("coordination") == sys.argv[2]
    and value.get("cycle") == sys.argv[1]
)
raise SystemExit(0 if valid else 1)
' "$CYCLE" "$COORD_MODE"
}

# Read the backend without opening a DynamoDB client so the dedicated AWS
# profile can be set before the first network operation.
COORD_MODE=$("${LOCK_WITH_TIMEOUT[@]}" backend | python3 -c "import sys,json; print(json.load(sys.stdin).get('coordination',''))")

if [ "$COORD_MODE" = "dynamodb" ]; then
    # boto3 resolves this profile from ~/.aws/credentials with zero prompts.
    export AWS_PROFILE="${ATELIER_LOCK_AWS_PROFILE:-atelier-lock}"
fi

LOCK_RESULT=$("${LOCK_WITH_TIMEOUT[@]}" acquire "$ROUTINE" --cycle "$CYCLE" 2>&1) || LOCK_EXIT=$?
LOCK_EXIT=${LOCK_EXIT:-0}

echo "[$(date -Iseconds)] lock acquire: exit=$LOCK_EXIT result=$LOCK_RESULT"

if [ "$LOCK_EXIT" -eq 1 ]; then
    if ! printf '%s' "$LOCK_RESULT" | python3 -c '
import json, sys
value = json.load(sys.stdin)
valid = (
    value.get("acquired") is False
    and value.get("coordination") == sys.argv[2]
    and value.get("cycle") == sys.argv[1]
)
raise SystemExit(0 if valid else 1)
' "$CYCLE" "$COORD_MODE"; then
        SAFE_RESULT=$(printf '%s' "$LOCK_RESULT" | python3 -c 'import json, sys; print(json.dumps("invalid-lock-contention-result: " + sys.stdin.read().replace("\n", " ")))')
        write_failure_diagnostic "lock-acquire" "$SAFE_RESULT"
        echo "[$(date -Iseconds)] ERROR: lock acquire exited 1 without a valid contention result" >&2
        exit 2
    fi
    # Genuine contention: another machine owns this cycle and will write the
    # shared output plus its own claim under $OV. Stand down cleanly; do NOT
    # write a claim here (the holder's claim covers the session cue check).
    echo "[$(date -Iseconds)] skipping: lock held by another machine"
    exit 0
fi

if [ "$LOCK_EXIT" -ne 0 ]; then
    # 2 = credential / DynamoDB failure; anything else (127 = uv missing from
    # the launchd PATH, etc.) is equally unknown lock state — fail CLOSED, not
    # open. Record a machine-specific diagnostic instead of touching the
    # canonical cycle claim, which may belong to another machine.
    SAFE_RESULT=$(printf '%s' "$LOCK_RESULT" | python3 -c 'import json, sys; print(json.dumps("lock-acquire-failed: " + sys.stdin.read().replace("\n", " ")))')
    write_failure_diagnostic "lock-acquire" "$SAFE_RESULT"
    echo "[$(date -Iseconds)] ERROR: lock acquire failed (credentials or DynamoDB). Fix before retrying." >&2
    exit 2
fi

if ! LOCK_METADATA=$(printf '%s' "$LOCK_RESULT" | python3 -c '
import json, sys
value = json.load(sys.stdin)
if (
    value.get("acquired") is not True
    or value.get("coordination") != sys.argv[2]
    or value.get("cycle") != sys.argv[1]
):
    raise SystemExit(1)
print("true" if value.get("retry_authorized") is True else "false")
print("true" if value.get("claim_reserved") is True else "false")
' "$CYCLE" "$COORD_MODE"); then
    SAFE_RESULT=$(printf '%s' "$LOCK_RESULT" | python3 -c 'import json, sys; print(json.dumps("invalid-lock-success-result: " + sys.stdin.read().replace("\n", " ")))')
    write_failure_diagnostic "lock-acquire" "$SAFE_RESULT"
    echo "[$(date -Iseconds)] ERROR: lock acquire succeeded without valid JSON attestation" >&2
    exit 2
fi
LOCK_RETRY_AUTHORIZED=$(printf '%s\n' "$LOCK_METADATA" | sed -n '1p')
LOCK_CLAIM_RESERVED=$(printf '%s\n' "$LOCK_METADATA" | sed -n '2p')

if [ "$COORD_MODE" != "owner" ] && [ "$LOCK_CLAIM_RESERVED" != "true" ] && [ "$LOCK_RETRY_AUTHORIZED" != "true" ] && [ -f "$CLAIM_FILE" ]; then
    if ! EXISTING_STATUS=$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb")).get("status", ""))' "$CLAIM_FILE"); then
        write_failure_diagnostic "claim-read" '"canonical-claim-is-not-valid-toml"'
        echo "[$(date -Iseconds)] ERROR: canonical claim is not valid TOML; lock retained" >&2
        exit 2
    fi
    case "$EXISTING_STATUS" in
        running|completed|failed|completion-uncertain)
            echo "[$(date -Iseconds)] skipping: canonical cycle claim is already $EXISTING_STATUS"
            if [ "$COORD_MODE" = "dynamodb" ] && [ "$EXISTING_STATUS" != "completed" ]; then
                echo "[$(date -Iseconds)] lock retained pending explicit cycle recovery"
                exit 0
            fi
            if ! release_lock; then
                echo "ERROR: could not release lock after duplicate-claim skip" >&2
                exit 2
            fi
            exit 0
            ;;
        deferred|retry-approved)
            ;;
        *)
            write_failure_diagnostic "claim-read" '"unknown-canonical-claim-status"'
            echo "[$(date -Iseconds)] ERROR: canonical claim has an unknown status; lock retained" >&2
            exit 2
            ;;
    esac
fi
if [ "$COORD_MODE" = "owner" ]; then
    LOCK_GENERATION=$(printf '%s' "$LOCK_RESULT" | python3 -c 'import json, sys; value=json.load(sys.stdin).get("generation"); print(value if isinstance(value, int) else "")')
    if [ -z "$LOCK_GENERATION" ]; then
        echo "ERROR: owner lock acquisition omitted its generation" >&2
        exit 2
    fi
    OWNER_GENERATION="$LOCK_GENERATION"
fi

# --- write local claim file -----------------------------------------------

CLAIMED_AT="$(date -Iseconds)"
CLAIM_EVENT_FIELD=""
if [ "$ROUTINE" = "autoevo-nightly" ]; then
    AUTOEVO_EVENT_LOG=$(mktemp "$OV/cache/autoevo-runner-${CYCLE}.log.XXXXXX")
    AUTOEVO_EVENT_LOG_REL="${AUTOEVO_EVENT_LOG#$OV/}"
    AUTOEVO_EVENT_LOG_TOML=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$AUTOEVO_EVENT_LOG_REL")
    CLAIM_EVENT_FIELD=$(printf 'event_log = %s' "$AUTOEVO_EVENT_LOG_TOML")
fi

write_claim <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
contract_version = 2
profile = "$ROUTINE_PROFILE"
profile_fingerprint = "$PROFILE_FINGERPRINT"
runtime = "$RUNTIME"
atelier_access = "$ATELIER_ACCESS_MODE"
shell_network = "$SHELL_NETWORK_MODE"
owner_generation = $OWNER_GENERATION
retry_authorized = $LOCK_RETRY_AUTHORIZED
claimed_at = "$CLAIMED_AT"
status = "running"
$CLAIM_EVENT_FIELD
EOF

runner_event "claimed: $CLAIM_FILE"

# A shell-level failure (including `set -u` or an unexpected helper exit) can
# otherwise bypass the normal completion block and leave a false `running`
# claim forever. Mark it failed on any nonzero exit after claim creation.
RUN_FINALIZED=0
ROUTINE_CWD=""
ROUTINE_RESULT_FILE=""
finalize_unexpected_exit() {
    local exit_code=$?
    if [ "$RUN_FINALIZED" = "0" ] && [ "$exit_code" -ne 0 ]; then
        set +e
        write_claim <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
contract_version = 2
profile = "$ROUTINE_PROFILE"
profile_fingerprint = "$PROFILE_FINGERPRINT"
runtime = "$RUNTIME"
atelier_access = "$ATELIER_ACCESS_MODE"
shell_network = "$SHELL_NETWORK_MODE"
owner_generation = $OWNER_GENERATION
retry_authorized = $LOCK_RETRY_AUTHORIZED
claimed_at = "$CLAIMED_AT"
status = "failed"
completed_at = "$(date -Iseconds)"
error = "runner-exited-unexpectedly"
exit_code = $exit_code
$CLAIM_EVENT_FIELD
EOF
        echo "[$(date -Iseconds)] ERROR: unexpected runner exit=$exit_code; claim marked failed" >&2
    fi
    if [ -n "$ROUTINE_CWD" ]; then
        python3 -c 'import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$ROUTINE_CWD"
    fi
    if [ -n "$ROUTINE_RESULT_FILE" ] && [ -f "$ROUTINE_RESULT_FILE" ]; then
        python3 -c 'from pathlib import Path; import sys; Path(sys.argv[1]).unlink(missing_ok=True)' "$ROUTINE_RESULT_FILE"
    fi
    if [ -n "$CAFFEINATE_PID" ]; then
        kill "$CAFFEINATE_PID" 2>/dev/null || true
        wait "$CAFFEINATE_PID" 2>/dev/null || true
    fi
}
trap finalize_unexpected_exit EXIT

# A cooperative transfer should not proceed while this running claim is
# synchronized. Recheck the generation immediately before model execution to
# fence a transfer already visible on this machine.
if [ "$COORD_MODE" = "owner" ]; then
    CURRENT_OWNER_RESULT=$("${TIMEOUT_CMD[@]}" python3 "$SCRIPTS_DIR/routine_owner.py" check --json)
    CURRENT_OWNER_GENERATION=$(printf '%s' "$CURRENT_OWNER_RESULT" | python3 -c 'import json, sys; value=json.load(sys.stdin).get("generation"); print(value if isinstance(value, int) else "")')
    if [ -z "$CURRENT_OWNER_GENERATION" ] || [ "$CURRENT_OWNER_GENERATION" != "$OWNER_GENERATION" ]; then
        echo "ERROR: local routine ownership changed before execution" >&2
        exit 2
    fi
fi

# Autoevo's safety gates are deterministic and must complete before the model
# is started. This fast path produces the same canonical audit artifact and a
# validated noop result, then leaves the claim in `deferred` so a later
# calendar trigger or RunAtLoad catch-up can retry without operator recovery.
# The command repeats the gates after model launch as defense in depth.
if [ "$ROUTINE" = "autoevo-nightly" ] && [ "${DRY_RUN:-0}" != "1" ]; then
    FAST_PREFLIGHT_STARTED_AT=$(date +%s)
    FAST_RESULT_FILE=$(mktemp "${TMPDIR:-/tmp}/atelier-autoevo-preflight-result.XXXXXX")
    ROUTINE_RESULT_FILE="$FAST_RESULT_FILE"
    if ! FAST_PREFLIGHT_JSON=$(python3 "$SCRIPTS_DIR/autoevo_preflight.py" \
        --record-blocker \
        --result-file "$FAST_RESULT_FILE" \
        --run-date "$CYCLE" \
        --cycle "$CYCLE" \
        --json); then
        echo "ERROR: deterministic autoevo preflight failed: $FAST_PREFLIGHT_JSON" >&2
        exit 2
    fi
    FAST_PREFLIGHT_READY=$(printf '%s' "$FAST_PREFLIGHT_JSON" | python3 -c '
import json, sys
value = json.load(sys.stdin).get("ready")
if value is True:
    print("true")
elif value is False:
    print("false")
else:
    raise SystemExit("preflight JSON omitted boolean ready")
')
    if [ "$FAST_PREFLIGHT_READY" = "false" ]; then
        FAST_GATE=$(printf '%s' "$FAST_PREFLIGHT_JSON" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("gate", "unknown"))')
        FAST_AUDIT_COMMIT=$(printf '%s' "$FAST_PREFLIGHT_JSON" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("audit_commit", "unknown"))')
        FAST_RETRY_AFTER_EPOCH=$(printf '%s' "$FAST_PREFLIGHT_JSON" | python3 -c '
import json, sys
value = json.load(sys.stdin).get("retry_after_epoch")
if isinstance(value, bool) or not isinstance(value, int) or value < 0:
    raise SystemExit("preflight JSON omitted a valid retry_after_epoch")
print(value)
')
        if [ "$FAST_AUDIT_COMMIT" = "reused" ]; then
            RUN_OUTCOME="noop"
            RUN_OUTPUT_FILE=$(printf '%s' "$FAST_PREFLIGHT_JSON" | python3 -c 'import json, sys; print(json.load(sys.stdin)["output_file"])')
        else
            if ! RESULT_ATTESTATION=$(python3 "$SCRIPTS_DIR/routine_result.py" "$ROUTINE" \
                --cycle "$CYCLE" \
                --claimed-at "$CLAIMED_AT" \
                --result-file "$FAST_RESULT_FILE" 2>&1); then
                echo "ERROR: deterministic preflight audit failed delivery attestation: $RESULT_ATTESTATION" >&2
                exit 2
            fi
            RUN_OUTCOME=$(printf '%s' "$RESULT_ATTESTATION" | python3 -c 'import json, sys; print(json.load(sys.stdin)["outcome"])')
            RUN_OUTPUT_FILE=$(printf '%s' "$RESULT_ATTESTATION" | python3 -c 'import json, sys; print(json.load(sys.stdin)["output_file"])')
        fi
        FAST_PREFLIGHT_ENDED_AT=$(date +%s)
        FAST_PREFLIGHT_DURATION=$(( FAST_PREFLIGHT_ENDED_AT - FAST_PREFLIGHT_STARTED_AT ))
        if ! release_lock; then
            echo "ERROR: deterministic preflight completed but lock release failed: $RELEASE_RESULT" >&2
            exit 2
        fi
        FAST_GATE_TOML=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$FAST_GATE")
        RUN_OUTCOME_TOML=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$RUN_OUTCOME")
        RUN_OUTPUT_FILE_TOML=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$RUN_OUTPUT_FILE")
        write_claim <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
contract_version = 2
profile = "$ROUTINE_PROFILE"
profile_fingerprint = "$PROFILE_FINGERPRINT"
runtime = "$RUNTIME"
atelier_access = "$ATELIER_ACCESS_MODE"
shell_network = "$SHELL_NETWORK_MODE"
owner_generation = $OWNER_GENERATION
retry_authorized = $LOCK_RETRY_AUTHORIZED
claimed_at = "$CLAIMED_AT"
status = "deferred"
deferred_at = "$(date -Iseconds)"
duration_seconds = $FAST_PREFLIGHT_DURATION
outcome = $RUN_OUTCOME_TOML
output_file = $RUN_OUTPUT_FILE_TOML
blocker = $FAST_GATE_TOML
retry_scheduled = true
retry_after_epoch = $FAST_RETRY_AFTER_EPOCH
$CLAIM_EVENT_FIELD
EOF
        RUN_FINALIZED=1
        runner_event "autoevo deferred before model launch: blocker=$FAST_GATE duration=${FAST_PREFLIGHT_DURATION}s"
        runner_event "delivery validated: outcome=$RUN_OUTCOME output=$RUN_OUTPUT_FILE"
        exit 0
    fi
    python3 -c 'from pathlib import Path; import sys; Path(sys.argv[1]).unlink(missing_ok=True)' "$FAST_RESULT_FILE"
    ROUTINE_RESULT_FILE=""
    runner_event "deterministic autoevo preflight passed"
fi

# --- execute routine ------------------------------------------------------

# Codex does not expose bot-only commands as user skills. Resolve the command
# through the portable registry, then give `codex exec` a bounded adapter
# prompt that tells it to read and execute the authoritative command source.
run_codex() {
    local command_expr command_name command_arg command_record command_source codex_hint codex_prompt
    local prompt_file
    local env_name
    local -a codex_env codex_global_args codex_exec_args

    if ! command -v codex >/dev/null 2>&1; then
        echo "ERROR: codex not found on PATH" >&2
        return 127
    fi

    command_expr="${COMMAND#/}"
    command_name="${command_expr%% *}"
    command_arg=""
    if [[ "$command_expr" == *" "* ]]; then
        command_arg="${command_expr#* }"
    fi
    if [ "$command_expr" = "$COMMAND" ] || [ -z "$command_name" ]; then
        echo "ERROR: Codex scheduled commands must use /<command> form: $COMMAND" >&2
        return 2
    fi

    if ! command_record=$(uv run --quiet --directory "$ATELIER_DIR" python3 -c '
import pathlib, sys, tomllib

registry_path = pathlib.Path(sys.argv[1])
command_name = sys.argv[2]
commands = tomllib.loads(registry_path.read_text()).get("commands", {})
row = commands.get(command_name)
if not isinstance(row, dict):
    raise SystemExit(f"command not registered: {command_name}")
source = row.get("source")
prompt = row.get("codex_prompt")
if not isinstance(source, str) or not isinstance(prompt, str):
    raise SystemExit(f"command missing source/codex_prompt: {command_name}")
if any(ch in source or ch in prompt for ch in ("\t", "\n")):
    raise SystemExit(f"command metadata must be single-line: {command_name}")
print(f"{source}\t{prompt}")
' "$ATELIER_DIR/harness/commands.toml" "$command_name"); then
        echo "ERROR: failed to resolve Codex command metadata: $command_name" >&2
        return 2
    fi

    IFS=$'\t' read -r command_source codex_hint <<< "$command_record"
    if [ ! -f "$ATELIER_DIR/$command_source" ]; then
        echo "ERROR: registered command source not found: $command_source" >&2
        return 2
    fi

    if [ "$command_name" = "run-routine" ]; then
        if [ -z "$command_arg" ] || [ "$command_arg" != "$ROUTINE" ]; then
            echo "ERROR: /run-routine argument must match routine name: $ROUTINE" >&2
            return 2
        fi
        prompt_file="$OV/_routine_prompts/$command_arg.md"
        if ! "${TIMEOUT_CMD[@]}" python3 "$SCRIPTS_DIR/routine_prompt_guard.py" "$prompt_file"; then
            echo "ERROR: private routine prompt failed preflight: $prompt_file" >&2
            return 2
        fi
    fi

    printf -v codex_prompt '%s\n\nThis is an unattended local Atelier routine, not an interactive user command. Invocation: `%s`. The wrapper has already completed owner, support, capability, dependency, launchd, and credential-guard preflight with profile `%s` (sandbox=%s, atelier_access=%s, web=%s, shell_network=%s, user_config=%s). Effective action permission allowlist: `%s`. Treat it as a strict model-level allowlist: skip every connector, CLI, web, or filesystem action not listed, even if an optional integration is installed. This is not a shell-level connector ACL. Read `%s/AGENTS.md` and `%s/CLAUDE.md` first, then read `%s/%s` completely and execute it in this process using the Codex adaptation table. Treat the Atelier repository as read-only unless atelier_access is read-write. Do not re-audit routine_profiles.toml, routine_runner.sh, remote-routines.md, launchd state, or the private watch registry; trust the wrapper preflight. This is operational work, not user-facing reflection; load only files required by the command and archived prompt after the mandatory session-start reads. The scheduled invocation authorizes only the autonomous writes and commits explicitly allowed by that command contract. Do not ask for interactive input. Ignore unrelated SessionStart cues. Stop safely if the command requires authority it does not grant. The final response must contain only JSON matching the supplied schema. Set outcome to delivered only after writing the canonical output artifact, noop only for an intentional documented no-op that still writes its audit artifact, or failed if the routine stops without a valid artifact. Report the canonical artifact path in output_file for delivered and noop outcomes.' "$codex_hint" "$COMMAND" "$ROUTINE_PROFILE" "$CODEX_SANDBOX" "$ATELIER_ACCESS_MODE" "$WEB_SEARCH_MODE" "$SHELL_NETWORK_MODE" "$USER_CONFIG_MODE" "$PERMISSION_ALLOWLIST" "$ATELIER_DIR" "$ATELIER_DIR" "$ATELIER_DIR" "$command_source"

    # The resolved capability profile supplies the least-privilege sandbox,
    # web mode, and user-config policy. Maintenance work that must commit gets
    # danger-full-access; ordinary routines get workspace-write plus $OV.
    # Project hooks are trusted only for the maintenance profile rooted in the
    # Atelier checkout. Ordinary vault-rooted routines do not load repo hooks.
    # Keep the model-facing shell environment narrow. The lock step may have
    # loaded unrelated credentials from login profiles, and autoevo does not
    # need them. Preserve only runtime paths, vault routing, hook guards, and
    # optional Codex location / CA settings needed to reach cached login and
    # installed connectors.
    codex_env=(
        env -i
        "HOME=$HOME"
        "PATH=$PATH"
        "OV=$OV"
        "ZDOTDIR=$ATELIER_DIR/harness/routine-shell"
        "TMPDIR=${TMPDIR:-/tmp}"
        "LANG=${LANG:-en_US.UTF-8}"
        "ATELIER_ACTIVE_RUNTIME=codex"
        "ATELIER_ROUTINE_CYCLE=$CYCLE"
        "ATELIER_ROUTINE_PROFILE=$ROUTINE_PROFILE"
        "ATELIER_ROUTINE_PERMISSIONS=$PERMISSION_ALLOWLIST"
        "ATELIER_SKIP_LOCK_TOUCH=1"
    )
    for env_name in DRY_RUN CODEX_HOME CODEX_CA_CERTIFICATE SSL_CERT_FILE; do
        if [ -n "${!env_name:-}" ]; then
            codex_env+=("$env_name=${!env_name}")
        fi
    done

    if [ "$WEB_SEARCH_MODE" = "live" ]; then
        codex_global_args=(
            -c 'approval_policy="never"'
            -c "model_reasoning_effort=\"$REASONING_EFFORT\""
            --search
        )
    else
        codex_global_args=(
            -c 'approval_policy="never"'
            -c "model_reasoning_effort=\"$REASONING_EFFORT\""
            -c 'web_search="disabled"'
        )
    fi

    if [ "$CODEX_SANDBOX" = "workspace-write" ]; then
        if [ "$SHELL_NETWORK_MODE" = "enabled" ]; then
            codex_global_args+=(
                -c 'sandbox_workspace_write.network_access=true'
            )
        else
            codex_global_args+=(
                -c 'sandbox_workspace_write.network_access=false'
            )
        fi
    fi

    codex_exec_args=(
        --sandbox "$CODEX_SANDBOX"
        --ephemeral
        --color never
        --output-schema "$ATELIER_DIR/harness/routine_result.schema.json"
    )
    ROUTINE_RESULT_FILE=$(mktemp "${TMPDIR:-/tmp}/atelier-routine-result.XXXXXX")
    codex_exec_args+=(--output-last-message "$ROUTINE_RESULT_FILE")
    if [ "$ATELIER_ACCESS_MODE" = "read-write" ]; then
        codex_exec_args+=(--dangerously-bypass-hook-trust --add-dir "$OV" -C "$ATELIER_DIR")
    else
        ROUTINE_CWD=$(mktemp -d "${TMPDIR:-/tmp}/atelier-routine-cwd.XXXXXX")
        codex_exec_args+=(--skip-git-repo-check --add-dir "$OV" -C "$ROUTINE_CWD")
    fi
    if [ "$USER_CONFIG_MODE" = "ignore" ]; then
        codex_exec_args=(--ignore-user-config "${codex_exec_args[@]}")
    fi

    python3 "$SCRIPTS_DIR/command_timeout.py" --seconds "$ROUTINE_TIMEOUT_SECONDS" -- \
        "${codex_env[@]}" codex "${codex_global_args[@]}" --ask-for-approval never exec \
        "${codex_exec_args[@]}" \
        "$codex_prompt"
}

runner_event "starting: runtime=$RUNTIME command=$COMMAND"
STARTED_AT=$(date +%s)
export ATELIER_ACTIVE_RUNTIME="$RUNTIME"

cd "$ATELIER_DIR"
MODEL_EXIT_CODE=0
RUN_STATUS="failed"
RUN_OUTCOME="failed"
RUN_OUTPUT_FILE=""
RUN_ERROR="model-execution-failed"
if run_codex 2>&1; then
    if RESULT_ATTESTATION=$(python3 "$SCRIPTS_DIR/routine_result.py" "$ROUTINE" \
        --cycle "$CYCLE" \
        --claimed-at "$CLAIMED_AT" \
        --result-file "$ROUTINE_RESULT_FILE" 2>&1); then
        RUN_STATUS="completed"
        RUN_OUTCOME=$(printf '%s' "$RESULT_ATTESTATION" | python3 -c 'import json, sys; print(json.load(sys.stdin)["outcome"])')
        RUN_OUTPUT_FILE=$(printf '%s' "$RESULT_ATTESTATION" | python3 -c 'import json, sys; print(json.load(sys.stdin)["output_file"])')
        RUN_ERROR=""
        runner_event "delivery validated: outcome=$RUN_OUTCOME output=$RUN_OUTPUT_FILE"
    else
        RUN_ERROR="delivery-attestation-failed"
        echo "[$(date -Iseconds)] ERROR: delivery validation failed: $RESULT_ATTESTATION" >&2
    fi
else
    MODEL_EXIT_CODE=$?
fi

ENDED_AT=$(date +%s)
DURATION=$(( ENDED_AT - STARTED_AT ))

runner_event "finished: status=$RUN_STATUS duration=${DURATION}s"

# --- release lock + update claim file ------------------------------------

COMPLETED_AT="$(date -Iseconds)"

if [ "$RUN_STATUS" = "completed" ]; then
    if release_lock; then
        runner_event "lock release: $RELEASE_RESULT"
    else
        RUN_STATUS="completion-uncertain"
        RUN_ERROR="lock-release-failed"
        echo "[$(date -Iseconds)] ERROR: model completed but lock release failed: $RELEASE_RESULT" >&2
    fi
fi

if [ "$RUN_STATUS" = "completed" ] || [ "$RUN_STATUS" = "completion-uncertain" ]; then
    RUN_OUTCOME_TOML=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$RUN_OUTCOME")
    RUN_OUTPUT_FILE_TOML=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$RUN_OUTPUT_FILE")
    FINAL_DETAILS=$(printf 'outcome = %s\noutput_file = %s' "$RUN_OUTCOME_TOML" "$RUN_OUTPUT_FILE_TOML")
else
    RUN_ERROR_TOML=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$RUN_ERROR")
    FINAL_DETAILS=$(printf 'error = %s\nmodel_exit_code = %s' "$RUN_ERROR_TOML" "$MODEL_EXIT_CODE")
fi

CLAIM_STATUS="$RUN_STATUS"
VERIFICATION_FIELD=""
if [ "$ROUTINE" = "autoevo-nightly" ] && [ "$RUN_STATUS" = "completed" ]; then
    CLAIM_STATUS="completion-uncertain"
    VERIFICATION_FIELD='verification = "pending"'
fi

write_claim <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
contract_version = 2
profile = "$ROUTINE_PROFILE"
profile_fingerprint = "$PROFILE_FINGERPRINT"
runtime = "$RUNTIME"
atelier_access = "$ATELIER_ACCESS_MODE"
shell_network = "$SHELL_NETWORK_MODE"
owner_generation = $OWNER_GENERATION
retry_authorized = $LOCK_RETRY_AUTHORIZED
claimed_at = "$CLAIMED_AT"
status = "$CLAIM_STATUS"
completed_at = "$COMPLETED_AT"
duration_seconds = $DURATION
$FINAL_DETAILS
$CLAIM_EVENT_FIELD
$VERIFICATION_FIELD
EOF

if [ "$RUN_STATUS" = "completed" ]; then
    if [ "$ROUTINE" = "autoevo-nightly" ]; then
        if POST_VERIFY_JSON=$(python3 "$SCRIPTS_DIR/autoevo_verify.py" \
            --cycle "$CYCLE" \
            --wrapper-log "$AUTOEVO_EVENT_LOG" \
            --allow-pending-claim \
            --json); then
            VERIFIED_SWEEPS=$(printf '%s' "$POST_VERIFY_JSON" | python3 -c 'import json, sys; print(json.load(sys.stdin)["sweeps_completed"])')
            VERIFICATION_COMMIT=$(printf '%s' "$POST_VERIFY_JSON" | python3 -c 'import json, sys; print(json.load(sys.stdin)["audit_commit"])')
            VERIFIED_AT="$(date -Iseconds)"
            write_claim <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
contract_version = 2
profile = "$ROUTINE_PROFILE"
profile_fingerprint = "$PROFILE_FINGERPRINT"
runtime = "$RUNTIME"
atelier_access = "$ATELIER_ACCESS_MODE"
shell_network = "$SHELL_NETWORK_MODE"
owner_generation = $OWNER_GENERATION
retry_authorized = $LOCK_RETRY_AUTHORIZED
claimed_at = "$CLAIMED_AT"
status = "completed"
completed_at = "$COMPLETED_AT"
duration_seconds = $DURATION
$FINAL_DETAILS
$CLAIM_EVENT_FIELD
verification = "passed"
verified_at = "$VERIFIED_AT"
verified_sweeps = $VERIFIED_SWEEPS
verification_commit = "$VERIFICATION_COMMIT"
EOF
            runner_event "post-run verification passed: sweeps=$VERIFIED_SWEEPS commit=$VERIFICATION_COMMIT"
        else
            POST_VERIFY_ERROR=$(printf '%s' "$POST_VERIFY_JSON" | python3 -c '
import json, sys
try:
    value = json.load(sys.stdin)
except json.JSONDecodeError:
    print("autoevo verifier returned invalid output")
else:
    print(value.get("error", "autoevo verifier failed without an error"))
')
            POST_VERIFY_ERROR_TOML=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$POST_VERIFY_ERROR")
            write_claim <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
contract_version = 2
profile = "$ROUTINE_PROFILE"
profile_fingerprint = "$PROFILE_FINGERPRINT"
runtime = "$RUNTIME"
atelier_access = "$ATELIER_ACCESS_MODE"
shell_network = "$SHELL_NETWORK_MODE"
owner_generation = $OWNER_GENERATION
retry_authorized = $LOCK_RETRY_AUTHORIZED
claimed_at = "$CLAIMED_AT"
status = "completion-uncertain"
completed_at = "$COMPLETED_AT"
duration_seconds = $DURATION
$FINAL_DETAILS
$CLAIM_EVENT_FIELD
error = "post-run-verification-failed"
verification = "failed"
verification_detail = $POST_VERIFY_ERROR_TOML
EOF
            RUN_FINALIZED=1
            runner_event "ERROR: post-run verification failed: $POST_VERIFY_ERROR"
            exit 2
        fi
    fi
    RUN_FINALIZED=1
    runner_event "done: claim updated, lock released"
    exit 0
fi

RUN_FINALIZED=1
if [ "$RUN_STATUS" = "completion-uncertain" ]; then
    echo "[$(date -Iseconds)] done: claim records completion uncertainty; lock was not released" >&2
    exit 2
fi
echo "[$(date -Iseconds)] done: claim updated, lock retained after failure" >&2
exit 1
