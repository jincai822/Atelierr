# launchd — macOS scheduled jobs

Atelier-managed `launchd` plists for local scheduled work. Model-driven
autoevo behavior is governed by `protocols/autoevo.md`; deterministic semantic
cache maintenance is governed by `sources/semantic.md`.

These are user-installable artifacts: copy to `~/Library/LaunchAgents/` and load with `launchctl`. Public, vault-agnostic plists live here. Private routine-specific plists may live under `$OV/_meta/launchd/`; what gets loaded into launchd is always a machine-local copy.

## Plists

| File | Schedule | Contract |
|---|---|---|
| `com.atelier.autoevo-nightly.plist` | 05:00 primary, hourly deferred recovery, wake/login catch-up | `protocols/autoevo.md` + `.claude/commands/autoevo-nightly.md` |
| `com.atelier.semantic-index.plist` | 07:30 and 19:30 local, plus load/login catch-up | Owner-gated, offline, timeout-bounded `scripts/semantic.py index --if-stale` |

## Install

### Step 1 — declare your vault path (one-time, per machine)

The wrapper script (`scripts/routine_runner.sh`) sources `~/atelier/harness/env.local.sh`. Create the file if it does not exist:

```bash
cat > ~/atelier/harness/env.local.sh <<'EOF'
# Atelier per-user environment overrides. Gitignored. Sourced by:
#   - scripts/routine_runner.sh (invoked by launchd plists)
# Mirror whatever your shell config (~/.zshrc / ~/.zprofile) sets so
# launchd's non-interactive shell has the same view.
export OV="/path/to/your/vault"
EOF
```

If `OV` is exported from `~/.zprofile` or `~/.profile` already (login-shell scopes), the wrappers pick it up from there — `env.local.sh` is the fallback for users whose `OV` lives only in `.zshrc` (interactive-only). A wrapper aborts loudly (`ERROR: OV not set ...`) if none of those sources work; the error surfaces in that job's `/tmp/com.atelier.*.err` log.

### Step 2: claim this machine as the local-routine owner

The recommended setup has one eligible machine at a time. Claiming creates a
gitignored random identity under `harness/`, publishes it to the shared vault,
and changes `routine_watch.toml` to `coordination.backend = "owner"`:

```bash
uv run scripts/routine_owner.py claim
uv run scripts/routine_owner.py status
```

Other machines may keep their plist copies loaded. Their runners exit before
starting a model or writing a claim file. `ATELIER_COORDINATION=none` cannot
downgrade this shared fence.

To migrate all local routines later, first unload their plists on the source
machine and wait for any active cycle to finish. Then run this on the destination:

```bash
uv run scripts/routine_owner.py claim --force --source-stopped
```

`--source-stopped` explicitly asserts that the source scheduler is quiescent;
Drive sync cannot prove this atomically. The transfer also fails if any locally
synchronized shared claim is still `status = "running"`. Wait for
the active cycle to finish or resolve the stale claim before retrying. A
successful transfer advances the shared owner generation. Then install and
load the plists there. The old machine becomes ineligible as soon as its
synchronized vault sees the new owner record.

### Step 2b: optional active-active DynamoDB coordination

Use this only when several machines are intentionally eligible and exactly one
should win each cycle. Credentials must be **non-interactive**: the job runs
with the screen locked, so `boto3` reads a dedicated static-key profile from
`~/.aws/credentials`, with no Keychain prompt.

```bash
# 1. Create a scoped IAM user (one-time, from a machine with admin creds).
#    Policy: DynamoDB GetItem/PutItem/UpdateItem on atelier-routine-locks only.
cat > /tmp/atelier-lock-policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["dynamodb:GetItem","dynamodb:PutItem","dynamodb:UpdateItem"],
    "Resource": "arn:aws:dynamodb:us-west-2:*:table/atelier-routine-locks"
  }]
}
JSON
aws iam create-user --user-name atelier-routine-lock
aws iam put-user-policy --user-name atelier-routine-lock \
  --policy-name atelier-lock --policy-document file:///tmp/atelier-lock-policy.json
aws iam create-access-key --user-name atelier-routine-lock   # note the keys

# 2. Write the keys to a non-interactive profile, then lock the file down.
cat >> ~/.aws/credentials <<'INI'

[atelier-lock]
aws_access_key_id = AKIA...
aws_secret_access_key = ...
region = us-west-2
INI
chmod 600 ~/.aws/credentials

# 3. Create the DynamoDB table (one-time, from any machine).
#    Use `uv run` — boto3 lives in the project venv, not system python3.
AWS_PROFILE=atelier-lock uv run scripts/routine_lock.py setup-table

# 4. Tell routine_watch.toml to use DynamoDB:
#   [coordination]
#   backend = "dynamodb"
```

The runner reads `AWS_PROFILE` (default `atelier-lock`; override via `ATELIER_LOCK_AWS_PROFILE`). The table uses provisioned mode (1 WCU / 1 RCU, always-free tier). Running locks are never taken over automatically because prior external effects may be uncertain. A diagnostic `lease_expires_at` is recorded for operators. Only a successfully completed marker receives the table's seven-day TTL.

Skip this step for the recommended single-owner setup.

### Step 3: prepare headless Codex

The shipped default uses `codex exec`. Authenticate once interactively and
review the repo's project hooks before relying on the unattended schedule:

```bash
codex login status
codex -C .
# In the TUI, open /hooks and trust the reviewed project hooks.
```

The scheduled invocation is ephemeral, starts from a narrow sanitized
environment, and runs without interactive approvals. Before claiming a cycle,
the runner resolves the routine's generic profile from
`harness/routine_profiles.toml` and verifies local readiness with
`scripts/routine_audit.py`. Ordinary routines use `workspace-write`, start in
a fresh disposable neutral directory, and add `$OV` as a writable root while
keeping the Atelier checkout read-only. This avoids persistent vault project
instructions crossing into later profiles. Only the maintenance profile grants
Atelier writes. The profile's `allowed_commands` binding is checked before the
cycle is claimed, and its permissions are passed as a strict model-level
allowlist rather than claimed as a shell or connector ACL. Research profiles enable live web only when
declared. Native web search and shell networking are distinct: ordinary
research, synthesis, and live-web digest profiles keep shell networking
disabled. Native web search does not grant arbitrary networked CLI access.
Connector profiles retain user-level Codex configuration; other
profiles ignore it. Only bounded maintenance workflows that must write git
metadata use `danger-full-access`; its shell network is explicitly recorded as
unrestricted because that sandbox does not isolate it. Every preflight probe
and model run has a hard epoch-based wall-clock timeout, so macOS sleep, a
permission prompt, or a hung provider cannot extend a one-hour budget into an
all-day process. The model-facing shell
also sets `ZDOTDIR` to `harness/routine-shell`, so it cannot load interactive
aliases, override `$OV`, or import credentials exported by `~/.zshrc`.
Once preflight succeeds, the wrapper starts `caffeinate -i -w <runner-pid>`.
This keeps the Mac awake while the stagger, model run, artifact validation,
and cleanup are active. It does not wake a Mac that was already asleep when
the schedule became due.
The runner passes both `-a never` and the explicit
`approval_policy="never"` config override. The second guard is necessary for
connector profiles that retain user configuration; otherwise a personal
approval reviewer can restore `on-request` and stall an unattended run.

Audit all local jobs, fixed Codex availability, machine ownership, dependencies,
plugins, plist mappings, and loaded launchd state:

```bash
python3 scripts/routine_audit.py audit --check-system --json
```

Unattended local routines always use Codex. `atelier_runtime.py use claude` and
`ATELIER_RUNTIME=claude` affect interactive launchers only.

### Step 4: install and load the plist

```bash
PLIST=com.atelier.autoevo-nightly.plist
cp "scripts/launchd/${PLIST}" "$HOME/Library/LaunchAgents/${PLIST}"
launchctl load "$HOME/Library/LaunchAgents/${PLIST}"

PLIST=com.atelier.semantic-index.plist
cp "scripts/launchd/${PLIST}" "$HOME/Library/LaunchAgents/${PLIST}"
launchctl load "$HOME/Library/LaunchAgents/${PLIST}"
```

Install private local-routine plists from the shared vault on the owner machine:

```bash
for SOURCE in "$OV"/_meta/launchd/com.atelier.routine-*.plist; do
  PLIST=$(basename "$SOURCE")
  cp "$SOURCE" "$HOME/Library/LaunchAgents/$PLIST"
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$PLIST"
done
```

Confirm it loaded:

```bash
launchctl list | grep atelier
```

The expected output: one line per loaded plist, with PID `-` (no current run) and exit code `0` (last run, or just-loaded).

## Wake the Mac at the scheduled time

`launchd` will not wake a sleeping Mac on its own. A missed
`StartCalendarInterval` is delivered when the machine next wakes. The
autoevo plist also uses `RunAtLoad` so login or LaunchAgent reload catches a
missed cycle. Before 05:00, the runner targets yesterday only when yesterday
did not complete; otherwise it waits for today's primary attempt. The claim
reservation prevents duplicate same-cycle work if wake, RunAtLoad, and a
calendar event arrive close together.

The calendar interval checks at minute 0 every hour. Missing `Hour` in a
`StartCalendarInterval` dictionary is a launchd wildcard. Completed, failed,
running, and uncertain claims exit before capability or model work. A
`deferred` deterministic preflight records `retry_after_epoch`; checks before
that time also exit cheaply, and the first due check can reacquire the cycle.
Session activity retries at the exact six-hour lock expiry. Other deterministic
blockers retry after one hour, so newly committed user work or repaired local
dependencies are recognized at the next calendar check. An unchanged blocker
for the same cycle reuses its committed audit, so hourly checks do not create
duplicate audit commits.

Use `pmset` to schedule a proactive wake just before the primary time:

```bash
# Wake the Mac at 04:55 every day so the 05:00 job lands on a running system.
sudo pmset repeat wakeorpoweron MTWRFSU 04:55:00
```

Verify:

```bash
pmset -g sched
```

Cancel with:

```bash
sudo pmset repeat cancel
```

## Uninstall

```bash
launchctl unload "$HOME/Library/LaunchAgents/com.atelier.autoevo-nightly.plist"
rm "$HOME/Library/LaunchAgents/com.atelier.autoevo-nightly.plist"
launchctl unload "$HOME/Library/LaunchAgents/com.atelier.semantic-index.plist"
rm "$HOME/Library/LaunchAgents/com.atelier.semantic-index.plist"
sudo pmset repeat cancel
```

## Manual test (without waiting for 5am)

```bash
# Note: an env-var prefix does NOT propagate through `launchctl start` (the
# job runs in launchd's environment, not your shell's), so this runs WITH the
# 0-120s hostname stagger:
launchctl start com.atelier.autoevo-nightly
tail -f /tmp/com.atelier.autoevo-nightly.out /tmp/com.atelier.autoevo-nightly.err
```

Or run the Codex wrapper directly, skipping the stagger:

```bash
ATELIER_SKIP_STAGGER=1 \
  scripts/routine_runner.sh autoevo-nightly /autoevo-nightly
```

Test semantic maintenance separately. It is deterministic, owner-gated, and
offline; it skips model loading when the index is current:

```bash
scripts/semantic_index_runner.sh
uv run scripts/semantic.py status --format json
tail -f /tmp/com.atelier.semantic-index.out /tmp/com.atelier.semantic-index.err
```

The audit log for the run itself (what the bot did to the vault) lives at `$OV/agent-findings/autoevo-applied-<YYYY-MM-DD>.md`; the `/tmp/` files capture aggregate wrapper and Codex CLI output. Each acquired attempt also records a private event journal under `$OV/cache/` in its claim. The claim file at `$OV/_meta/routine_runs/autoevo-nightly/<date>.toml` records status, timing, journal path, and verification evidence.

Verify that a cycle performed real Forgetter work rather than only completing
a preflight `noop`:

```bash
python3 scripts/autoevo_verify.py --cycle "$(date +%Y-%m-%d)" --json
```

For autoevo, `status = "completed"` additionally requires
`verification = "passed"`. The wrapper has then proved a real Forgetter sweep,
one committed decay report per returned sweep envelope, matching audit
sidecars, a committed clean vault, ordered claim-owned event markers, and
final Git evidence. Verification runs while the claim is
`completion-uncertain` with `verification = "pending"` so interruption cannot
leave a false success. A failed verification remains
`completion-uncertain`. Other routines use the general artifact attestation:
a fresh, nonempty file matching the routine's declared `output_dir` and
`file_pattern`.

`status = "deferred"` means the deterministic autoevo preflight wrote and
validated its audit artifact before Codex or the mutation phase started. The
claim's `retry_after_epoch` is the earliest automatic retry. The first hourly
calendar or RunAtLoad check at or after that time may reacquire the cycle.
`failed` and `completion-uncertain` still require explicit effects review.

The first manual run is also the auth smoke test. If `codex exec` cannot use the cached ChatGPT login, it logs the failure to `/tmp/com.atelier.autoevo-nightly.err`. Resolve it with `codex login`, then rerun `codex login status` and the direct wrapper test.

## Debugging coordination

```bash
# Confirm this machine owns local routines:
uv run scripts/routine_owner.py status

# Check lock status for today's cycle (uv run: boto3 lives in the venv):
uv run scripts/routine_lock.py status autoevo-nightly

# Check the canonical cycle claim. status=failed means the model or runner
# failed after acquisition; status absent means no cycle was acquired:
cat "$OV/_meta/routine_runs/autoevo-nightly/$(date +%Y-%m-%d).toml"

# Preflight and lock-acquire failures are machine-specific diagnostics:
ls -lt "$OV/_meta/routine_failures/autoevo-nightly/"

# After stopping the original process and reviewing its external effects,
# preserve a cycle whose effects completed:
uv run scripts/routine_lock.py recover <routine> --cycle <id> \
  --outcome completed --confirm-effects-reviewed

# Approve one same-cycle retry only when review confirms repeating is safe:
uv run scripts/routine_lock.py recover <routine> --cycle <id> \
  --outcome safe-to-retry --confirm-effects-reviewed

# Test lock acquire/release without running the routine:
AWS_PROFILE=atelier-lock uv run scripts/routine_lock.py acquire autoevo-nightly --cycle test
AWS_PROFILE=atelier-lock uv run scripts/routine_lock.py release autoevo-nightly --cycle test
```

Owner acquire atomically reserves the claim as `running`; a normal `failed`,
`completed`, or `completion-uncertain` claim cannot be acquired again. A
deterministic `deferred` claim can be consumed automatically because no model
or mutation phase began.
`safe-to-retry` changes the synchronized claim to `retry-approved`, which is
the manual recovery state owner acquire may consume. DynamoDB recovery updates
the same local claim and keeps a central `retry-approved` fence. Dynamo acquire
atomically consumes that state, so another machine may safely execute the
approved retry even before its local Drive copy converges.

## Path assumptions

The plists delegate to `scripts/routine_runner.sh` or
`scripts/semantic_index_runner.sh`. They assume:

- Atelier checked out at `~/atelier/`. Edit the plist's `ProgramArguments` path if elsewhere.
- `codex` on `PATH` via `/opt/homebrew/bin`, `/usr/local/bin`, or `~/.local/bin`. The plist and wrapper populate these locations because `launchd` does not inherit an interactive shell's `PATH`.
- `uv` on `PATH` (the runner invokes `routine_lock.py` via `uv run` so boto3 resolves from the project venv).
- `caffeinate` on `PATH` on macOS. The system audit checks it before local routines are considered ready.
- `$OV` is exported from one of: `~/.zprofile`, `~/.profile`, or `~/atelier/harness/env.local.sh` (see Install step 1). The wrapper tries all three in order and aborts loudly if none work.
- If `$OV` is inside macOS `~/Library/CloudStorage`, grant Full Disk Access to the background helper executable reported by the TCC log. Homebrew Python is the first helper that reads ownership policy. The model runtime may require its own grant on first use. Use the canonical `~/Library/CloudStorage/...` path in `env.local.sh`, not a legacy `~/Google Drive` alias. A denied prompt now times out and fails before claim creation.
- `$OV/cache/` and `$OV/_meta/routine_runs/` are created on every run via `mkdir -p`, so a fresh install does not silently fail on missing directories.
- For recommended single-owner coordination: a gitignored `harness/routine_owner.local.toml` identity matching `$OV/_meta/routine_owner.toml`.
- For optional active-active coordination: an `atelier-lock` profile in `~/.aws/credentials` (see Step 2b). Without it, DynamoDB mode fails loud rather than silently skipping.

## What the schedule does NOT do

- Does not push commits to `origin`. Per `protocols/repo-conventions.md`, push remains user-driven.
- Does not touch `<paths.wiki>/`, `<paths.daily_notes>/`, or anything outside the four working tiers.
- Does not start a new session if an existing session was active within the last 6h (see `protocols/autoevo.md` § Pre-flight gates).
