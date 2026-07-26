#!/bin/bash
# Verify one local routine profile through a no-side-effect Codex invocation.

set -euo pipefail

SMOKE_ROUTINE="${1:?Usage: routine_profile_smoke.sh <routine-name>}"
if [[ ! "$SMOKE_ROUTINE" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "ERROR: invalid routine name: $SMOKE_ROUTINE" >&2
    exit 2
fi
LAUNCHD_LABEL="${ATELIER_PROFILE_SMOKE_LAUNCHER:-}"
if [ "$PPID" -ne 1 ] || [[ "$LAUNCHD_LABEL" != com.atelier.profile-smoke.* ]]; then
    echo "ERROR: profile smoke must run from a dedicated com.atelier.profile-smoke.* launchd job" >&2
    exit 2
fi

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
ATELIER_DIR="$(dirname "$SCRIPTS_DIR")"

set +eu
source "$HOME/.zprofile" 2>/dev/null || true
source "$HOME/.profile" 2>/dev/null || true
source "$ATELIER_DIR/harness/env.local.sh" 2>/dev/null || true
set -eu

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) [ -d "$HOME/.local/bin" ] && export PATH="$HOME/.local/bin:$PATH" ;;
esac

: "${OV:?ERROR: OV not set}"

SMOKE_TIMEOUT_SECONDS="${ATELIER_PROFILE_SMOKE_TIMEOUT_SECONDS:-180}"
TIMEOUT_CMD=(python3 "$SCRIPTS_DIR/command_timeout.py" --seconds "$SMOKE_TIMEOUT_SECONDS" --)

if ! "${TIMEOUT_CMD[@]}" python3 "$SCRIPTS_DIR/routine_owner.py" check >/dev/null; then
    echo "ERROR: this machine is not eligible to run local routine smoke" >&2
    exit 2
fi

if [ "$SMOKE_ROUTINE" = "autoevo-nightly" ]; then
    SMOKE_COMMAND="/autoevo-nightly"
else
    SMOKE_COMMAND="/run-routine $SMOKE_ROUTINE"
fi

if ! PROFILE_RECORD=$("${TIMEOUT_CMD[@]}" python3 "$SCRIPTS_DIR/routine_audit.py" \
    resolve "$SMOKE_ROUTINE" --surface local --check-system --runtime codex \
    --command "$SMOKE_COMMAND" --format tsv); then
    echo "ERROR: routine profile preflight failed: $SMOKE_ROUTINE" >&2
    exit 2
fi

IFS=$'\t' read -r ROUTINE_PROFILE CODEX_SANDBOX ATELIER_ACCESS_MODE WEB_SEARCH_MODE SHELL_NETWORK_MODE USER_CONFIG_MODE \
    ROUTINE_TIMEOUT_SECONDS REASONING_EFFORT PROFILE_FINGERPRINT PERMISSION_ALLOWLIST <<< "$PROFILE_RECORD"
if [ -z "$ROUTINE_PROFILE" ] || [ -z "$CODEX_SANDBOX" ] || \
    [ -z "$ATELIER_ACCESS_MODE" ] || [ -z "$WEB_SEARCH_MODE" ] || [ -z "$SHELL_NETWORK_MODE" ] || [ -z "$USER_CONFIG_MODE" ] || \
    [ -z "$REASONING_EFFORT" ] || [ -z "$PROFILE_FINGERPRINT" ] || [ -z "$PERMISSION_ALLOWLIST" ]; then
    echo "ERROR: incomplete routine profile record" >&2
    exit 2
fi

SMOKE_OUTPUT=$(mktemp "${TMPDIR:-/tmp}/atelier-profile-smoke-output.XXXXXX")
SMOKE_CWD=""
cleanup_smoke_output() {
    rm -f "$SMOKE_OUTPUT"
    if [ -n "$SMOKE_CWD" ]; then
        python3 -c 'import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$SMOKE_CWD"
    fi
}
trap cleanup_smoke_output EXIT

CLAIM_DIR="$OV/_meta/routine_profile_smokes/$ROUTINE_PROFILE"
mkdir -p "$CLAIM_DIR"
CLAIM_FILE="$CLAIM_DIR/$(date +%Y%m%dT%H%M%S)-$(hostname).toml"
CLAIMED_AT="$(date -Iseconds)"

write_claim() {
    local status="$1"
    local completed_at="$2"
    local duration="$3"
    cat > "$CLAIM_FILE" <<EOF
kind = "runtime-envelope"
contract_version = 2
routine = "$SMOKE_ROUTINE"
profile = "$ROUTINE_PROFILE"
profile_fingerprint = "$PROFILE_FINGERPRINT"
runtime = "codex"
machine = "$(hostname)"
launcher = "$LAUNCHD_LABEL"
sandbox = "$CODEX_SANDBOX"
atelier_access = "$ATELIER_ACCESS_MODE"
web_search = "$WEB_SEARCH_MODE"
shell_network = "$SHELL_NETWORK_MODE"
user_config = "$USER_CONFIG_MODE"
connector_access = "not-exercised"
approval_policy = "never"
claimed_at = "$CLAIMED_AT"
completed_at = "$completed_at"
duration_seconds = $duration
status = "$status"
EOF
}

CODEX_ENV=(
    env -i
    "HOME=$HOME"
    "PATH=$PATH"
    "OV=$OV"
    "ZDOTDIR=$ATELIER_DIR/harness/routine-shell"
    "TMPDIR=${TMPDIR:-/tmp}"
    "LANG=${LANG:-en_US.UTF-8}"
    "ATELIER_ACTIVE_RUNTIME=codex"
    "ATELIER_ROUTINE_PROFILE=$ROUTINE_PROFILE"
    "ATELIER_SKIP_LOCK_TOUCH=1"
)
for ENV_NAME in CODEX_HOME CODEX_CA_CERTIFICATE SSL_CERT_FILE; do
    if [ -n "${!ENV_NAME:-}" ]; then
        CODEX_ENV+=("$ENV_NAME=${!ENV_NAME}")
    fi
done

if [ "$WEB_SEARCH_MODE" = "live" ]; then
    CODEX_GLOBAL_ARGS=(
        -c 'approval_policy="never"'
        -c "model_reasoning_effort=\"$REASONING_EFFORT\""
        --search
    )
else
    CODEX_GLOBAL_ARGS=(
        -c 'approval_policy="never"'
        -c "model_reasoning_effort=\"$REASONING_EFFORT\""
        -c 'web_search="disabled"'
    )
fi

if [ "$CODEX_SANDBOX" = "workspace-write" ]; then
    if [ "$SHELL_NETWORK_MODE" = "enabled" ]; then
        CODEX_GLOBAL_ARGS+=(
            -c 'sandbox_workspace_write.network_access=true'
        )
    else
        CODEX_GLOBAL_ARGS+=(
            -c 'sandbox_workspace_write.network_access=false'
        )
    fi
fi

CODEX_EXEC_ARGS=(
    --sandbox "$CODEX_SANDBOX"
    --ephemeral
    --color never
    --output-last-message "$SMOKE_OUTPUT"
)
if [ "$ATELIER_ACCESS_MODE" = "read-write" ]; then
    CODEX_EXEC_ARGS+=(--dangerously-bypass-hook-trust --add-dir "$OV" -C "$ATELIER_DIR")
else
    SMOKE_CWD=$(mktemp -d "${TMPDIR:-/tmp}/atelier-profile-smoke-cwd.XXXXXX")
    CODEX_EXEC_ARGS+=(--skip-git-repo-check --add-dir "$OV" -C "$SMOKE_CWD")
fi
if [ "$USER_CONFIG_MODE" = "ignore" ]; then
    CODEX_EXEC_ARGS=(--ignore-user-config "${CODEX_EXEC_ARGS[@]}")
fi

SMOKE_PROMPT="This is a no-side-effect Atelier runtime-envelope smoke for profile $ROUTINE_PROFILE. Read $ATELIER_DIR/CLAUDE.md only if project rules require it. Treat $ATELIER_DIR as read-only unless atelier_access is read-write. Do not access Gmail, Readwise, web sources, or user content. Do not write files, run project workflows, follow session-start cues, or mutate any service. Return exactly ATELIER_PROFILE_SMOKE_OK and nothing else."

echo "[$(date -Iseconds)] profile smoke starting: routine=$SMOKE_ROUTINE profile=$ROUTINE_PROFILE sandbox=$CODEX_SANDBOX web=$WEB_SEARCH_MODE shell_network=$SHELL_NETWORK_MODE user_config=$USER_CONFIG_MODE"
STARTED_AT=$(date +%s)
if "${TIMEOUT_CMD[@]}" "${CODEX_ENV[@]}" codex "${CODEX_GLOBAL_ARGS[@]}" \
    --ask-for-approval never exec "${CODEX_EXEC_ARGS[@]}" "$SMOKE_PROMPT"; then
    RUN_STATUS="completed"
else
    RUN_STATUS="failed"
fi
ENDED_AT=$(date +%s)
DURATION=$((ENDED_AT - STARTED_AT))
COMPLETED_AT="$(date -Iseconds)"

if [ "$RUN_STATUS" = "completed" ] && [ "$(< "$SMOKE_OUTPUT")" = "ATELIER_PROFILE_SMOKE_OK" ]; then
    write_claim "completed" "$COMPLETED_AT" "$DURATION"
    echo "[$(date -Iseconds)] profile smoke completed: $CLAIM_FILE"
    exit 0
fi

write_claim "failed" "$COMPLETED_AT" "$DURATION"
echo "ERROR: profile smoke failed or returned an unexpected final message" >&2
exit 1
