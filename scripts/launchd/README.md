# launchd — macOS scheduled jobs

Atelier-managed `launchd` plists for local scheduled work. Contract per `protocols/autoevo.md`.

These are user-installable artifacts: copy to `~/Library/LaunchAgents/` and load with `launchctl`. Each plist is committed to the atelier repo so the source-of-truth is versioned; what gets loaded into launchd is a copy.

## Plists

| File | Schedule | Contract |
|---|---|---|
| `com.atelier.autoevo-nightly.plist` | 05:00 local daily | `protocols/autoevo.md` + `.claude/commands/autoevo-nightly.md` |

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

If `OV` is exported from `~/.zprofile` or `~/.profile` already (login-shell scopes), the wrapper picks it up from there — `env.local.sh` is the fallback for users whose `OV` lives only in `.zshrc` (interactive-only). The wrapper aborts loudly (`ERROR: OV not set ...`) if none of those sources work, which surfaces in `/tmp/com.atelier.autoevo-nightly.err`.

### Step 2 — (optional) enable multi-machine coordination

If you run the same routines on multiple Macs, set up DynamoDB as the cross-machine lock. Credentials must be **non-interactive**: the job runs at 05:00 with the screen locked, when the macOS Keychain is unreadable. So `boto3` reads a dedicated static-key profile straight from `~/.aws/credentials` — no `aws-vault`, no Keychain prompt. (aws-vault is an interactive broker; using it for a headless 5am job is what silently broke earlier runs — a locked-Keychain failure was indistinguishable from benign lock contention.)

```bash
# 1. Create a scoped IAM user (one-time, from a machine with admin creds).
#    Policy: DynamoDB Get/Put/Update/DeleteItem on atelier-routine-locks only.
cat > /tmp/atelier-lock-policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["dynamodb:GetItem","dynamodb:PutItem","dynamodb:UpdateItem","dynamodb:DeleteItem"],
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

The runner reads `AWS_PROFILE` (default `atelier-lock`; override via `ATELIER_LOCK_AWS_PROFILE`). The table uses provisioned mode (1 WCU / 1 RCU, always-free tier). Stale locks from crashed runs are taken over at acquire time once their TTL (default 1 hour) passes; the table's TTL attribute only garbage-collects old items in the background.

Skip this step for single-machine setups — the lock module is a no-op when `coordination.backend` is absent or `"none"`.

### Step 3: prepare the selected headless runtime

The shipped default uses `codex exec`. Authenticate once interactively and
review the repo's project hooks before relying on the unattended schedule:

```bash
codex login status
codex -C .
# In the TUI, open /hooks and trust the reviewed project hooks.
```

The scheduled invocation is ephemeral, ignores user-level Codex configuration,
disables web search, starts from a narrow sanitized environment, and runs without interactive approvals. It uses
`danger-full-access` because the workflow must write per-operation commits to
`$OV/.git/`, which Codex `workspace-write` deliberately protects as read-only.
Use this permission profile only for the bounded autoevo bot.

To use Claude Code instead, authenticate its CLI and persist the local runtime
choice before loading or testing the job:

```bash
claude auth status
python3 scripts/atelier_runtime.py use claude
python3 scripts/atelier_runtime.py status
```

Run `python3 scripts/atelier_runtime.py use codex` to restore Codex. The local
preference is gitignored and is read by the launchd wrapper at execution time,
so the plist does not need to change.

### Step 4: install and load the plist

```bash
PLIST=com.atelier.autoevo-nightly.plist
cp "scripts/launchd/${PLIST}" "$HOME/Library/LaunchAgents/${PLIST}"
launchctl load "$HOME/Library/LaunchAgents/${PLIST}"
```

Confirm it loaded:

```bash
launchctl list | grep atelier
```

The expected output: one line per loaded plist, with PID `-` (no current run) and exit code `0` (last run, or just-loaded).

## Wake the Mac at the scheduled time

`launchd` will not wake a sleeping Mac on its own; it fires the job at the next opportunity once the machine is awake. Use `pmset` to schedule a wake just before the cron time:

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

Or run the wrapper directly with the selected default, skipping the stagger:

```bash
ATELIER_SKIP_STAGGER=1 \
  scripts/routine_runner.sh autoevo-nightly /autoevo-nightly
```

Use an environment override to test the other runtime without changing the
persistent preference:

```bash
ATELIER_SKIP_STAGGER=1 ATELIER_RUNTIME=codex \
  scripts/routine_runner.sh autoevo-nightly /autoevo-nightly
```

The audit log for the run itself (what the bot did to the vault) lives at `$OV/agent-findings/autoevo-applied-<YYYY-MM-DD>.md`; the `/tmp/` files capture the wrapper and Codex CLI output. The claim file at `$OV/_meta/routine_runs/autoevo-nightly/<date>.toml` records status and timing.

The first manual run is also the auth smoke test. If `codex exec` cannot use the cached ChatGPT login, it logs the failure to `/tmp/com.atelier.autoevo-nightly.err`. Resolve it with `codex login`, then rerun `codex login status` and the direct wrapper test. If Claude is selected, diagnose its authentication through `claude auth status` and the same direct wrapper test.

## Debugging coordination

```bash
# Check lock status for today's cycle (uv run: boto3 lives in the venv):
AWS_PROFILE=atelier-lock uv run scripts/routine_lock.py status autoevo-nightly

# Check local claim file (status=failed with an `error` line means the lock
# step itself failed — read the error; status absent means it never ran):
cat "$OV/_meta/routine_runs/autoevo-nightly/$(date +%Y-%m-%d).toml"

# Test lock acquire/release without running the routine:
AWS_PROFILE=atelier-lock uv run scripts/routine_lock.py acquire autoevo-nightly --cycle test
AWS_PROFILE=atelier-lock uv run scripts/routine_lock.py release autoevo-nightly --cycle test
```

## Path assumptions

The plist delegates to `scripts/routine_runner.sh`, which assumes:

- Atelier checked out at `~/atelier/`. Edit the plist's `ProgramArguments` path if elsewhere.
- `codex` on `PATH` via `/opt/homebrew/bin`, `/usr/local/bin`, or `~/.local/bin`. The plist and wrapper populate these locations because `launchd` does not inherit an interactive shell's `PATH`.
- `uv` on `PATH` (the runner invokes `routine_lock.py` via `uv run` so boto3 resolves from the project venv).
- `$OV` is exported from one of: `~/.zprofile`, `~/.profile`, or `~/atelier/harness/env.local.sh` (see Install step 1). The wrapper tries all three in order and aborts loudly if none work.
- `$OV/cache/` and `$OV/_meta/routine_runs/` are created on every run via `mkdir -p`, so a fresh install does not silently fail on missing directories.
- For multi-machine coordination: an `atelier-lock` profile in `~/.aws/credentials` (non-interactive static keys; see Install step 2). Without it, `boto3` finds no credentials and the lock acquire fails loud (exit 2, `status=failed` claim) rather than silently skipping. Single-machine setups (`backend = "none"`) need no credentials at all.

## What the schedule does NOT do

- Does not push commits to `origin`. Per `protocols/repo-conventions.md`, push remains user-driven.
- Does not touch `<paths.wiki>/`, `<paths.daily_notes>/`, or anything outside the four working tiers.
- Does not start a new session if an existing session was active within the last 6h (see `protocols/autoevo.md` § Pre-flight gates).
