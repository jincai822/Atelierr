## Purpose

Nightly autonomous quality pass over `$OV`. The bot fires at 5:00 local, sweeps the working tiers for decay using Forgetter heuristics, auto-applies the high-confidence band, logs uncertain findings to a pending queue, and commits every destructive operation to git so `git revert` is the recovery path. Surfaces unresolved items at the next `/hi` via `scripts/cues.py`.

Companion docs:
- `.claude/agents/forgetter.md` — the four decay categories + firing heuristics this protocol acts on.
- `.claude/agents/curator.md` — the agent that performs the merge/archive ops (extended with `--auto-apply` mode by this protocol).
- `protocols/repo-conventions.md` § "$OV git push policy" — the user-driven push policy this protocol partially overrides.

## Carve-out from the $OV push policy

`protocols/repo-conventions.md` declares "the atelier does not auto-commit or auto-push; both are user-driven." Autoevo is the explicit exception:

- **Auto-commit: YES.** Every op the bot performs commits to `$OV`'s default branch before the next op starts. Git history is the recovery floor; without per-op commits, `git revert` cannot undo individual bad calls.
- **Auto-push: NO.** Push remains user-driven per the existing policy. Local commits are sufficient for recovery; remote replication is a deliberate user act.

## Schedule

macOS `launchd`, 5:00 local, daily.

- Plist: `~/Library/LaunchAgents/com.atelier.autoevo-nightly.plist`
- Wake-from-sleep: `pmset repeat wakeorpoweron MTWRFSU 04:55:00`
- Invocation: see the plist's `ProgramArguments` block, which delegates to `scripts/routine_runner.sh`. The wrapper sources `~/.zprofile` / `~/.profile` / `~/atelier/harness/env.local.sh` for `OV`, ensures `$OV/cache` and `$OV/_meta/routine_runs/<routine>/` exist, then runs `cd ~/atelier && claude -p "/autoevo-nightly"`. Launchd captures stdout/stderr to `/tmp/com.atelier.autoevo-nightly.out` and `.err` (configured via the plist's `StandardOutPath` / `StandardErrorPath`).
- The bot's own audit log (what the autoevo did to the vault) is separate: `$OV/agent-findings/autoevo-applied-<YYYY-MM-DD>.md`. The `/tmp/` files capture only the shell wrapper + Claude CLI output, useful for debugging launchd-level failures.

Reversible: `launchctl unload <plist>` + `pmset repeat cancel`.

## Pre-flight gates

The bot bails (writes a one-line entry to the audit log and exits 0) if any of these hold. Each abort surfaces as a cue at next `/hi` so the user knows the night was skipped.

| Gate | Check | Rationale |
|---|---|---|
| Session-active lock | `<paths.cache>/atelier-session-lock` exists AND mtime < 6h | User may be mid-session; avoid collision. |
| Dirty `$OV` working tree | `git -C "$OV" status --porcelain` non-empty | Don't compound user intent into bot commits. |
| Dirty zettelm submodule | same check inside `<paths.zettelm>/` | User is mid mobile-capture digest. |
| Privacy gate | `uv run scripts/privacy_check.py --json` returns `hit_count > 0` | Hard veto; never commit a leak. |

## Trust bands

### Auto-apply (no human in loop, each op commits)

| Category | Threshold | Op |
|---|---|---|
| Redundant | 3+ peers ≥ 0.85 retrieval AND all peers in `<paths.wip>/` AND all peers + candidate untouched > 30d | Curator merge (`--auto-apply redundant-high`) |
| Low-signal | All 5 Forgetter conditions hold AND untouched > 365d | `mv` to `<paths.archive>/decayed/<YYYY-MM-DD>-<slug>.md`. Never `rm`; archive is the recovery surface. |
| Contradicted (rhetorical) | Auto-Challenger probe says "rhetorical, not a real contradiction" | No op; audit-log entry only. |

### Log to pending queue (surface at /hi)

| Category | Threshold | Action |
|---|---|---|
| Redundant | 3+ peers ≥ 0.6 but below auto-band thresholds | Append to pending queue. |
| Time-stale (era-stale, Forgetter heuristic B) | Always | Append to pending queue. Era judgments are intent-laden; never auto-act. |
| Time-stale (content-stale, Forgetter heuristic A) | Always | Append to pending queue. |
| Contradicted (real) | Challenger probe confirms genuine contradiction | Append to pending queue. Wiki rewrites need human approval. |
| Low-signal | 5 conditions hold AND 90-365d untouched | Append to pending queue. |

### Never auto-act

The bot refuses any op under these paths regardless of finding:

- `<paths.wiki>/` and any localized shadow wikis declared in `[paths.wiki_localized]`.
- `<paths.daily_notes>/` (user-authored per the global writing rules; the sole system write path is Scribe `daily_note` verbatim capture, never autoevo).
- Any path outside `<paths.wip>/`, `<paths.research>/`, `<paths.reflections>/`, `<paths.agent_findings>/`.

Contradicted findings against L4 wiki entries always go to the pending queue, never auto-applied.

## Per-op commit policy

One commit per destructive op. Not one commit per night.

- **Identity**: the user's `git config user.name` / `user.email`. The bot acts as the user's automated extension; co-author trailer disambiguates.
- **Subject**: `[autoevo:<category>] <scope>: <summary>`. The `[autoevo:...]` prefix is the grep handle (`git log --grep='\[autoevo:'`).
- **Body**: includes the Forgetter evidence verbatim so revert reviewer has full context. Cite peer paths, retrieval scores, mtime, mode (stub/real), floor threshold.
- **Trailer**: `Co-Authored-By: Atelier Autoevo Bot <noreply@atelier.local>`.

Example — redundant merge:

```
[autoevo:redundant] wip: merge 3 notes into <slug>

Source notes:
- <paths.wip>/foo.md (retrieval 0.91, mtime 2025-12-01)
- <paths.wip>/bar.md (retrieval 0.88, mtime 2026-02-14)
- <paths.wip>/baz.md (retrieval 0.86, mtime 2026-03-05)

Auto-band: redundant-high (3 peers ≥ 0.85, all > 30d cold, mode=real, floor=0.6)
Revert: git revert <sha>

Co-Authored-By: Atelier Autoevo Bot <noreply@atelier.local>
```

Example — low-signal archive:

```
[autoevo:low-signal] archive: <slug> after 412 days inactive

words: 87, links_in: 0, tags: 0, mtime: 2025-04-04
Moved: <paths.wip>/<slug>.md -> <paths.archive>/decayed/2026-05-22-<slug>.md

Co-Authored-By: Atelier Autoevo Bot <noreply@atelier.local>
```

## Pending queue: `$OV/_meta/autoevo_pending.toml`

Sibling to `routine_watch.toml`. Schema:

```toml
schema_version = 1

[[pending]]
id = "20260522-050143-redundant-001"   # <bot-run-ts>-<category>-<seq>
category = "redundant"                  # redundant | time-stale-A | time-stale-B | contradicted | low-signal
proposed_action = "merge into <paths.wip>/<canonical-slug>.md"
evidence_summary = "3 peers, retrieval scores 0.78/0.72/0.61, mode=real"
peers = ["<paths.wip>/a.md", "<paths.wip>/b.md", "<paths.wip>/c.md"]
proposed_at = "2026-05-22"
last_surfaced = "2026-05-22"
surface_count = 0
status = "pending"   # pending | applied | dismissed | auto-dismissed
```

Lifecycle:

1. **Create**: `/autoevo-nightly` appends new entries for findings below the auto-band.
2. **Surface**: `scripts/cues.py` `check_autoevo_pending` reads the queue; if any entries are `status = "pending"` and not snoozed, fires one cue at session start with a category breakdown.
3. **Resolve**: `/autoevo-review` walks each pending entry; user picks apply / skip / defer / explain-more.
   - Apply → dispatch Curator in approval mode; on confirm, write entry's status to `applied` and commit.
   - Skip → set `status = "dismissed"`; record in audit log.
   - Defer → increment `surface_count`; update `last_surfaced`; reuse `cue_snooze.json` for the snooze interval.
4. **Auto-dismiss**: after 3 skips OR 30 days from `proposed_at` without resolution, set `status = "auto-dismissed"`, write one-line note to the audit log.

## Audit log: `<paths.agent_findings>/autoevo-applied-<YYYY-MM-DD>.md`

One file per night the bot ran. Format:

```markdown
## Autoevo Run: 2026-05-22 05:00

### Auto-applied (N)
- `[autoevo:redundant] wip: merge 3 notes` — sha abc1234
- `[autoevo:low-signal] archive: <slug>` — sha def5678

### Logged to pending queue (M)
- redundant: 2 entries
- time-stale-A: 1 entry
- contradicted: 1 entry (Challenger confirmed)

### Skipped (reason)
- Dirty $OV working tree at 04:59:58 (3 unstaged files in <paths.research>/)

### Errors
- (none)
```

If the bot bails at a pre-flight gate, the file is still written with the Skipped section populated; the cue surfaces the skip at next /hi.

## Concurrency lock: `<paths.cache>/atelier-session-lock`

Touched (`touch <file>`) by two hook paths wired in `.claude/settings.json`:

- **SessionStart hook** → runs `uv run scripts/cues.py --hook`, which touches the lock before running cue checks. Fires once per new Claude Code session.
- **UserPromptSubmit hook** → runs `uv run scripts/cues.py --touch-lock 2>/dev/null || true`, which refreshes the lock and exits without running any cue check (the lock path resolves via the paths registry). Fires on every user prompt so long-running sessions refresh the lock per prompt.

`/autoevo-nightly` reads the mtime; if mtime is within the last 6h, abort with reason "session-active lock fresh."

Six hours is the bound: with the UserPromptSubmit hook in place, an actively-used session refreshes the lock per prompt, so the only way to cross the 6h window is to leave a session genuinely idle for 6 hours. If the lock file is absent (fresh install, never run an interactive session), the bot interprets this as "no recent session" and proceeds — the permissive default for first-run cases.

If the lock-touch fails (cache dir unwritable, disk full), `cues.py` logs to stderr in `--verbose` mode but never breaks the hook. A persistently-failing lock leaves the 6h window operating on stale mtime; surface this by running `uv run scripts/cues.py --hook --verbose` manually to inspect.

## Recovery surfaces

| Surface | Use when |
|---|---|
| `git log --since='1 day ago' --grep='\[autoevo:'` | Skim what the bot did last night. |
| `git revert <sha>` | Undo one specific op. The bot's next run detects the revert and tombstones the cluster (see Revert tombstones below) so it does not re-merge the same notes. |
| `git revert <range>` | Undo a whole night. |
| `<paths.archive>/decayed/` | Recover a low-signal note that was auto-archived (still a regular file; `mv` back). |
| `<paths.agent_findings>/autoevo-applied-<date>.md` | At-a-glance summary without `git log`. Skipped/Errors sections also surface as a cue at next /hi (via `check_autoevo_ran` in `scripts/cues.py`). |

The archive directory is the asymmetric safety: deletions are revert-only; archive moves are revert + manual `mv` (both work). Low-signal ops use archive rather than `rm` because the recovery surface is friendlier than reading a git-revert diff to recreate the note.

## Revert tombstones

When the user runs `git revert <[autoevo:redundant] sha>`, the bot's next run would re-flag the same peer set, re-score it at the same retrieval, and re-merge within 24-72h — undoing the user's undo. The tombstone mechanism prevents this loop.

**The cluster hash.** Every redundant auto-merge commit body includes a `cluster_hash: <12 hex chars>` line, computed as the first 12 hex chars of `sha1` over the sorted list of source relative paths (one per line, LF-terminated). Two compact runs on the same exact source set produce the same hash; the hash is stable across re-runs and machines as long as the path strings match.

**Auto-detection at `/autoevo-nightly` step 4.0.** For each finding the bot is about to auto-apply:

1. Compute the candidate cluster's hash from its sorted source paths.
2. Walk `git log --since='90 days ago' --grep='^\[autoevo:'` for prior compact commits, extract each commit body's `cluster_hash` line.
3. For each matching hash, check whether that commit has a corresponding revert in the same window (`git log --since='90 days ago' --grep="^Revert.*<sha-prefix>"`).
4. If any match → route the finding to the pending queue with reason `"tombstoned cluster — user reverted <orig-sha> on <date>"`. Do not auto-apply.

This is fully git-native; no external state file is required for the common case. The bot inserts its own `cluster_hash:` lines into commit bodies, and `git log` is the lookup surface.

**Manual tombstones at `$OV/_meta/autoevo_tombstones.toml`.** For pre-existing reverts (before the cluster_hash convention shipped) or for user-driven "never merge these specific notes" rules, the file may also be populated by hand:

```toml
schema_version = 1

[[tombstone]]
cluster_hash = "abc123def456"   # 12 hex chars; matches the commit-body convention
sources = ["wip/foo.md", "wip/bar.md", "wip/baz.md"]
reason = "manual: these are intentionally separate per project X notes"
created_at = "2026-05-22"
expires_at = "2027-05-22"       # optional; absent = permanent
```

The auto-detection check above takes precedence; explicit tombstones are an additional skip list. Both are checked at step 4.0.

**Expiry.** Auto-detected tombstones expire after 90 days (re-evaluated on each run by re-querying git). Manual tombstones expire on their `expires_at` date if set, or persist indefinitely. Forgetter's confidence heuristics may legitimately re-fire on the same cluster after years if the underlying notes have changed; the tombstone is a brake on auto-apply, not a permanent blocklist.

## What is out of scope

- **Push.** Bot never pushes to `origin`; push remains user-driven per the `$OV` git push convention.
- **Daily notes.** Bot never reads them as autoevo targets. CLAUDE.md § Writing Rules forbids system writes to daily notes (sole exception: Scribe `daily_note` verbatim capture); this protocol upholds that.
- **Wiki rewrites.** Contradicted findings against L4 are always pending-queue, never auto-applied. The Curator wiki-edit path requires human approval.
- **Re-indexing decisions.** If the semantic index needs rebuild after a Curator delete/move, this protocol defers to whatever `scripts/semantic.py` does at next query (lazy rebuild assumed unless verified otherwise).

## Related

- `protocols/remote-routines.md` — for routines that run in claude.ai cloud. Autoevo does **not** use that path; it runs locally because the entire decay stack (`scripts/semantic.py`, `scripts/lint.py`, `scripts/trust.py`, Forgetter, Curator) is local-only.
- `protocols/repo-conventions.md` § "$OV git push policy" — the policy this carve-out partially overrides.
- `protocols/local-first-architecture.md` — tier model the trust bands key off.
- `.claude/agents/forgetter.md` — heuristic source.
- `.claude/agents/curator.md` — op executor (with `--auto-apply` extension).
