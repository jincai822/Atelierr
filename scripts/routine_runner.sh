#!/bin/bash
# routine_runner.sh — Wrapper for scheduled local routines.
#
# Invoked by launchd. Handles:
#   1. Environment setup ($OV, PATH)
#   2. Hostname-based stagger (0-120s) to reduce race probability
#   3. DynamoDB lock acquire (skip if another machine claimed this cycle)
#   4. Local claim file write ($OV/_meta/routine_runs/<routine>/<cycle>.toml)
#   5. claude -p "/<command>" execution
#   6. Lock release + claim file update
#
# Usage:
#   routine_runner.sh <routine-name> <command>
#   routine_runner.sh autoevo-nightly /autoevo-nightly
#
# Environment:
#   OV                       — vault root (required)
#   ATELIER_SKIP_LOCK_TOUCH  — set by this script; prevents session hooks
#                               from touching the session-active lock
#   ATELIER_COORDINATION     — override coordination mode (default: reads
#                               from routine_watch.toml; "none" skips DynamoDB)
#   ATELIER_SKIP_STAGGER     — set to 1 to skip the hostname stagger (for
#                               manual test runs via launchctl start)

set -euo pipefail

ROUTINE="${1:?Usage: routine_runner.sh <routine-name> <command>}"
COMMAND="${2:?Usage: routine_runner.sh <routine-name> <command>}"
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

# Claude Code's native installer puts `claude` in ~/.local/bin, which only
# ~/.zshrc (interactive-only) adds to PATH — not the login profiles sourced
# above. Without this, `claude -p` below is not found in the headless launchd
# environment and the routine fails after acquiring the lock. Prepend it.
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) [ -d "$HOME/.local/bin" ] && export PATH="$HOME/.local/bin:$PATH" ;;
esac

: "${OV:?ERROR: OV not set — export it from ~/.zprofile, ~/.profile, or ~/atelier/harness/env.local.sh}"

mkdir -p "$OV/cache" "$OV/_meta/routine_runs/$ROUTINE"

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
# {Get,Put,Update,Delete}Item on the lock table only. One-time setup lives in
# scripts/launchd/README.md § Step 2.

LOCK_PY="uv run --directory $ATELIER_DIR python3 $SCRIPTS_DIR/routine_lock.py"

# Coordination mode is read from routine_watch.toml; "none" skips creds entirely.
COORD_MODE=$($LOCK_PY status "$ROUTINE" --cycle "$CYCLE" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('coordination',''))" 2>/dev/null || echo "")

if [ "$COORD_MODE" != "none" ]; then
    # boto3 resolves this profile from ~/.aws/credentials with zero prompts.
    export AWS_PROFILE="${ATELIER_LOCK_AWS_PROFILE:-atelier-lock}"
fi
LOCK_CMD="$LOCK_PY"

CLAIM_DIR="$OV/_meta/routine_runs/$ROUTINE"
CLAIM_FILE="$CLAIM_DIR/$CYCLE.toml"
HOSTNAME="$(hostname)"

LOCK_RESULT=$($LOCK_CMD acquire "$ROUTINE" --cycle "$CYCLE" 2>&1) || LOCK_EXIT=$?
LOCK_EXIT=${LOCK_EXIT:-0}

echo "[$(date -Iseconds)] lock acquire: exit=$LOCK_EXIT result=$LOCK_RESULT"

if [ "$LOCK_EXIT" -eq 1 ]; then
    # Genuine contention: another machine owns this cycle and will write the
    # shared output plus its own claim under $OV. Stand down cleanly; do NOT
    # write a claim here (the holder's claim covers the session cue check).
    echo "[$(date -Iseconds)] skipping: lock held by another machine"
    exit 0
fi

if [ "$LOCK_EXIT" -eq 2 ]; then
    # Credential / DynamoDB failure. Fail LOUD: record a failed claim so the
    # session cue reports "failed (<reason>)" instead of the misleading
    # "no run today / machine asleep" default. Flatten + de-quote the reason
    # so the claim stays valid TOML.
    SAFE_RESULT=$(printf '%s' "$LOCK_RESULT" | tr '\n' ' ' | sed "s/\"/'/g")
    cat > "$CLAIM_FILE" <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
claimed_at = "$(date -Iseconds)"
status = "failed"
error = "lock-acquire-failed: $SAFE_RESULT"
EOF
    echo "[$(date -Iseconds)] ERROR: lock acquire failed (credentials or DynamoDB). Wrote failed claim. Fix before retrying." >&2
    exit 2
fi

# --- write local claim file -----------------------------------------------

CLAIMED_AT="$(date -Iseconds)"

cat > "$CLAIM_FILE" <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
claimed_at = "$CLAIMED_AT"
status = "running"
EOF

echo "[$(date -Iseconds)] claimed: $CLAIM_FILE"

# --- execute routine ------------------------------------------------------

echo "[$(date -Iseconds)] starting: claude -p \"$COMMAND\""
STARTED_AT=$(date +%s)

cd "$ATELIER_DIR"
if claude -p "$COMMAND" 2>&1; then
    RUN_STATUS="completed"
else
    RUN_STATUS="failed"
fi

ENDED_AT=$(date +%s)
DURATION=$(( ENDED_AT - STARTED_AT ))

echo "[$(date -Iseconds)] finished: status=$RUN_STATUS duration=${DURATION}s"

# --- update claim file + release lock ------------------------------------

COMPLETED_AT="$(date -Iseconds)"

cat > "$CLAIM_FILE" <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
claimed_at = "$CLAIMED_AT"
status = "$RUN_STATUS"
completed_at = "$COMPLETED_AT"
duration_seconds = $DURATION
EOF

if [ "$RUN_STATUS" = "completed" ]; then
    $LOCK_CMD release "$ROUTINE" --cycle "$CYCLE" 2>&1 || true
fi

echo "[$(date -Iseconds)] done: claim updated, lock released"
