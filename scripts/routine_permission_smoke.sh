#!/bin/bash
# Verify one explicitly authorized external permission through launchd and the
# routine's exact Codex capability profile. The supported probes are narrow:
# Gmail account metadata (read-only) and an idempotent Readwise test-document
# upsert. No mailbox content is read and no user-authored content is written.

set -euo pipefail

SMOKE_ROUTINE="${1:?Usage: routine_permission_smoke.sh <routine-name> <permission>}"
SMOKE_PERMISSION="${2:?Usage: routine_permission_smoke.sh <routine-name> <permission>}"
if [[ ! "$SMOKE_ROUTINE" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "ERROR: invalid routine name: $SMOKE_ROUTINE" >&2
    exit 2
fi
case "$SMOKE_PERMISSION" in
    gmail:read|readwise:create-document) ;;
    *)
        echo "ERROR: unsupported permission smoke: $SMOKE_PERMISSION" >&2
        exit 2
        ;;
esac

LAUNCHD_LABEL="${ATELIER_PERMISSION_SMOKE_LAUNCHER:-}"
if [ "$PPID" -ne 1 ] || [[ "$LAUNCHD_LABEL" != com.atelier.permission-smoke.* ]]; then
    echo "ERROR: permission smoke must run from a dedicated com.atelier.permission-smoke.* launchd job" >&2
    exit 2
fi
if [ "${ATELIER_PERMISSION_SMOKE_AUTHORIZED:-0}" != "1" ]; then
    echo "ERROR: explicit permission-smoke authorization is required" >&2
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

SMOKE_TIMEOUT_SECONDS="${ATELIER_PERMISSION_SMOKE_TIMEOUT_SECONDS:-300}"
TIMEOUT_CMD=(python3 "$SCRIPTS_DIR/command_timeout.py" --seconds "$SMOKE_TIMEOUT_SECONDS" --)

if ! "${TIMEOUT_CMD[@]}" python3 "$SCRIPTS_DIR/routine_owner.py" check >/dev/null; then
    echo "ERROR: this machine is not eligible to run local permission smoke" >&2
    exit 2
fi
if ! PROFILE_RECORD=$("${TIMEOUT_CMD[@]}" python3 "$SCRIPTS_DIR/routine_audit.py" \
    resolve "$SMOKE_ROUTINE" --surface local --check-system --runtime codex \
    --command "/run-routine $SMOKE_ROUTINE" --format tsv); then
    echo "ERROR: routine profile preflight failed: $SMOKE_ROUTINE" >&2
    exit 2
fi
IFS=$'\t' read -r ROUTINE_PROFILE CODEX_SANDBOX ATELIER_ACCESS_MODE WEB_SEARCH_MODE SHELL_NETWORK_MODE \
    USER_CONFIG_MODE ROUTINE_TIMEOUT_SECONDS REASONING_EFFORT PROFILE_FINGERPRINT PERMISSION_ALLOWLIST <<< "$PROFILE_RECORD"
if [ -z "$ROUTINE_PROFILE" ] || [ -z "$CODEX_SANDBOX" ] || \
    [ -z "$ATELIER_ACCESS_MODE" ] || [ -z "$WEB_SEARCH_MODE" ] || [ -z "$SHELL_NETWORK_MODE" ] || \
    [ -z "$USER_CONFIG_MODE" ] || [ -z "$REASONING_EFFORT" ] || [ -z "$PROFILE_FINGERPRINT" ] || [ -z "$PERMISSION_ALLOWLIST" ]; then
    echo "ERROR: incomplete routine profile record" >&2
    exit 2
fi

if ! python3 - "$ATELIER_DIR/harness/routine_profiles.toml" "$ROUTINE_PROFILE" "$SMOKE_PERMISSION" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    profiles = tomllib.load(handle)["profiles"]
profile = profiles.get(sys.argv[2], {})
if sys.argv[3] not in profile.get("permissions", []):
    raise SystemExit(2)
PY
then
    echo "ERROR: permission is not declared by profile $ROUTINE_PROFILE: $SMOKE_PERMISSION" >&2
    exit 2
fi

SMOKE_OUTPUT=$(mktemp "${TMPDIR:-/tmp}/atelier-permission-smoke-output.XXXXXX")
SMOKE_CWD=""
cleanup_smoke_output() {
    rm -f "$SMOKE_OUTPUT"
    if [ -n "$SMOKE_CWD" ]; then
        python3 -c 'import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$SMOKE_CWD"
    fi
}
trap cleanup_smoke_output EXIT

SAFE_PERMISSION="${SMOKE_PERMISSION//:/_}"
CLAIM_DIR="$OV/_meta/routine_permission_smokes/$ROUTINE_PROFILE"
mkdir -p "$CLAIM_DIR"
CLAIM_FILE="$CLAIM_DIR/$(date +%Y%m%dT%H%M%S)-$(hostname)-$SAFE_PERMISSION.toml"
CLAIMED_AT="$(date -Iseconds)"

case "$SMOKE_PERMISSION" in
    gmail:read)
        EXPECTED_MARKER="ATELIER_PERMISSION_SMOKE_GMAIL_OK"
        MUTATION_MODE="read-only"
        SMOKE_PROMPT="This is an explicitly authorized, read-only Atelier Gmail permission smoke. Use only the connected Gmail app to read the authenticated account profile. Do not search messages, read mailbox content, create drafts, send, archive, delete, or change labels. If and only if the profile call succeeds, return exactly $EXPECTED_MARKER and nothing else."
        ;;
    readwise:create-document)
        READWISE_DOCUMENT_ID="${ATELIER_READWISE_SMOKE_DOCUMENT_ID:-}"
        if [[ ! "$READWISE_DOCUMENT_ID" =~ ^[A-Za-z0-9_-]+$ ]]; then
            echo "ERROR: ATELIER_READWISE_SMOKE_DOCUMENT_ID is required and invalid" >&2
            exit 2
        fi
        EXPECTED_MARKER="ATELIER_PERMISSION_SMOKE_READWISE_OK"
        MUTATION_MODE="idempotent-test-write"
        SMOKE_PROMPT="This is an explicitly authorized Atelier Readwise permission smoke. Run exactly one shell command: readwise --json reader-create-document --url https://atelier.local/routine-permission-smoke/2026-07-17 --markdown 'Atelier routine permission smoke. Created with explicit user authorization on 2026-07-17. This document contains no user content.' --title 'Atelier routine permission smoke 2026-07-17' --category article --tags 'atelier-smoke,routine-permission-test'. This is an idempotent upsert of the already-created test URL. Do not access any other Readwise document or user content. Parse the JSON without printing it. If and only if the command succeeds and its document id equals $READWISE_DOCUMENT_ID, return exactly $EXPECTED_MARKER and nothing else."
        ;;
esac

write_claim() {
    local status="$1"
    local completed_at="$2"
    local duration="$3"
    cat > "$CLAIM_FILE" <<EOF
kind = "external-permission"
contract_version = 1
routine = "$SMOKE_ROUTINE"
profile = "$ROUTINE_PROFILE"
profile_fingerprint = "$PROFILE_FINGERPRINT"
permission = "$SMOKE_PERMISSION"
runtime = "codex"
machine = "$(hostname)"
launcher = "$LAUNCHD_LABEL"
sandbox = "$CODEX_SANDBOX"
atelier_access = "$ATELIER_ACCESS_MODE"
web_search = "$WEB_SEARCH_MODE"
shell_network = "$SHELL_NETWORK_MODE"
user_config = "$USER_CONFIG_MODE"
approval_policy = "never"
user_authorized = true
verification = "model-reported"
mutation_mode = "$MUTATION_MODE"
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

CODEX_GLOBAL_ARGS=(
    -c 'approval_policy="never"'
    -c "model_reasoning_effort=\"$REASONING_EFFORT\""
)
if [ "$WEB_SEARCH_MODE" = "live" ]; then
    CODEX_GLOBAL_ARGS+=(--search)
else
    CODEX_GLOBAL_ARGS+=(-c 'web_search="disabled"')
fi
if [ "$CODEX_SANDBOX" = "workspace-write" ]; then
    if [ "$SHELL_NETWORK_MODE" = "enabled" ]; then
        CODEX_GLOBAL_ARGS+=(-c 'sandbox_workspace_write.network_access=true')
    else
        CODEX_GLOBAL_ARGS+=(-c 'sandbox_workspace_write.network_access=false')
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
    SMOKE_CWD=$(mktemp -d "${TMPDIR:-/tmp}/atelier-permission-smoke-cwd.XXXXXX")
    CODEX_EXEC_ARGS+=(--skip-git-repo-check --add-dir "$OV" -C "$SMOKE_CWD")
fi
if [ "$USER_CONFIG_MODE" = "ignore" ]; then
    CODEX_EXEC_ARGS=(--ignore-user-config "${CODEX_EXEC_ARGS[@]}")
fi

echo "[$(date -Iseconds)] permission smoke starting: routine=$SMOKE_ROUTINE profile=$ROUTINE_PROFILE permission=$SMOKE_PERMISSION shell_network=$SHELL_NETWORK_MODE"
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

if [ "$RUN_STATUS" = "completed" ] && [ "$(< "$SMOKE_OUTPUT")" = "$EXPECTED_MARKER" ]; then
    write_claim "completed" "$COMPLETED_AT" "$DURATION"
    echo "[$(date -Iseconds)] permission smoke completed: $CLAIM_FILE"
    exit 0
fi

write_claim "failed" "$COMPLETED_AT" "$DURATION"
echo "ERROR: permission smoke failed or returned an unexpected final message" >&2
exit 1
