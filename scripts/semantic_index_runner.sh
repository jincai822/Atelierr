#!/bin/bash
# Owner-gated deterministic refresh for the machine-local semantic index.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
ATELIER_DIR="$(dirname "$SCRIPTS_DIR")"

# launchd does not inherit the interactive shell environment. Temporarily
# relax strict mode while loading user profiles because unrelated variables in
# those files may be unset.
set +eu
source "$HOME/.zprofile" 2>/dev/null || true
source "$HOME/.profile" 2>/dev/null || true
source "$ATELIER_DIR/harness/env.local.sh" 2>/dev/null || true
set -eu

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) [ -d "$HOME/.local/bin" ] && export PATH="$HOME/.local/bin:$PATH" ;;
esac

: "${OV:?ERROR: OV not set; export it from a login profile or harness/env.local.sh}"

TIMEOUT_CMD=(
    python3 "$SCRIPTS_DIR/command_timeout.py"
    --seconds "${ATELIER_PREFLIGHT_TIMEOUT_SECONDS:-30}"
    --
)
OWNER_EXIT=0
OWNER_RESULT=$(
    "${TIMEOUT_CMD[@]}" python3 "$SCRIPTS_DIR/routine_owner.py" check --json 2>&1
) || OWNER_EXIT=$?
if [ "$OWNER_EXIT" -eq 1 ]; then
    echo "[$(date -Iseconds)] semantic index skipped: owned by another machine"
    exit 0
fi
if [ "$OWNER_EXIT" -ne 0 ]; then
    echo "[$(date -Iseconds)] ERROR: routine owner check failed: $OWNER_RESULT" >&2
    exit 2
fi

# Scheduled maintenance is cache-only and must never download a model or
# mutate dependency resolution. An uncached model or environment fails visibly
# in the launchd error log.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

echo "[$(date -Iseconds)] semantic index freshness check started"
cd "$ATELIER_DIR"
SEMANTIC_TIMEOUT_SECONDS="${ATELIER_SEMANTIC_INDEX_TIMEOUT_SECONDS:-7200}"
/usr/bin/caffeinate -i \
    python3 "$SCRIPTS_DIR/command_timeout.py" \
    --seconds "$SEMANTIC_TIMEOUT_SECONDS" \
    -- \
    uv run --offline --frozen scripts/semantic.py index --if-stale
echo "[$(date -Iseconds)] semantic index maintenance completed"
