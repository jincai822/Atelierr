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

If you run the same routines on multiple Macs, set up DynamoDB as the cross-machine lock:

```bash
# Install aws-vault (stores AWS credentials in macOS Keychain)
brew install aws-vault
aws-vault add atelier   # prompts for Access Key ID + Secret

# Create the DynamoDB table (one-time, from any machine)
aws-vault exec atelier -- python3 scripts/routine_lock.py setup-table

# Tell routine_watch.toml to use DynamoDB
# Add to $OV/_meta/routine_watch.toml:
#   [coordination]
#   backend = "dynamodb"
```

The table uses provisioned mode (1 WCU / 1 RCU) which is always-free tier. TTL auto-expires stale locks after 1 hour.

Skip this step for single-machine setups — the lock module is a no-op when `coordination.backend` is absent or `"none"`.

### Step 3 — install and load the plist

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
# Skip the hostname stagger for immediate execution:
ATELIER_SKIP_STAGGER=1 launchctl start com.atelier.autoevo-nightly
tail -f /tmp/com.atelier.autoevo-nightly.out /tmp/com.atelier.autoevo-nightly.err
```

Or run the wrapper directly:

```bash
ATELIER_SKIP_STAGGER=1 scripts/routine_runner.sh autoevo-nightly /autoevo-nightly
```

The audit log for the run itself (what the bot did to the vault) lives at `$OV/agent-findings/autoevo-applied-<YYYY-MM-DD>.md`; the `/tmp/` files capture the wrapper + Claude CLI output. The claim file at `$OV/_meta/routine_runs/autoevo-nightly/<date>.toml` records status and timing.

The first manual run is also the auth smoke test: if `claude -p` hits an auth prompt, it'll log to `/tmp/com.atelier.autoevo-nightly.err`. Resolve by running `claude` interactively once to refresh credentials; the cached auth then survives subsequent headless invocations.

## Debugging coordination

```bash
# Check lock status for today's cycle:
aws-vault exec atelier -- python3 scripts/routine_lock.py status autoevo-nightly

# Check local claim file:
cat "$OV/_meta/routine_runs/autoevo-nightly/$(date +%Y-%m-%d).toml"

# Test lock acquire/release without running the routine:
aws-vault exec atelier -- python3 scripts/routine_lock.py acquire autoevo-nightly --cycle test
aws-vault exec atelier -- python3 scripts/routine_lock.py release autoevo-nightly --cycle test
```

## Path assumptions

The plist delegates to `scripts/routine_runner.sh`, which assumes:

- Atelier checked out at `~/atelier/`. Edit the plist's `ProgramArguments` path if elsewhere.
- `claude` on `PATH` via `/opt/homebrew/bin` (Apple Silicon Homebrew) or `/usr/local/bin` (Intel). The `EnvironmentVariables` block in the plist sets `PATH` because `launchd` does not inherit a login shell's `PATH`.
- `python3` on `PATH` (for `routine_lock.py`). Homebrew Python or system Python both work.
- `$OV` is exported from one of: `~/.zprofile`, `~/.profile`, or `~/atelier/harness/env.local.sh` (see Install step 1). The wrapper tries all three in order and aborts loudly if none work.
- `$OV/cache/` and `$OV/_meta/routine_runs/` are created on every run via `mkdir -p`, so a fresh install does not silently fail on missing directories.
- For multi-machine coordination: `aws-vault` on `PATH` and an `atelier` profile in Keychain (see Install step 2). Without it, the lock is a no-op.

## What the schedule does NOT do

- Does not push commits to `origin`. Per `protocols/repo-conventions.md`, push remains user-driven.
- Does not touch `<paths.wiki>/`, `<paths.daily_notes>/`, or anything outside the four working tiers.
- Does not start a new session if an existing session was active within the last 6h (see `protocols/autoevo.md` § Pre-flight gates).
