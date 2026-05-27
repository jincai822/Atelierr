# /autoevo-nightly — Autonomous decay sweep + auto-commit

Fired by macOS `launchd` at 5:00 local. Contract: `protocols/autoevo.md`.

This command is intended for **headless invocation** (`claude -p "/autoevo-nightly"`). It runs unattended, auto-applies the high-confidence Forgetter band, logs the rest to a pending queue for next /hi, and commits every destructive op to `$OV`. It never pushes. It never touches `<paths.wiki>/`, `<paths.daily_notes>/`, or anything outside the three working-tier sweep scopes (`<paths.wip>/`, `<paths.research>/`, `<paths.reflections>/`). `<paths.agent_findings>/` is a write target for the audit log only — never a sweep scope.

If invoked interactively, the same contract holds — the bot does not wait for human approval. To review what it does before it does it, set the `DRY_RUN=1` env var (see step 8).

## Run shape

```
launchd 05:00 -> claude -p "/autoevo-nightly" -> orchestrator runs this file
```

The orchestrator MUST execute this command verbatim, sequentially. No parallel agent dispatches (each commit must complete before the next op begins). On any unrecoverable error, abort the run, write the partial audit log, and exit. Failures surface as cues at next /hi via the pre-flight gates section.

## Halt conditions

Three declared signals that interrupt the nightly run at different levels: condition 1 refuses to start; condition 2 demotes one dispatch and continues; condition 3 skips one scope on the next run and continues.

The umbrella name "halt" is loose for condition 1 (a pre-flight refusal) and condition 2 (a dispatch-level demote); only condition 3 halts a unit of work mid-run. The umbrella is naming convenience; the per-condition prose below is authoritative.

Each is implemented in this same file; no external file or consumer change is required to ship this section.

### Condition 1: External blocker (pre-flight)

Refuses to start the run. Implementation: step 1 gates. Triggers on any of:

- session-active lock present and < 6h old
- `$OV` not a git work tree
- `$OV` working tree dirty
- `zettelm/` submodule dirty
- `privacy_check.py --json` returns `hit_count > 0`

Exit: 0, audit log § Skipped with gate name + detail. The next nightly fires a fresh cycle.

### Condition 2: Per-step budget exhaustion

Demotes the dispatch. Implementation: per-dispatch caps in step 2 (`max_candidates: 12-15`, `time_budget_s: 240`) and the agent-level `maxTurns: 60` ceiling declared in `.claude/agents/forgetter.md`. A dispatch that hits any cap returns `mode: partial`; the orchestrator accepts the partial findings and continues to the next scope.

A dispatch that returns no envelope at all is **not** a demote: it is the input signal for condition 3. Per `.claude/agents/forgetter.md` ("If you do not emit the envelope, the orchestrator's parser cannot recover any findings from your output — the sweep is lost"), envelope emission is mandatory on completion. Absence of the envelope therefore unambiguously signals truncation, crash, or runtime interruption; never "ran fine, nothing to say."

### Condition 3: Per-scope quarantine (cross-run)

Skips the scope on the next run. If a scope returns `forgetter_no_envelope` on **3 consecutive dispatch attempts** (counted per scope, where each attempt occurs on a distinct rotation slot for `<paths.research>/` subdirs), the next run's step 2.0 removes that scope from the dispatch list. The orchestrator logs `scope_quarantined: scope=<absolute-path>, consecutive_failures=<n>, first_failed=<YYYY-MM-DD>, expires_at=<YYYY-MM-DD>` to audit § Skipped per skipped scope and continues to the next scope.

Threshold-crossing run: when a scope's 3rd consecutive failure occurs this run, only § Errors emits (`forgetter_no_envelope: scope=<S>, ...` from the existing step 2a contract). The `scope_quarantined:` entry appears on the NEXT run's § Skipped when step 2.0 filters the scope. The threshold-crossing run does not double-log.

State: `$OV/_meta/autoevo_quarantine.toml`. This file is the **source of truth** for quarantine state; step 7 updates it directly from this run's per-scope dispatch outcomes. There is no rebuild from audit-log history.

Schema:

```toml
# Consumer note: scripts/cues.py surfaces this state indirectly. The
# existing check_autoevo_ran fires on ANY non-empty content in audit
# log § Skipped (via section_populated). The keyword `scope_quarantined:`
# is for the user, not for cues.py. Renaming the keyword is safe as long
# as the line still lands in § Skipped.
[[quarantine]]
scope = '<canonical absolute path WITHOUT trailing slash>'
first_failed = '<YYYY-MM-DD>'
consecutive_failures = 3
reason = 'forgetter_no_envelope'
expires_at = '<YYYY-MM-DD>'   # Auto-recovery date. Step 7 sets this to
                              # first_failed + QUARANTINE_EXPIRY_DAYS
                              # (defined inline at step 7; default 30).
                              # Step 2.0 drops entries where
                              # expires_at <= RUN_DATE.
```

TOML literal strings (single-quoted) are used throughout for filesystem paths and dates; they need no escaping and survive any bash heredoc quoting unchanged. If a future failure mode introduces a path containing a single quote, switch that field to a multi-line literal string (`'''...'''`) or to a basic string with proper escaping.

The 30-day expiry default is deliberately short: the failure modes that trigger condition 3 (corrupt file, renamed path, permission glitch) are static, not transient. A 30-day cooldown gets the scope back into the dispatch set fast enough that a stale quarantine is visible to the user within a normal operating month.

### Implementation logic

Three pieces of bash + Python land in three existing steps. The OUTCOMES hand-off between step 2a and step 7 uses a sidecar JSON file (not an env var) so each piece is self-contained and debuggable. All Python heredocs are quoted (`<<'EOF'`) and receive runtime paths via `os.environ`; bash performs no substitution inside the heredoc body. The heredoc `EOF` terminators must sit at column 0 in the bash file when extracted from this markdown.

**Path normalization invariant**: step 2.0 strips trailing slashes from all three dispatch scopes (`RESEARCH_TONIGHT`, `WIP_DIR`, `REFLECTIONS_DIR`) once, into `_STRIPPED` variants. Every downstream consumer (step 2a's SCOPE_PATH, step 7's TOML key, the quarantine sidecar lines) uses the stripped variant. The unstripped originals must not be referenced downstream; they would produce a different key from the TOML's canonical no-trailing-slash form, and the quarantine match would silently never fire.

#### Step 2 start: initialize sidecar

Before any Forgetter dispatch:

```bash
OUTCOMES_FILE="$PATHS_CACHE/autoevo-${RUN_TS}-outcomes.json"
echo '{}' > "$OUTCOMES_FILE"
```

#### Step 2a: record per-dispatch outcome

After each dispatch returns (right after the existing envelope-detection logic), update the sidecar. `SCOPE_PATH` is the absolute path with trailing slash stripped (from step 2.0's normalization). `OUTCOME` is one of `envelope_returned` (covers `mode: full` and `mode: partial`) or `forgetter_no_envelope`.

```bash
SCOPE_PATH="$SCOPE_PATH" OUTCOME="$OUTCOME" OUTCOMES_FILE="$OUTCOMES_FILE" \
  uv run --quiet python3 - <<'EOF'
import json, os, pathlib
p = pathlib.Path(os.environ["OUTCOMES_FILE"])
data = json.loads(p.read_text())
data[os.environ["SCOPE_PATH"]] = os.environ["OUTCOME"]
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(data))
tmp.replace(p)
EOF
```

The `SCOPE_PATH` here MUST be one of the `_STRIPPED` variants from step 2.0 (`RESEARCH_TONIGHT_STRIPPED`, `WIP_DIR_STRIPPED`, `REFLECTIONS_DIR_STRIPPED`). Using the unstripped variant breaks the lookup in step 7.

Both `mode: full` and `mode: partial` are `envelope_returned`. Only "no envelope present at all" maps to `forgetter_no_envelope`.

#### Step 2.0: normalize paths + quarantine filter

Added after the existing sort, before the existing empty-list guard.

```bash
# Normalize all dispatch-scope paths once. Used everywhere downstream.
WIP_DIR_STRIPPED="${WIP_DIR%/}"
REFLECTIONS_DIR_STRIPPED="${REFLECTIONS_DIR%/}"
# RESEARCH_TONIGHT_STRIPPED is set below after the rotation modulo.

# Build the quarantine set into a tempfile (one path per line). Use a
# tempfile rather than command substitution so paths with spaces survive
# intact through the next loop.
QUARANTINE_TMP="$PATHS_CACHE/autoevo-${RUN_TS}-quarantined.txt"
QUARANTINE_SKIPPED="$PATHS_CACHE/autoevo-${RUN_TS}-quarantine-skipped.txt"
: > "$QUARANTINE_SKIPPED"   # truncate; step 7 reads this later

OV="$OV" \
  uv run --quiet python3 - <<'EOF' > "$QUARANTINE_TMP"
import os, sys, tomllib, datetime, pathlib
p = pathlib.Path(os.environ["OV"]) / "_meta" / "autoevo_quarantine.toml"
if not p.exists():
    sys.exit(0)
data = tomllib.loads(p.read_text())
today = datetime.date.today().isoformat()
for q in data.get("quarantine", []):
    if q.get("consecutive_failures", 0) >= 3 and q.get("expires_at", "") > today:
        print(q["scope"])
EOF

# Filter the research-subdir list. Strip trailing slashes from each
# entry; use while-read (not for-in) to survive paths with spaces.
declare -a FILTERED=()
for d in "${RESEARCH_SUBDIRS[@]}"; do
    d_stripped="${d%/}"
    match=0
    while IFS= read -r q; do
        [ "$d_stripped" = "$q" ] && { match=1; break; }
    done < "$QUARANTINE_TMP"
    if [ $match -eq 1 ]; then
        echo "scope_quarantined: scope=$d_stripped (research-tier rotation)" \
            >> "$QUARANTINE_SKIPPED"
    else
        FILTERED+=("$d_stripped")
    fi
done
RESEARCH_SUBDIRS=("${FILTERED[@]}")

# Apply the same filter to wip and reflections (single-scope each).
SKIP_WIP=0
SKIP_REFLECTIONS=0
while IFS= read -r q; do
    [ "$WIP_DIR_STRIPPED" = "$q" ] && SKIP_WIP=1
    [ "$REFLECTIONS_DIR_STRIPPED" = "$q" ] && SKIP_REFLECTIONS=1
done < "$QUARANTINE_TMP"
if [ $SKIP_WIP -eq 1 ]; then
    echo "scope_quarantined: scope=$WIP_DIR_STRIPPED (wip)" >> "$QUARANTINE_SKIPPED"
fi
if [ $SKIP_REFLECTIONS -eq 1 ]; then
    echo "scope_quarantined: scope=$REFLECTIONS_DIR_STRIPPED (reflections)" >> "$QUARANTINE_SKIPPED"
fi

# The wip and reflections dispatches in step 2.1 must check
# SKIP_WIP / SKIP_REFLECTIONS and bypass the corresponding dispatch
# when set.

# Empty-list guard after filter: if all research subdirs are
# quarantined, skip research dispatch this run and note it.
if [ ${#RESEARCH_SUBDIRS[@]} -eq 0 ] && [ -s "$QUARANTINE_TMP" ]; then
    echo "Research rotation: all subdirs currently quarantined, skipping research dispatch this run"
    RESEARCH_TONIGHT=""
    # Audit-log § Notes: research_all_quarantined
fi

# After the existing rotation modulo sets RESEARCH_TONIGHT, normalize:
RESEARCH_TONIGHT_STRIPPED="${RESEARCH_TONIGHT%/}"
```

#### Step 7: update quarantine TOML and emit quarantine entries into audit log § Skipped

The Python heredoc is quoted (`<<'EOF'`). Bash performs no substitution inside; runtime paths arrive via env vars. Filesystem paths are written as TOML literal strings, which require no escaping.

```bash
OV="$OV" OUTCOMES_FILE="$OUTCOMES_FILE" PATHS_CACHE="$PATHS_CACHE" \
RUN_TS="$RUN_TS" \
  uv run --quiet python3 - <<'EOF'
import json, os, tomllib, datetime, pathlib

QUARANTINE_EXPIRY_DAYS = 30

OV = pathlib.Path(os.environ["OV"])
p_toml = OV / "_meta" / "autoevo_quarantine.toml"
p_outcomes = pathlib.Path(os.environ["OUTCOMES_FILE"])

today = datetime.date.today()
today_str = today.isoformat()

data = tomllib.loads(p_toml.read_text()) if p_toml.exists() else {"quarantine": []}
by_scope = {q["scope"]: q for q in data.get("quarantine", [])}

crossed_or_created = 0

outcomes = json.loads(p_outcomes.read_text()) if p_outcomes.exists() else {}
for scope, outcome in outcomes.items():
    if outcome == "envelope_returned":
        by_scope.pop(scope, None)
    elif outcome == "forgetter_no_envelope":
        prior_count = by_scope.get(scope, {}).get("consecutive_failures", 0)
        entry = by_scope.setdefault(scope, {
            "scope": scope,
            "first_failed": today_str,
            "consecutive_failures": 0,
            "reason": "forgetter_no_envelope",
            "expires_at": (today + datetime.timedelta(days=QUARANTINE_EXPIRY_DAYS)).isoformat(),
        })
        # Invariant: each increment represents one attempt on a distinct
        # rotation slot. <paths.research>/ subdirs are dispatched at
        # most once per run by step 2.0's modulo. If step 2.0 ever
        # batch-dispatches multiple subdirs in one run, re-establish
        # this invariant by keying the counter on (scope, RUN_TS) and
        # deduping per run.
        entry["consecutive_failures"] += 1
        new_count = entry["consecutive_failures"]
        # <Q> counts only threshold transitions (prior < 3, new >= 3).
        if prior_count < 3 and new_count >= 3:
            crossed_or_created += 1

by_scope = {s: e for s, e in by_scope.items() if e.get("expires_at", "") > today_str}

# Hand-roll TOML emission using literal strings (single-quoted).
lines = []
for entry in by_scope.values():
    lines.append("[[quarantine]]")
    for k in ("scope", "first_failed", "reason", "expires_at"):
        lines.append(f"{k} = '{entry[k]}'")
    lines.append(f"consecutive_failures = {int(entry['consecutive_failures'])}")
    lines.append("")
body = "\n".join(lines) + "\n"

# Atomic write: sibling tmpfile + os.replace.
tmp = p_toml.with_suffix(".toml.tmp")
tmp.write_text(body)
tmp.replace(p_toml)

# Emit the <Q> count to a sidecar so the orchestrator can substitute
# into the commit-message heredoc.
cache = pathlib.Path(os.environ["PATHS_CACHE"])
ts = os.environ["RUN_TS"]
(cache / f"autoevo-{ts}-quarantine-count.txt").write_text(str(crossed_or_created))
EOF
```

Audit-log integration. The existing step 7 writes the audit log directly to its final path. Bind the path explicitly so the quarantine append is unambiguous:

```bash
AUDIT_LOG_PATH="$OV/${FINDINGS_REL}/autoevo-applied-${RUN_DATE}.md"

# After the existing step 7 has constructed and written the audit log
# (with its § Skipped section already containing any pre-flight gate
# aborts), append the quarantine-skipped lines:
if [ -s "$QUARANTINE_SKIPPED" ]; then
    cat "$QUARANTINE_SKIPPED" >> "$AUDIT_LOG_PATH"
fi
```

Audit-log commit. Matches the existing step 7 convention exactly: `<<'EOF'` heredoc with `<RUN_DATE>`, `<N>`, `<M>`, `<K>` as orchestrator-substituted placeholders, plus the new `<Q>` placeholder which the orchestrator reads from `$PATHS_CACHE/autoevo-${RUN_TS}-quarantine-count.txt`.

```bash
git -C "$OV" add -- "_meta/autoevo_quarantine.toml"
git -C "$OV" add -- "${FINDINGS_REL}/autoevo-applied-${RUN_DATE}.md"
git -C "$OV" commit -m "$(cat <<'EOF'
[autoevo:audit] agent-findings: record nightly run <RUN_DATE>

Auto-applied: <N>, Pending: <M>, Errors: <K>, Quarantined: <Q>

Co-Authored-By: Atelier Autoevo Bot <noreply@atelier.local>
EOF
)"
```

The orchestrator substitutes `<RUN_DATE>`, `<N>`, `<M>`, `<K>` from the values it already computes in the existing step 7, and substitutes `<Q>` from the count sidecar file. No bash bindings required; same idiom as the existing commits.

`<Q>` counts only threshold transitions (prior_count < 3 AND new_count >= 3). New entries with counter=1 or counter=2 do not contribute. Entries that increment beyond 3 also do not contribute.

Manual reset: user deletes the matching `[[quarantine]]` block from `_meta/autoevo_quarantine.toml` (or `rm` the whole file to clear all quarantines). The next run's step 2.0 sees no entry, dispatches the scope normally. If it succeeds, no entry is re-created. If it fails again, the counter restarts at 1.

Catches: a corrupted file inside the scope that crashes Forgetter pre-flight; a path that became invalid after a rename; a permission issue that does not self-heal.

Caveat for the audit-log mapping table below: "halt" applies at three different control-flow levels. Condition 1 refuses to start the run (pre-flight); condition 2 demotes one dispatch (run continues); condition 3 skips one scope on the next run (run continues). The table summarizes the outcome; the per-condition prose above is authoritative on semantics.

### Audit-log mapping

| Condition | Action | Audit log section | Exit code |
|---|---|---|---|
| 1: External blocker | refuse to start | Skipped (`<gate>: <detail>`) | 0 |
| 2: Per-step budget | demote dispatch | Errors (`forgetter_partial: ...`) | run continues |
| 3: Per-scope quarantine | scope skip | Skipped (`scope_quarantined: ...`) | run continues to next scope |

Fatal errors not covered by any condition (snapshot cp failed, commit aborted by hook, queue TOML corrupted) follow the existing step 4c, step 7, and "Edge cases" handling and exit 1.

### Implementation requirements (within this file)

| Section | Required edit |
|---|---|
| Step 2 start | initialize empty OUTCOMES sidecar JSON file at `$PATHS_CACHE/autoevo-${RUN_TS}-outcomes.json` |
| Step 2.0 | normalize `WIP_DIR_STRIPPED` / `REFLECTIONS_DIR_STRIPPED` / `RESEARCH_TONIGHT_STRIPPED` (after rotation); parse quarantine TOML into tempfile; filter dispatch list after sort, before empty-list guard; write `$QUARANTINE_SKIPPED` for step 7 to consume; set `SKIP_WIP` / `SKIP_REFLECTIONS` flags for step 2.1; add all-research-subdirs-quarantined guard |
| Step 2.1 | dispatch with `_STRIPPED` paths (not the originals). Honor `SKIP_WIP` / `SKIP_REFLECTIONS` flags by bypassing the corresponding Forgetter dispatch. Concrete pattern: `if [ $SKIP_WIP -eq 0 ]; then ...existing wip dispatch with WIP_DIR_STRIPPED... ; fi`. Same for reflections; research uses `RESEARCH_TONIGHT_STRIPPED`. |
| Step 2a | use the `_STRIPPED` scope path as both the dispatch target AND the SCOPE_PATH key in the OUTCOMES sidecar write |
| Step 7 | bind `AUDIT_LOG_PATH`; apply quarantine update logic; append `$QUARANTINE_SKIPPED` into `$AUDIT_LOG_PATH` after the existing § Skipped emission; orchestrator reads count sidecar and substitutes `<Q>` into the commit-message heredoc alongside the existing `<RUN_DATE>`, `<N>`, `<M>`, `<K>` substitutions; `git add` the quarantine TOML alongside the audit log |

### Deferred (not blocking, tracked for future iteration)

- Queue fatigue demotion: a fourth signal in the same conceptual family (when does the system stop trying to surface a pending finding the user has implicitly ignored?). Out of scope for the current halt-conditions surface because it requires consumer-side edits in `protocols/autoevo.md`, `scripts/cues.py`, and `.claude/commands/autoevo-review.md`. Track as a followup once run-history data is available.
- Early-warning cue at consecutive_failures 1 or 2.
- `/autoevo-review` surface for inspecting and resetting quarantine state.
- Vault-rename hook to update quarantine TOML keys.
- Eventual extraction of step 7's Python heredoc into `scripts/autoevo_quarantine_update.py` (removes the inline-pseudocode coupling between the contract section and the implementation detail).

## Step 0: Acquire run identity and resolve registry paths

```bash
RUN_TS=$(date +%Y%m%d-%H%M%S)
RUN_DATE=$(date +%Y-%m-%d)
echo "autoevo-nightly run started $RUN_TS"

# Resolve registry-defined paths once, bind shell variables for the rest of the run.
# This is the canonical way to address vault segments; never hardcode `archive/decayed/`
# or `agent-findings/` inline (CLAUDE.md § Path placeholders + scripts/_paths.py contract).
PATHS_CACHE=$(uv run --quiet python3 -c "from scripts._paths import tier; print(tier('cache'))")
PATHS_ARCHIVE=$(uv run --quiet python3 -c "from scripts._paths import tier; print(tier('archive'))")
PATHS_FINDINGS=$(uv run --quiet python3 -c "from scripts._paths import tier; print(tier('agent_findings'))")
LOCK="$PATHS_CACHE/atelier-session-lock"
```

Bind `<RUN_TS>` and `<RUN_DATE>` for the rest of the run. Subsequent steps use `$PATHS_CACHE`, `$PATHS_ARCHIVE`, `$PATHS_FINDINGS` instead of hardcoded segments, so a registry rename does not silently break the bot.

## Step 1: Pre-flight gates

Each gate writes a one-line entry to the audit log if it trips, then exits 0. The audit log entry surfaces as the next /hi cue.

### 1a. Session-active lock

```bash
# $LOCK was bound in step 0 via the path registry.
if [ -f "$LOCK" ]; then
  AGE=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || stat -c %Y "$LOCK") ))
  if [ "$AGE" -lt 21600 ]; then
    echo "abort: session-active lock fresh (age ${AGE}s < 21600s)"
    # write audit log Skipped section, exit
  fi
fi
```

Six hours is the bound per `protocols/autoevo.md`. An absent lock file is treated as "no recent session" (permissive default — the first run after install proceeds). If the lock is fresh, log skip and exit. The lock writer is `scripts/cues.py --hook` invoked by the SessionStart hook in `.claude/settings.json` AND by the UserPromptSubmit hook (so long-running sessions refresh the lock per prompt).

### 1b. $OV is a git work tree AND clean

```bash
# Confirm $OV is a git repo first — every safety guarantee in this protocol
# (per-op commits, git revert recovery, tombstone detection via git log)
# depends on it. If git-status fails, `wc -l` returns 0 and DIRTY=0 — the
# old check would happily pass and let the bot run on a non-git vault.
if ! git -C "$OV" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "abort: \$OV is not a git work tree (no recovery surface)"
  # write audit log § Skipped, exit
fi

DIRTY=$(git -C "$OV" status --porcelain | wc -l | tr -d ' ')
if [ "$DIRTY" -gt 0 ]; then
  echo "abort: dirty $OV working tree ($DIRTY entries)"
  # write audit log, exit
fi
```

### 1c. Dirty zettelm submodule

```bash
ZM=$(git -C "$OV"/zettelm status --porcelain 2>/dev/null | wc -l | tr -d ' ')
if [ "$ZM" -gt 0 ]; then
  echo "abort: dirty zettelm submodule ($ZM entries)"
  # write audit log, exit
fi
```

If `zettelm/` doesn't exist as a submodule for this user, the check silently skips (git returns non-zero, no entries counted).

### 1d. Privacy gate

```bash
uv run scripts/privacy_check.py --json > "$PATHS_CACHE/autoevo-${RUN_TS}-privacy.json"
HITS=$(python3 -c "import json,sys; d=json.load(open('$PATHS_CACHE/autoevo-${RUN_TS}-privacy.json')); print(d.get('hit_count', 0))")
if [ "$HITS" -gt 0 ]; then
  echo "abort: privacy_check found $HITS hits"
  # write audit log with hit details, exit
fi
```

`hit_count > 0` is a hard veto — fix leaks before any commit. Soft-skip flags (`zk_missing`, `vacuous_gate`) treat as pass (the gate is not meaningfully running).

If any gate trips, write the audit log section "Skipped (reason: <gate>)" per step 7 format and exit 0. **Do not proceed to step 2.**

## Step 2: Forgetter sweep + persist reports

For each working-tier scope, dispatch Forgetter **synchronous, sequential** (the orchestrator awaits each Agent call before issuing the next). Sequential is mandatory: it (a) avoids subagent-runtime turn-cap contention, (b) keeps audit-log Errors entries in scope-order, (c) preserves per-dispatch determinism for the cluster_hash machinery downstream. The orchestrator pre-resolves placeholder paths to absolute paths before dispatch so Forgetter does not spend budget re-resolving the path registry.

### 2.0 Choose dispatch scopes (rotation for the large tier)

Empirically a Forgetter dispatch consumes ~3-4 tool calls per candidate (Read + semantic query + result inspection). With `maxTurns: 60` and a budget reserve for envelope emission, a single dispatch can safely cover ~12-15 candidates. The `<paths.research>/` tier has hundreds of files spread across many subdirs; sweeping it whole exhausts the budget. To get full coverage without blowing the per-dispatch budget, the orchestrator **rotates through `<paths.research>/` subdirs**, sweeping one subdir per night based on the day-of-month modulo subdir count.

```bash
# Resolve absolute paths for the three working tiers via the registry.
WIP_DIR=$(uv run --quiet python3 -c "from scripts._paths import tier; print(tier('wip'))")
RESEARCH_DIR=$(uv run --quiet python3 -c "from scripts._paths import tier; print(tier('research'))")
REFLECTIONS_DIR=$(uv run --quiet python3 -c "from scripts._paths import tier; print(tier('reflections'))")

# Build the research-tier subdir rotation. Sort for determinism;
# exclude non-candidate-bearing dirs (cache, images, raw, dotdirs).
RESEARCH_SUBDIRS=()
for d in "$RESEARCH_DIR"/*/; do
  basename_d=$(basename "$d")
  case "$basename_d" in
    cache|images|raw|.*) continue ;;
  esac
  RESEARCH_SUBDIRS+=("$d")
done
# Sort for deterministic rotation order across nights.
IFS=$'\n' RESEARCH_SUBDIRS=($(sort <<<"${RESEARCH_SUBDIRS[*]}")); unset IFS

# Empty-list guard: if <paths.research>/ has no eligible subdirs (fresh vault,
# all subdirs excluded by the cache|images|raw filter, or the dir doesn't
# exist yet), the modulo below would divide by zero and abort the run before
# the audit log is written. Skip the research dispatch instead.
if [ ${#RESEARCH_SUBDIRS[@]} -eq 0 ]; then
  RESEARCH_TONIGHT=""
  echo "Research rotation: no eligible subdirs found in $RESEARCH_DIR — skipping research dispatch this run"
  # The orchestrator records this as audit-log § Notes (NOT § Errors —
  # this is expected behavior on a fresh vault, not a failure).
else
  # Choose tonight's subdir by day-of-month modulo count.
  DOM=$(date +%-d)
  RESEARCH_TONIGHT_IDX=$(( (DOM - 1) % ${#RESEARCH_SUBDIRS[@]} ))
  RESEARCH_TONIGHT="${RESEARCH_SUBDIRS[$RESEARCH_TONIGHT_IDX]}"
  echo "Research rotation: night ${DOM} → $(basename "$RESEARCH_TONIGHT") (subdir ${RESEARCH_TONIGHT_IDX} of ${#RESEARCH_SUBDIRS[@]})"
fi
```

Wip and reflections tiers are smaller (typical 30-50 files); sweep them whole each night with a tighter `max_candidates` cap.

### 2.1 Dispatch in this exact order

```
1. Agent (subagent_type=forgetter) with:
     scope_path: $WIP_DIR
     max_candidates: 12
     time_budget_s: 240

   Await full return. Process per 2a below.

2. Agent (subagent_type=forgetter) with:
     scope_path: $RESEARCH_TONIGHT   # rotation chooses one subdir per night
     max_candidates: 15
     time_budget_s: 240

   **Skip this dispatch entirely** if `$RESEARCH_TONIGHT` is empty (per the empty-list guard in 2.0).
   When skipped, write a one-line `research_rotation_empty: no eligible subdirs in $RESEARCH_DIR`
   to audit log § Notes and move to dispatch 3.

   Await full return. Process per 2a below.

3. Agent (subagent_type=forgetter) with:
     scope_path: $REFLECTIONS_DIR
     max_candidates: 12
     time_budget_s: 240

   Await full return.
```

`max_candidates: 12-15` keeps total tool calls below Forgetter's `maxTurns: 60` ceiling. Empirically 15 candidates × ~3 tool calls = 45 turns, leaving 15 turns headroom for setup + envelope emission. The research-tier rotation gives full coverage over `${#RESEARCH_SUBDIRS[@]}` nights (typically 5-8 nights for a healthy vault) while keeping each dispatch within budget. The full rotation period appears in audit log § "Notes" so the user can see "research tier full sweep completes every N days."

`<paths.wiki>/` is **not** in the sweep list. Wiki maintenance follows the Contradicted-only flow (step 4); the bot does not sweep wiki for low-signal or redundant decay.

`<paths.research>/` subdirs that don't yet exist on first run (or that are explicitly excluded above as `cache|images|raw|.*`) are skipped silently. If the rotation ever picks a non-existent path, Forgetter's pre-flight refuses with a clarification request and the orchestrator routes the gap to audit § Errors as `forgetter_scope_missing: scope=<path>`.

### 2a. Persist + parse each Forgetter return

Per the updated `protocols/agent-handoff.md` § Forgetter → Orchestrator, Forgetter is read-only: it returns the full categorized findings inline inside the `---forgetter-result--- … ---end-result---` envelope. The orchestrator persists the report to disk and is responsible for detecting envelope absence:

For each Forgetter dispatch return:

1. **Detect envelope presence.** Scan the agent's response for `---forgetter-result---` and `---end-result---` markers. If either marker is missing, the dispatch truncated before emitting; record an audit-log § Errors row:

   ```
   forgetter_no_envelope: scope=<scope_path>, tool_calls=<from agent metadata>, duration_s=<from agent metadata>, mode=<absent | partial>
   ```

   Continue to the next dispatch in step 2; do NOT retry this scope this run (the next nightly run will catch it). Note: a `forgetter_no_envelope` entry in audit § Errors will surface as a soft cue at next /hi via `check_autoevo_ran`.

2. **Persist the inline content to disk.** When the envelope is present, derive a scope slug from `scope_path` (e.g., `<paths.wip>` → `wip`, `<paths.research>` → `research`) and write the inline findings block to:

   ```
   $PATHS_FINDINGS/decay-${RUN_TS}-<scope-slug>.md
   ```

   Use the `Write` tool. The orchestrator HAS write capability; Forgetter does not. The persisted report is human-readable + grep-able + survives across runs as a historical decay record.

3. **Parse `findings_inline`** for routing in step 3. Read `mode`, `summary`, and the per-category arrays. Note the mode: `full` (complete sweep) or `partial` (budget-exhausted) — both have valid findings; `partial` triggers an audit-log § Errors row like `forgetter_partial: scope=<scope>, candidates_evaluated=<n>, reason=<budget | maxTurns-self-stop>` for transparency.

The three persisted decay-report files plus their parsed envelopes feed step 3.

## Step 3: Parse decay reports + route by trust band

Read each decay report. For each finding, route per `protocols/autoevo.md` § Trust bands:

### 3a. Redundant findings

Read the `confidence` field from the Forgetter row. **If `confidence` is absent** (older Forgetter version, partial report, or any row without explicit confidence), treat as `medium` and route to the pending queue — never auto-apply on an unspecified confidence. This rule is documented in `.claude/agents/forgetter.md` § Confidence Field "Backward compatibility" and enforced uniformly across all category routings below.

Route:

| Confidence | Threshold check | Route |
|---|---|---|
| `high` | 3+ peers ≥ 0.85 AND all in `<paths.wip>/` AND all + candidate untouched > 30d | Auto-apply (step 4) |
| `medium` or `low` | Anything else | Append to pending queue (step 5) |

### 3b. Low-signal findings

| Confidence | Threshold check | Route |
|---|---|---|
| `high` | All 5 conditions AND mtime > 365d ago | Auto-apply (step 4) |
| `medium` | All 5 conditions AND mtime > 90d ago but ≤ 365d | Append to pending queue (step 5) |

### 3c. Time-stale findings

Always route to pending queue. Era judgments and content-stale phrasing are intent-laden; never auto-act.

### 3d. Contradicted findings

For each contradicted finding, dispatch Challenger (synchronous):

```
Dispatch Agent (subagent_type=challenger) with:
  task: probe-contradiction
  wiki_claim: <claim text from finding>
  contradicting_peer: <path>
  contradiction_signal: <phrase>
```

Challenger returns `genuine` | `rhetorical`. Route:

| Challenger verdict | Route |
|---|---|
| `rhetorical` | No op; one-line note in audit log § "Contradicted rhetorical dismissals" |
| `genuine` | Append to pending queue with category `contradicted` (wiki rewrites need user approval; never auto-apply) |

## Step 4: Auto-apply ops (commit-per-op)

For each finding routed to auto-apply, perform the op then commit immediately. Order: process redundant first (merges create surviving notes), then low-signal (archives are simpler).

### 4.0. Tombstone check (skip recently-reverted clusters)

Before snapshotting anything for auto-apply, run **both** tombstone layers per `protocols/autoevo.md` § Revert tombstones. The git-log layer is primary (catches plain `git revert` with no extra user action); the TOML layer is the additional explicit-skip list.

For each finding the bot is about to auto-apply, compute the candidate's cluster hash:

```bash
CLUSTER_HASH=$(printf '%s\n' "${SOURCES[@]}" | sort -u | shasum -a 1 | cut -c1-12)
```

**Layer A — git-log auto-detection.** Walk the last 90 days of compact commits, extract their `cluster_hash:` body lines, and check whether each one has a corresponding revert. The revert detection matches against the FULL commit message (`%B` = subject + body) because `git revert <sha>` puts the original full SHA in the body (`This reverts commit <40-char sha>.`), not in the `Revert "..."` subject line:

```bash
SKIP_REASON=""
COMMIT_SHAS=$(git -C "$OV" log --since='90 days ago' --grep='^\[autoevo:' --format='%H' || true)
for SHA in $COMMIT_SHAS; do
  ORIG_HASH=$(git -C "$OV" show -s --format='%b' "$SHA" 2>/dev/null \
    | awk '/^cluster_hash:/ {print $2; exit}')
  [ -z "$ORIG_HASH" ] && continue
  [ "$ORIG_HASH" != "$CLUSTER_HASH" ] && continue
  # SHA matches our cluster. Check if it was reverted: grep the full message
  # body (%B) of all revert-shaped commits in the window for the original SHA.
  # `git revert` writes "This reverts commit <full-sha>." in the body, so a
  # full-SHA grep is the correct match (a short-SHA grep against the subject
  # would miss the standard revert format).
  REVERTED=$(git -C "$OV" log --since='90 days ago' --grep='^Revert "' --format='%H %B' \
             | awk -v s="$SHA" '$0 ~ s {print $1; exit}' || true)
  if [ -n "$REVERTED" ]; then
    SHA_SHORT=$(git -C "$OV" rev-parse --short=7 "$SHA")
    SKIP_REASON="tombstoned cluster — user reverted ${SHA_SHORT} on $(git -C "$OV" show -s --format='%cs' "$REVERTED")"
    break
  fi
done
if [ -n "$SKIP_REASON" ]; then
  # Route this finding to pending queue (step 5) with $SKIP_REASON, continue.
  continue
fi
```

**Layer B — explicit TOML tombstones.** Read `$OV/_meta/autoevo_tombstones.toml` (if it exists). For each entry whose `cluster_hash` matches the candidate AND whose `expires_at` is either absent or after today, route the finding to the pending queue with the entry's `reason`.

```bash
TOMB_FILE="$OV/_meta/autoevo_tombstones.toml"
if [ -f "$TOMB_FILE" ]; then
  SKIP_REASON=$(uv run --quiet python3 - <<EOF
import tomllib, datetime, sys
data = tomllib.loads(open("$TOMB_FILE").read())
today = datetime.date.today().isoformat()
for t in data.get("tombstone", []):
    if t.get("cluster_hash") != "$CLUSTER_HASH":
        continue
    exp = t.get("expires_at")
    if exp and str(exp) < today:
        continue
    print(f"explicit tombstone: {t.get('reason', 'no reason given')}")
    sys.exit(0)
EOF
)
  if [ -n "$SKIP_REASON" ]; then
    # Route to pending queue with $SKIP_REASON, continue.
    continue
  fi
fi
```

The git-log walk runs in O(commits in last 90 days × peers per candidate) — bounded since the bot writes ~3-5 commits per night maximum. If `git log` is slow on very large vault histories, future optimization: cache `cluster_hash` → revert-status mapping in a sidecar file.

### 4.1. Snapshot creation (orchestrator)

Every auto-apply dispatch is snapshot-first per `.claude/agents/curator.md` § Auto-apply rule 1. Before calling Curator, the orchestrator copies each source file (the redundancy candidate plus its peers, OR the single low-signal note) to the cache dir bound in step 0. Curator works from these stable copies, so an external edit mid-run cannot corrupt the merge.

```bash
# For each auto-apply finding (redundant or low-signal):
SOURCES=( <candidate-relative-path> <peer1-relative-path> <peer2-relative-path> ... )
SNAPSHOT_PATHS=()
SNAP_FAILED=""
for SRC in "${SOURCES[@]}"; do
  # Slug includes the path with separators flattened to dashes, so a cluster
  # with two same-basename notes in different tier dirs (e.g., wip/foo.md and
  # research/foo.md) produces distinct snapshot files instead of one
  # overwriting the other. The leading basename keeps slugs human-readable
  # in the cache dir listing.
  PATH_SLUG=$(printf '%s' "$SRC" | sed 's|/|-|g' | sed 's|\.md$||')
  SNAP="$PATHS_CACHE/autoevo-${RUN_TS}-${PATH_SLUG}.md"
  if [ ! -f "$OV/$SRC" ]; then
    SNAP_FAILED="source missing on disk: $SRC"
    break   # abort snapshotting; the outer finding handler routes to pending queue
  fi
  if ! cp "$OV/$SRC" "$SNAP"; then
    SNAP_FAILED="cp failed for $SRC"
    break
  fi
  SNAPSHOT_PATHS+=("$SNAP")
done

if [ -n "$SNAP_FAILED" ]; then
  echo "abort finding: $SNAP_FAILED"
  # Route the WHOLE finding to the pending queue with reason $SNAP_FAILED.
  # Do not call Curator with a partial $SNAPSHOT_PATHS array.
  continue   # outer loop over findings
fi
```

The inner `break` is critical: a `continue` in the inner loop would only skip ONE source and let the outer logic proceed with an incomplete snapshot set. Auto-apply on a partial set could merge fewer notes than expected (silently dropping content) or — worse — pass through Curator's `auto_apply_safe` check on the surviving snapshots and commit a malformed merge. Never auto-apply on a partial snapshot set.

The same `$PATH_SLUG` convention is used by the recovery loop in step 4c (`cp "$PATHS_CACHE/autoevo-${RUN_TS}-$(printf '%s' "$SRC" | sed 's|/|-|g; s|\.md$||').md" "$OV/$SRC"` when restoring after a failed commit).

### 4a. Redundant auto-merge

For each redundant-high finding:

1. **Snapshot.** Run step 4.1 over the source set: the candidate path PLUS every peer path from the Forgetter row. The candidate is the note Forgetter flagged; it is one of the sources to merge, not a separate target.
2. **Pick the canonical surviving path.** Among the snapshotted sources, find the one with the OLDEST mtime in `$OV/` (not in the snapshot, which is fresh-copied). That filesystem path is the `target_path` — keep its slug to preserve any inbound `[[wikilinks]]` to that title.

```bash
TARGET_REL=$(for SRC in "${SOURCES[@]}"; do
  echo "$(stat -f %m "$OV/$SRC" 2>/dev/null || stat -c %Y "$OV/$SRC")|$SRC"
done | sort -n | head -1 | cut -d'|' -f2-)
TARGET_PATH="$OV/$TARGET_REL"
```

3. **Dispatch Curator** with the snapshot set and the chosen target:

```
Dispatch Agent (subagent_type=curator) with:
  operation: compact
  mode: auto-apply
  band: redundant-high
  source_notes: [<every snapshotted source: candidate + peers>]
  snapshot_paths: [<all values from $SNAPSHOT_PATHS array>]
  target_path: <TARGET_REL — the oldest-mtime source path>
  evidence: <Forgetter row evidence dict including confidence: high>
```

Curator with `mode: auto-apply` runs its scope guards (curator.md § Auto-apply hard refusal conditions), runs the Content Preservation Checklist, and returns the proposal envelope with `auto_apply_safe: true | false`. If `auto_apply_safe: false`, route the finding to the pending queue (step 5) with the returned `refusal_reason`; do not proceed to step 4 below for that finding.

4. **Write merged content** to `$TARGET_PATH` (`Write` tool — overwrite the existing surviving file with the merged body Curator returned).
5. **Stage explicit paths.** Do NOT use `git add -A`. Explicit staging keeps the pre-existing "abort on unexpected paths" check in step 4c meaningful:

```bash
git -C "$OV" add -- "$TARGET_REL"
for SRC in "${SOURCES[@]}"; do
  [ "$SRC" = "$TARGET_REL" ] && continue   # the survivor stays
  git -C "$OV" rm -- "$SRC"
done

# Sanity check: only the expected paths should be staged.
STAGED=$(git -C "$OV" diff --cached --name-only | sort)
EXPECTED=$(printf '%s\n' "$TARGET_REL" "${SOURCES[@]}" | grep -v "^$TARGET_REL$" | sort -u; echo "$TARGET_REL")
if [ "$STAGED" != "$(echo "$EXPECTED" | sort -u)" ]; then
  echo "abort op: staged paths diverged from expected"
  git -C "$OV" restore --staged .
  # Restore the survivor target FIRST — Write already overwrote it with the
  # merged body. `git restore` returns it to HEAD's content (pre-op state).
  # Without this, the survivor stays mutated and the next pre-flight gate
  # (dirty tree) fires forever.
  git -C "$OV" restore -- "$TARGET_REL" 2>/dev/null || true
  # Restore deleted sources from snapshots so the working tree returns to pre-op state.
  # Slug must match the step 4.1 convention (path-with-slashes-to-dashes) so collisions
  # between same-basename notes in different dirs are preserved.
  for SRC in "${SOURCES[@]}"; do
    [ "$SRC" = "$TARGET_REL" ] && continue   # survivor handled above
    [ -f "$OV/$SRC" ] && continue
    SRC_PATH_SLUG=$(printf '%s' "$SRC" | sed 's|/|-|g; s|\.md$||')
    cp "$PATHS_CACHE/autoevo-${RUN_TS}-${SRC_PATH_SLUG}.md" "$OV/$SRC"
  done
  # Log to audit § Errors, route finding to pending queue.
  continue
fi
```

6. **Commit:**

```bash
# Compute cluster_hash for the tombstone mechanism (protocols/autoevo.md § Revert tombstones).
CLUSTER_HASH=$(printf '%s\n' "${SOURCES[@]}" | sort -u | shasum -a 1 | cut -c1-12)

git -C "$OV" commit -m "$(cat <<EOF
[autoevo:redundant] <relative dir under \$OV>: merge <N> notes into <target slug>

Source notes:
- <peer1 relative path under \$OV/> (retrieval <score>, mtime <YYYY-MM-DD>)
- <peer2 ...>
- ...

Auto-band: redundant-high (3+ peers ≥ 0.85, all > 30d cold, mode=<stub|real>, floor=<0.5|0.6>)
cluster_hash: ${CLUSTER_HASH}
Revert: git revert <future sha>

Co-Authored-By: Atelier Autoevo Bot <noreply@atelier.local>
EOF
)"
COMMIT_SHA=$(git -C "$OV" rev-parse HEAD)
```

The `cluster_hash` line is the load-bearing signal the next night's run reads to detect "this cluster was reverted; skip" (per `protocols/autoevo.md` § Revert tombstones). Removing it breaks the tombstone safety mechanism.

7. **Append to audit log § "Auto-applied"** with the SHA and a one-line summary.

### 4b. Low-signal auto-archive (routed through Curator)

The low-signal-high path also goes through Curator's `mode: auto-apply` to re-verify (per curator.md § Auto-apply for `band: low-signal-high`) that no inbound `[[wikilink]]` references appeared since the Forgetter sweep. This catches the race where the user linked the note between the sweep and the archive step.

For each low-signal-high finding:

1. **Snapshot.** Run step 4.1 over the single source path.
2. **Dispatch Curator** with operation: archive:

```
Dispatch Agent (subagent_type=curator) with:
  operation: archive
  mode: auto-apply
  band: low-signal-high
  source_notes: [<source relative path under $OV/>]
  snapshot_paths: [<single value from $SNAPSHOT_PATHS array>]
  target_path: <$PATHS_ARCHIVE relative to $OV>/decayed/<RUN_DATE>-<slug>.md
  evidence: <Forgetter row evidence dict including confidence: high, words: <N>, mtime: <YYYY-MM-DD>>
```

Curator re-runs the inbound-wikilink grep and returns `auto_apply_safe: true | false`. If `false`, route the finding to the pending queue.

3. **Collision check.** Refuse if the archive target already exists (extremely rare given the date prefix, but cheap to guard):

```bash
# Derive a safe slug from the source path. Use the full path-with-slashes-to-dashes
# convention from step 4.1 so two same-basename notes in different subdirs produce
# distinct archive targets (e.g., wip/foo.md → wip-foo, research/foo.md → research-foo).
SOURCE_REL="<source relative path under $OV>"   # bound from the Forgetter row
SLUG=$(printf '%s' "$SOURCE_REL" | sed 's|/|-|g; s|\.md$||')
ARCHIVE_REL_DIR="${PATHS_ARCHIVE#$OV/}/decayed"   # portable shell strip; macOS realpath has no --relative-to
TARGET_REL="${ARCHIVE_REL_DIR}/${RUN_DATE}-${SLUG}.md"
if [ -e "$OV/$TARGET_REL" ]; then
  echo "abort op: archive target exists: $TARGET_REL"
  # Route to pending queue, log to audit § Errors.
  continue
fi
mkdir -p "$OV/$ARCHIVE_REL_DIR"
```

4. **Move and commit** (use `git mv` so git records this as a rename, not delete+add):

```bash
git -C "$OV" mv -- "<source relative path under $OV>" "$TARGET_REL"
git -C "$OV" commit -m "$(cat <<'EOF'
[autoevo:low-signal] archive: <slug> after <N> days inactive

words: <N>, links_in: 0, tags: 0, mtime: <YYYY-MM-DD>
Moved: <source path under $OV> -> <TARGET_REL>

Auto-band: low-signal-high (all 5 Forgetter conditions + >365d cold)

Co-Authored-By: Atelier Autoevo Bot <noreply@atelier.local>
EOF
)"
COMMIT_SHA=$(git -C "$OV" rev-parse HEAD)
```

Append to audit log § "Auto-applied".

### 4c. Failure handling

If any commit fails (hook error, permission, disk full, GPG signing prompt):

1. Do NOT retry the same op. Single failure aborts the entire auto-apply phase for this run.
2. **Roll back the failed op's staged state** so the working tree returns to a clean baseline. The merge wrote a file and deleted sources; the archive moved a file. Both must be reversed:

```bash
# Unstage any partial work the failed op produced.
git -C "$OV" restore --staged .

# Restore the working tree to HEAD so deleted sources reappear and the merged
# target reverts to its pre-op content. Snapshots are still in $PATHS_CACHE
# if a deeper recovery is needed, but `git restore .` is the cheapest correct undo.
git -C "$OV" restore .

# Archive ops create a freshly-untracked file at $TARGET_REL via `git mv` —
# `git restore .` does not touch untracked files, so the archive target
# lingers as untracked dirt and the next pre-flight `git status --porcelain`
# gate aborts forever. Detect by checking if $TARGET_REL is tracked at HEAD;
# if not (i.e., this was an archive op), remove the orphan file.
if [ -n "$TARGET_REL" ] && [ -f "$OV/$TARGET_REL" ]; then
  if ! git -C "$OV" ls-files --error-unmatch -- "$TARGET_REL" >/dev/null 2>&1; then
    rm -f "$OV/$TARGET_REL"
  fi
fi
```

3. Run `git -C "$OV" status` and write its output verbatim to audit log § "Errors". The dirty-tree pre-flight gate at next run will catch any residue.
4. Continue to step 5 (pending queue write) — the queue is independent of git state. Any auto-apply findings that did not run get routed to the queue with reason `"auto-apply phase aborted on commit failure"`.

## Step 5: Append to pending queue

Read existing `$OV/_meta/autoevo_pending.toml` (or initialize empty if missing). For each finding routed to the queue in step 3:

```toml
[[pending]]
id = "<RUN_TS>-<category>-<seq>"   # seq is per-run zero-padded counter
category = "redundant" | "time-stale-A" | "time-stale-B" | "contradicted" | "low-signal"
proposed_action = "<short imperative>"
evidence_summary = "<one-line evidence>"
peers = ["<relative paths under $OV/>"]   # for redundant; otherwise omit
proposed_at = "<RUN_DATE>"
last_surfaced = "<RUN_DATE>"
surface_count = 0
status = "pending"
```

Write the updated TOML atomically (write to a sibling `.tmp` then `mv` over the target). The TOML library available is `tomllib` (stdlib, read-only); for writes, emit TOML by hand WITH PROPER ESCAPING — evidence text routinely contains quoted phrases, paths with backslashes, or embedded newlines. An unescaped value produces invalid TOML and bricks `/autoevo-review` + the cue parser until the user repairs by hand.

Minimal pattern the orchestrator follows for each new pending entry:

```python
# Inline pattern; no shared helper exists yet.
def _escape_toml_basic_string(s: str) -> str:
    """TOML basic-string escaping per https://toml.io/en/v1.0.0#string."""
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )

def emit_pending_entry(entry: dict) -> str:
    esc = _escape_toml_basic_string
    lines = ["[[pending]]"]
    for key in ("id", "category", "proposed_action", "evidence_summary",
                "proposed_at", "last_surfaced", "status"):
        v = entry[key]
        lines.append(f'{key} = "{esc(v)}"')
    lines.append(f"surface_count = {int(entry['surface_count'])}")
    if entry.get("peers"):
        peers = ", ".join(f'"{esc(p)}"' for p in entry["peers"])
        lines.append(f"peers = [{peers}]")
    return "\n".join(lines) + "\n\n"
```

Append the rendered block(s) to the existing file content, write to `autoevo_pending.toml.tmp`, then `mv` into place. Field order matches the schema in `protocols/autoevo.md` § Pending queue. After writing, sanity-check by re-parsing with `tomllib.loads(open(path).read())` — if parse fails, the write is rejected and the orchestrator logs to the audit log § Errors. This is the only commit-blocking validation on queue writes; tomllib's parse step is fast and catches every TOML-spec violation deterministically.

Commit the queue update (this is a `_meta/` config change, not a destructive op, but still belongs in git history for queue-state audit):

```bash
git -C "$OV" add _meta/autoevo_pending.toml
git -C "$OV" commit -m "$(cat <<'EOF'
[autoevo:queue] _meta: append <N> pending findings from <RUN_DATE> sweep

Categories: redundant=<n>, time-stale-A=<n>, time-stale-B=<n>, contradicted=<n>, low-signal=<n>

Co-Authored-By: Atelier Autoevo Bot <noreply@atelier.local>
EOF
)"
```

## Step 6: Run /lint and report

```bash
uv run scripts/lint.py --json > "$PATHS_CACHE/autoevo-${RUN_TS}-lint.json"
```

Read the JSON. Append a summary to audit log § "Lint": counts by severity. **Do not** auto-fix lint findings. Lint is informational here; user reviews next /hi.

If lint reports ERROR-level findings that look caused by this run's ops (parse errors in merged note, broken @cite from deleted source), record under audit-log § "Errors" with the finding details — these need human review.

## Step 7: Write audit log

Path: `<paths.agent_findings>/autoevo-applied-<RUN_DATE>.md` (resolve via `$PATHS_FINDINGS` bound in step 0). If a file exists for `<RUN_DATE>` (rare — multiple runs same day), append a new `## Run` section to it. **Always write this file, even when a pre-flight gate aborted the run** — the Skipped / Errors sections are what surface the abort to the user at next /hi via `check_autoevo_ran` in `scripts/cues.py`. Format:

```markdown
## Autoevo Run: <RUN_DATE> <HH:MM>

Run ID: <RUN_TS>

### Auto-applied (<N>)
- [autoevo:redundant] <scope>: merge <N> notes into <slug> — sha <abbrev sha>
- [autoevo:low-signal] archive: <slug> — sha <abbrev sha>
- (...)

### Logged to pending queue (<M>)
- redundant: <n> entries (ids: <list>)
- time-stale-A: <n> entries
- time-stale-B: <n> entries
- contradicted: <n> entries (Challenger genuine)
- low-signal: <n> entries

### Contradicted rhetorical dismissals (<K>)
- <wiki claim> vs. <peer path>: Challenger judged "rhetorical"
- (...)

### Lint
- ERROR: <n>, WARN: <n>, INFO: <n>

### Skipped (reason)
- (none) | <gate>: <detail>

### Errors
- (none) | <error description>
```

Commit the audit log. The path resolves via the registry-bound `$PATHS_FINDINGS` from step 0:

```bash
FINDINGS_REL="${PATHS_FINDINGS#$OV/}"   # portable shell strip; macOS realpath has no --relative-to
git -C "$OV" add -- "${FINDINGS_REL}/autoevo-applied-${RUN_DATE}.md"
git -C "$OV" commit -m "$(cat <<'EOF'
[autoevo:audit] agent-findings: record nightly run <RUN_DATE>

Auto-applied: <N>, Pending: <M>, Errors: <K>

Co-Authored-By: Atelier Autoevo Bot <noreply@atelier.local>
EOF
)"
```

The audit log itself being committed means `git log --grep='\[autoevo:audit\]'` gives a chronological index of every nightly run.

## Step 8: Dry-run override

If env var `DRY_RUN=1`:
- Run steps 1-3 normally (gates + sweep + routing).
- For step 4: print the proposed ops + commit messages to stdout, do **not** execute them.
- For step 5: print the proposed queue entries, do **not** write the TOML.
- For step 7: print the audit-log content, do **not** write or commit.
- Exit 0.

Use during initial deployment or after band-threshold tuning, then unset to resume autonomous mode.

## Step 9: Exit cleanly

Print one summary line to stdout (captured to `/tmp/com.atelier.autoevo-nightly.out` via the plist's `StandardOutPath`):

```
autoevo-nightly <RUN_DATE>: auto=<N>, pending=<M>, dismissed=<K>, errors=<E>, lint_errors=<L>
```

Exit code:
- `0` — ran cleanly (whether or not anything was found).
- `0` — pre-flight gate aborted (audit log records the skip).
- `1` — fatal error during a step (audit log records details; user reviews next /hi).

The cue at next /hi surfaces the audit log's Skipped / Errors sections regardless of exit code.

## Edge cases

- **No findings at all.** Forgetter sweeps return empty reports; steps 4-5 are no-ops. Step 6-7 still run and produce a minimal audit log with all sections "(none)". This is a valid clean night.
- **Forgetter returns `mode: partial`.** A sweep hit `time_budget_s`. Use whatever findings came back; note "partial sweep on `<scope>`" in audit log § "Errors" (so the user knows next-night might catch more).
- **Forgetter dispatch returns no envelope** (no `---forgetter-result---` markers in the agent output). Covered by step 2a: log to audit § Errors as `forgetter_no_envelope: scope=<scope_path>, ...` and continue to the next dispatch. Do not retry this scope this run.
- **Target path = no source path** (rare for redundant: when the orchestrator picks a new canonical slug not matching any source filename). In step 4a, write the new file, delete all sources, commit. The merged content is the canonical record.
- **Curator refuses an op.** Curator's scope guards (wiki, daily-notes, non-working-tier) refuse with an error envelope. Log under § "Errors" with the refusal reason; continue to next op.
- **Mid-run, $OV becomes dirty (external edit).** Unlikely at 5am but possible. Detect at each commit step: if `git diff --cached` includes paths the bot didn't touch, abort the auto-apply phase and dump everything remaining to the pending queue. Log under § "Errors".
- **Queue TOML corrupted.** If reading the existing pending queue fails (parse error), do NOT overwrite. Write the proposed entries to a `autoevo_pending.toml.new` sidecar, log under § "Errors" with the parse error, and surface as a cue. User fixes manually.

## What this command does NOT do

- Does not push to `origin` (per `protocols/repo-conventions.md` § "$OV git push policy").
- Does not edit daily notes.
- Does not auto-apply on `<paths.wiki>/`.
- Does not run synthesis, reflection, or any user-facing output beyond the audit log.
- Does not re-index the semantic store. Lazy rebuild at next `scripts/semantic.py query` is assumed.

## Related

- `protocols/autoevo.md` — the load-bearing contract.
- `.claude/agents/forgetter.md` — decay heuristics.
- `.claude/agents/curator.md` — op executor (with `--auto-apply` extension).
- `.claude/commands/autoevo-review.md` — companion morning triage command.
- `.claude/commands/lint.md` — invoked in step 6.
- `protocols/repo-conventions.md` § "$OV git push policy" — partially overridden carve-out.
