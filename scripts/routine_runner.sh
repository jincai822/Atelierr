#!/bin/bash
# routine_runner.sh — Wrapper for scheduled local routines.
#
# Invoked by launchd. Handles:
#   1. Environment setup ($OV, PATH)
#   2. Hostname-based stagger (0-120s) to reduce race probability
#   3. DynamoDB lock acquire (skip if another machine claimed this cycle)
#   4. Local claim file write ($OV/_meta/routine_runs/<routine>/<cycle>.toml)
#   5. Headless execution through the selected native runtime
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
#   ATELIER_RUNTIME          : "codex" or "claude" (one-process override;
#                               otherwise use harness/runtime.local.toml, then
#                               the committed Codex default)

set -euo pipefail

ROUTINE="${1:?Usage: routine_runner.sh <routine-name> <command>}"
COMMAND="${2:?Usage: routine_runner.sh <routine-name> <command>}"
if [[ ! "$ROUTINE" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "ERROR: invalid routine name: $ROUTINE" >&2
    exit 2
fi
if [[ ! "$COMMAND" =~ ^/[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "ERROR: scheduled commands must use /<command> form: $COMMAND" >&2
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

RUNTIME_RESOLUTION_ERROR=""
if ! RUNTIME="$(python3 "$SCRIPTS_DIR/atelier_runtime.py" resolve 2>&1)"; then
    RUNTIME_RESOLUTION_ERROR="$RUNTIME"
    RUNTIME="unresolved"
fi

# Runtime installers may put their CLI in ~/.local/bin, which only ~/.zshrc
# (interactive-only) adds to PATH, not the login profiles sourced above.
# Prepend it so launchd sees the same executable as an interactive shell.
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) [ -d "$HOME/.local/bin" ] && export PATH="$HOME/.local/bin:$PATH" ;;
esac

: "${OV:?ERROR: OV not set — export it from ~/.zprofile, ~/.profile, or ~/atelier/harness/env.local.sh}"

mkdir -p "$OV/cache" "$OV/_meta/routine_runs/$ROUTINE"

CLAIM_DIR="$OV/_meta/routine_runs/$ROUTINE"
CLAIM_FILE="$CLAIM_DIR/$CYCLE.toml"
HOSTNAME="$(hostname)"

# A machine with an invalid local runtime preference must not claim the shared
# cycle and block another correctly configured machine until TTL. Record the
# local failure before coordination, then stand down without touching the lock.
if [ -n "$RUNTIME_RESOLUTION_ERROR" ]; then
    SAFE_RUNTIME_ERROR=$(printf '%s' "$RUNTIME_RESOLUTION_ERROR" | python3 -c 'import json, sys; print(json.dumps("runtime-resolution-failed: " + sys.stdin.read().replace("\n", " ")))')
    cat > "$CLAIM_FILE" <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
claimed_at = "$(date -Iseconds)"
status = "failed"
error = $SAFE_RUNTIME_ERROR
EOF
    echo "ERROR: could not resolve Atelier runtime: $RUNTIME_RESOLUTION_ERROR" >&2
    exit 2
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
# {Get,Put,Update,Delete}Item on the lock table only. One-time setup lives in
# scripts/launchd/README.md § Step 2.

LOCK_CMD=(uv run --directory "$ATELIER_DIR" python3 "$SCRIPTS_DIR/routine_lock.py")

# Coordination mode is read from routine_watch.toml; "none" skips creds entirely.
COORD_MODE=$("${LOCK_CMD[@]}" status "$ROUTINE" --cycle "$CYCLE" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('coordination',''))" 2>/dev/null || echo "")

if [ "$COORD_MODE" != "none" ]; then
    # boto3 resolves this profile from ~/.aws/credentials with zero prompts.
    export AWS_PROFILE="${ATELIER_LOCK_AWS_PROFILE:-atelier-lock}"
fi

LOCK_RESULT=$("${LOCK_CMD[@]}" acquire "$ROUTINE" --cycle "$CYCLE" 2>&1) || LOCK_EXIT=$?
LOCK_EXIT=${LOCK_EXIT:-0}

echo "[$(date -Iseconds)] lock acquire: exit=$LOCK_EXIT result=$LOCK_RESULT"

if [ "$LOCK_EXIT" -eq 1 ]; then
    # Genuine contention: another machine owns this cycle and will write the
    # shared output plus its own claim under $OV. Stand down cleanly; do NOT
    # write a claim here (the holder's claim covers the session cue check).
    echo "[$(date -Iseconds)] skipping: lock held by another machine"
    exit 0
fi

if [ "$LOCK_EXIT" -ne 0 ]; then
    # 2 = credential / DynamoDB failure; anything else (127 = uv missing from
    # the launchd PATH, etc.) is equally unknown lock state — fail CLOSED, not
    # open. Record a failed claim so the session cue reports "failed (<reason>)"
    # instead of the misleading "no run today / machine asleep" default.
    # Encode the flattened reason as a valid TOML basic string.
    SAFE_RESULT=$(printf '%s' "$LOCK_RESULT" | python3 -c 'import json, sys; print(json.dumps("lock-acquire-failed: " + sys.stdin.read().replace("\n", " ")))')
    cat > "$CLAIM_FILE" <<EOF
routine = "$ROUTINE"
cycle_id = "$CYCLE"
machine = "$HOSTNAME"
claimed_at = "$(date -Iseconds)"
status = "failed"
error = $SAFE_RESULT
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

# Codex does not expose bot-only commands as user skills. Resolve the command
# through the portable registry, then give `codex exec` a bounded adapter
# prompt that tells it to read and execute the authoritative command source.
run_codex() {
    local command_name command_record command_source codex_hint codex_prompt
    local env_name
    local -a codex_env

    if ! command -v codex >/dev/null 2>&1; then
        echo "ERROR: codex not found on PATH" >&2
        return 127
    fi

    command_name="${COMMAND#/}"
    if [ "$command_name" = "$COMMAND" ] || [ -z "$command_name" ]; then
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

    printf -v codex_prompt '%s\n\nThis is an unattended local Atelier routine, not an interactive user command. Read AGENTS.md and CLAUDE.md first, then read `%s` completely and execute it in this process using the Codex adaptation table. Read directly referenced protocol and role files as needed. The scheduled invocation authorizes only the autonomous writes and commits explicitly allowed by that command contract. Do not ask for interactive input. Ignore unrelated SessionStart cues. Stop safely if the command requires authority it does not grant. Return the command-required final summary.' "$codex_hint" "$command_source"

    # Autoevo requires per-operation commits to $OV. Codex workspace-write
    # protects every .git directory as read-only, so the scheduled bot needs
    # danger-full-access. The command contract supplies the narrower semantic
    # boundary: clean-tree and privacy gates, bounded sweep paths, no push, and
    # one recoverable commit per destructive operation. User config is ignored
    # for deterministic automation; project hooks remain enabled and are
    # explicitly trusted for this vetted local workflow.
    # Keep the model-facing shell environment narrow. The lock step may have
    # loaded unrelated credentials from login profiles, and autoevo does not
    # need them. Preserve only runtime paths, vault routing, hook guards, and
    # optional Codex location / CA settings needed to reach the cached login.
    codex_env=(
        env -i
        "HOME=$HOME"
        "PATH=$PATH"
        "OV=$OV"
        "TMPDIR=${TMPDIR:-/tmp}"
        "LANG=${LANG:-en_US.UTF-8}"
        "ATELIER_ACTIVE_RUNTIME=codex"
        "ATELIER_SKIP_LOCK_TOUCH=1"
    )
    for env_name in DRY_RUN CODEX_HOME CODEX_CA_CERTIFICATE SSL_CERT_FILE; do
        if [ -n "${!env_name:-}" ]; then
            codex_env+=("$env_name=${!env_name}")
        fi
    done

    "${codex_env[@]}" codex --ask-for-approval never exec \
        --ignore-user-config \
        --sandbox danger-full-access \
        --dangerously-bypass-hook-trust \
        --ephemeral \
        --color never \
        --add-dir "$OV" \
        -C "$ATELIER_DIR" \
        -c 'web_search="disabled"' \
        "$codex_prompt"
}

run_claude() {
    if ! command -v claude >/dev/null 2>&1; then
        echo "ERROR: claude not found on PATH" >&2
        return 127
    fi
    claude -p "$COMMAND"
}

echo "[$(date -Iseconds)] starting: runtime=$RUNTIME command=$COMMAND"
STARTED_AT=$(date +%s)
export ATELIER_ACTIVE_RUNTIME="$RUNTIME"

cd "$ATELIER_DIR"
case "$RUNTIME" in
    codex)
        if run_codex 2>&1; then
            RUN_STATUS="completed"
        else
            RUN_STATUS="failed"
        fi
        ;;
    claude)
        if run_claude 2>&1; then
            RUN_STATUS="completed"
        else
            RUN_STATUS="failed"
        fi
        ;;
    *)
        echo "ERROR: unsupported Atelier runtime=$RUNTIME (expected codex or claude)" >&2
        RUN_STATUS="failed"
        ;;
esac

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
    "${LOCK_CMD[@]}" release "$ROUTINE" --cycle "$CYCLE" 2>&1 || true
    echo "[$(date -Iseconds)] done: claim updated, lock released"
    exit 0
fi

echo "[$(date -Iseconds)] done: claim updated, lock retained until TTL after failure" >&2
exit 1
