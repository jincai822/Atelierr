---
name: atelier
description: Run or modify Atelier workflows, commands, agents, intent routing, and harness portability in this repo. Use for broad Atelier harness work or to adapt Claude commands such as `/hi` to native Codex skills such as `$hi`.
---

## Atelier

Use this skill when the user asks to run or modify Atelier workflows, commands,
agents, or harness portability.

## Quick Start

1. Read `AGENTS.md` and `CLAUDE.md`.
2. Read `protocols/runtime-adapters.md` only when changing or debugging
   cross-runtime behavior.
3. Invoke known commands through their explicit repo skills (`$hi`, `$weekly`,
   `$decision`, `$explore`, `$promote`, `$lint`, and so on).
4. Read the command skill's declared `.claude/commands/<command>.md` source
   directly and execute it in the current thread.
   For `$hi`, use the injected route packet and read only its registry-owned
   `procedure`; load the full intent table only on packet fallback. A fallback
   is a semantic handoff through `intents.general`, never implicit reflection.
5. Do not launch Codex recursively.
6. Discover native roles under `.codex/agents/` and inspect them with `/agent`.
7. Load only the selected `.claude/commands/<command>.md` spec and any directly
   referenced agent or protocol files.
8. For external launches, `scripts/atelier/atelier_runtime.py` resolves the committed
   Codex default, the gitignored local preference, and one-process overrides.
   It sends the workflow name directly to the selected native CLI surface.
9. For local scheduled routines, inspect ownership with
   `uv run scripts/atelier/routine_owner.py status`; transfer all local routines to the
   current machine only after unloading the source scheduler, using
   `uv run scripts/atelier/routine_owner.py claim --force --source-stopped`.
10. Keep private routine support/profile mappings under `$OV`, keep generic
    profiles in `harness/routine_profiles.toml`, and run
    `python3 scripts/atelier/routine_audit.py audit --check-system --json` before
    enabling or handing off launchd jobs.
11. Keep private skill sources under `<paths.private_features>/`. Link the same
    source directory into Claude and Codex user skill discovery; do not copy
    the skill body or add its name to committed registries.

## Command Execution

Claude Code command specs are the current workflow source. In Codex, adapt them:

- Codex CLI slash input is reserved for built-in TUI commands. Use explicit
  command skills such as `$hi`, `$weekly`, `$decision`, and `$lint`. Each skill
  reads the matching Claude command specification directly and runs it in the
  active thread. `allow_implicit_invocation: false` prevents command names from
  hijacking ordinary prose. `$reflect` runs `$hi`.
  Frozen bot-invoked workflows such as `autoevo-nightly` have no shorthand or
  active registry entry; do not launch them.
- `Read` means read the local file.
- `Grep` and `Glob` mean use `rg` or `rg --files` with scoped paths.
- `Bash` means use the local shell.
- `AskUserQuestion` means use a native choice UI when available, otherwise ask
  a concise numbered question.
- `Agent(...)` means dispatch the matching project agent from
  `.codex/agents/<role>.toml` when permitted. If dispatch is unavailable, run
  the role sequentially from `.claude/agents/<role>.md` and disclose the downgrade.
- Translate user-facing references to registered Claude project commands from
  `/name` to Codex `$name`. Do not translate real Codex built-ins such as
  `/hooks` or `/agent`.
- All vault writes go through the orchestrator (Write/Edit) after explicit user
  approval. Reflection records under `<paths.reflections>/` are user-authored:
  the system reads them but does not write to them. Sole exception:
  user-dictated raw content recorded verbatim by the Scribe agent
  (`daily_note` operation); any other system write targeting a reflection is
  refused. Retired `forgetter`, `decay_scan`, and `autoevo-nightly` workflows
  must not be launched; memory lifecycle behavior belongs to the application
  memory module.

### Atelierr read-only bridge

Workflows may search, list, and read Atelierr's top-level application-owned
memory note files under `<paths.memory>` and cognition entries under
`<paths.cognition>` as source material. Both surfaces are always read-only:
never write, move, delete, or edit their notes/frontmatter, and never invoke
memory lifecycle or write-back operations. The framework-owned `<paths.wiki>`
and `<paths.reflections>` surfaces follow the existing orchestrator plus
explicit user-approval write rules. `<paths.cognition>` is physically nested
under `<paths.wiki>` but is a read-only exception, so cognition files and their
frontmatter must never be written. This exception grants no write access to
any other `<paths.memory>` path. Cite the exact source path and keep excerpts
to the minimum needed for the claim.

For command discovery, type `$` in the Codex composer. Do not guess an
unavailable command.

## Harness Changes

When editing the harness:

1. Keep shared behavior provider-neutral.
2. Update `harness/commands.toml` for command additions or removals.
3. Update `harness/agents.toml` for agent additions or removals.
4. Update `harness/models.toml` for model-profile changes.
5. Update `harness/capabilities.toml` for tool or runtime changes.
6. Update `harness/runtimes.toml` for native CLI or shipped-default changes.
7. Keep each native voice identity's runtime-neutral `reasoning_tier`
   synchronized with the Codex adapter's `model_reasoning_effort`.
8. Keep `.codex/agents/` and `.codex/hooks.json` synchronized with the shared
   registries and lifecycle contracts.
9. Keep private feature names and behavior out of committed registries; the
   source-root contract is defined in `protocols/private-features.md`.
10. Run `python3 scripts/atelier/harness_lint.py` before finishing.
11. Run `.venv/bin/python scripts/atelier/harness_smoke.py` after helper or registry
    edits when the project environment exists; otherwise use the configured
    dependency runner.
12. For roles without a direct intent or command route, use only the bounded
    marker-based `indirect_callers` or `manual_entrypoints` evidence in
    `harness/agents.toml`; never restore retired `used_by` rows or keyword-only
    caller claims.

Keep command skills thin: they point to shared Claude command specifications
and must not copy workflow bodies into the Codex edge.
