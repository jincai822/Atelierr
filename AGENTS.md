# AGENTS.md — Atelier

Root instructions for Codex and other non-Claude runtimes. Claude Code reads
`CLAUDE.md`; Codex reads this file. Treat both as the same behavioral contract.

This system is **the Atelier** — a workshop wrapping the user's **œuvre**
(accumulating body of work, kept under `$OV/`). The user is the **Painter**;
agents collectively are **le cercle**. For the full vocabulary and the
15-operator archetype map, see `protocols/atelier.md`.

Codex can also discover the repo-scoped `atelier` skill in `.agents/skills/atelier/`.

Before user-facing reflection work, read `CLAUDE.md` for the domain rules. The
operational Claude-to-Codex tool mapping lives in this file (§ Codex
Adaptation, below). The conceptual contract (workflow / role / capability /
runtime separation, model and capability profiles) lives in
`protocols/runtime-adapters.md`; consult it when adding a new role, command,
or runtime, not for routine command execution.

## Critical Rules

`CLAUDE.md` is the single source of behavioral rules. Codex MUST read it at
session start; Critical Rules, Reading Rules, Writing Rules, and Coaching
Style there apply equally under Codex. Do not restate them here; this file
documents the runtime contract only.

## Runtime Contract

- Shared behavior belongs in `CLAUDE.md`, `AGENTS.md`, `protocols/`, `harness/`,
  `frameworks/`, `sources/`, and `scripts/`.
- Runtime-specific behavior belongs at the edge: `.claude/`, `.codex/`, local
  CLI config, MCP config, or adapter documentation.
- `.claude/commands/*.md` are command specifications. In Codex, read the matching
  command file and adapt the tool syntax rather than treating the file as
  unusable. `harness/commands.toml` is the portable command registry.
- `.claude/agents/*.md` are role specifications. Codex exposes them through
  thin project adapters in `.codex/agents/*.toml`; each native agent reads the
  matching role brief. If subagents are unavailable or disallowed by
  higher-priority runtime rules, emulate the role sequentially in the main
  session and disclose the downgrade. `harness/agents.toml` is the portable
  role registry.
- Model names in agent frontmatter are harness assumptions. The neutral mapping
  lives in `harness/models.toml`.
- Tool names in agent frontmatter are runtime affordances. The neutral mapping
  lives in `harness/capabilities.toml`.

## Codex Adaptation

When a command spec uses Claude Code syntax, adapt it this way:

| Claude surface | Codex behavior |
|---|---|
| `Read` | Read the local file. |
| `Grep` / `Glob` | Use `rg` / `rg --files` with scoped paths. |
| `Bash` | Use the shell tool with project-relative paths. |
| `Write` / `Edit` | Use `apply_patch` or the runtime's local-file write tool to create or modify project files. |
| `AskUserQuestion` | Use a native choice UI when available; otherwise ask a concise numbered question. |
| `Agent(...)` | Dispatch the matching `.codex/agents/<role>.toml` project agent when permitted; otherwise run the role sequentially from its `.claude/agents/*.md` brief. |
| `WebSearch` / `WebFetch` | Use web search when enabled; otherwise state that web access is unavailable. |
| User-facing `/<project-command>` | Render the registered Codex form `$<project-command>`. Keep actual Codex built-in slash commands such as `/hooks` unchanged. |

## Codex Quick Recipes

High-frequency operations. Lift these directly instead of re-deriving from `protocols/runtime-adapters.md` each session:

| Need | Command |
|---|---|
| Semantic vault search | `uv run scripts/semantic.py query "<concept>" --top 10` |
| Today's daily note | `cat "$OV/daily-notes/$(date +%Y/%m/%Y-%m-%d).md"` (before 03:00 local also read previous day) |
| Wiki entry by title | `rg -l "<title>" "$OV/wiki/"` |
| Privacy gate | `uv run scripts/privacy_check.py --json` |
| Harness state / lint | `python3 scripts/harness_lint.py --json` |
| Run a command in Codex | Invoke `$<name>` (for example, `$weekly`) |
| Launch a fresh Codex workflow | `codex -C . '$<name>'` |
| Run a one-shot Codex workflow | `codex exec -C . '$<name>'` |
| Show selected external runtime | `python3 scripts/atelier_runtime.py status` |
| Launch through selected runtime | `python3 scripts/atelier_runtime.py run <name>` |

For Claude project commands such as `/hi`, `/review`, `/weekly`, and `/lint`,
Codex exposes matching explicit skills: `$hi`, `$review`, `$weekly`, and
`$lint`. Each skill reads the corresponding `.claude/commands/<name>.md` file
directly and runs the workflow under this adaptation table. `$reflect` remains
an alias for `$hi`.

### Codex command skills

Codex CLI reserves slash-prefixed input for its own built-in TUI commands. The
native repo-shared equivalent is an explicit skill mention:

| User says | Codex behavior |
|---|---|
| `$hi` | Read the `hi` skill's declared command source and execute it in the current thread. |
| `$hi <context>` | Apply the `/hi` routing specification to the context, then execute the matched procedure. |
| `$reflect` or `$reflect <context>` | Execute the `hi` workflow; `reflect` is an alias. |
| `$<command>` | Read `.claude/commands/<command>.md` and execute it in the current thread. |

Command skills declare `allow_implicit_invocation: false`, so ordinary prose
containing words such as "read" or "review" does not trigger them. Type `$` in
the Codex composer to discover available skills. Do not expose the bot-invoked
`autoevo-nightly` workflow as a user skill; offer `$autoevo-review` when
appropriate.

Never start a nested Codex process for an in-session command. Read the source
declared by the command skill and complete the workflow in the active thread.

`/autoevo-nightly` is bot-invoked (headless `codex exec`, launchd at 05:00)
and is not exposed as a Codex user skill. The shipped scheduler default is
Codex. `python3 scripts/atelier_runtime.py use claude` makes Claude the local
default for both the external launcher and launchd; `ATELIER_RUNTIME` remains
the one-process override. Claude `/autoevo-review` and Codex
`$autoevo-review` are the morning triage surfaces for its pending queue.
Both workflows are defined by `protocols/autoevo.md` and registered with
`direct_only = true` in `harness/commands.toml`.

### Codex `$hi` parity

Use `$hi` or `$hi <text>`. The skill reads its declared command source and
`harness/intents.toml`, applies the same routing and clarification rules, and
executes the selected procedure in the current thread. When the matched intent
declares `parallel = true`, dispatch the listed project agents as one batch.

To launch a fresh workflow from an external shell or automation:

```bash
codex -C . '$hi'                     # interactive TUI, fresh session
codex -C . '$hi context'             # fresh session with context
codex exec -C . '$lint'              # non-interactive
codex resume --last '$promote'        # continue the last session
codex fork --last '$promote'          # branch from the last session
```

Default is a fresh session. `--resume` (`codex resume --last`) and `--fork`
(`codex fork --last`) carry prior session context and are only recommended
for commands marked `resume_friendly = true` in `harness/commands.toml`.

Codex discovers explicit commands under `.agents/skills/` and native role
adapters under `.codex/agents/`. Project lifecycle hooks live in
`.codex/hooks.json`; review and trust them with `/hooks` after a fresh checkout
or hook change.

## Project Trust (Codex)

Project shell trust lives in `~/.codex/config.toml`:

```toml
[projects."/path/to/atelier"]
trust_level = "trusted"
```

Trust allows Codex to load the project's `.codex/` config, hooks, and rules.
It does not disable shell approvals or the sandbox; those remain controlled by
the active approval policy and sandbox mode.

## System Evolution

When changing the harness:

1. Keep the core protocol provider-neutral.
2. Add or update model identities and runtime-neutral reasoning tiers in
   `harness/models.toml` (provider bindings live in gitignored
   `profile/models.toml`).
3. Add or update capability mappings in `harness/capabilities.toml`.
4. Add or update role mappings in `harness/agents.toml`.
5. Add or update command mappings in `harness/commands.toml`.
6. Add or update native CLI mappings and the shipped default in
   `harness/runtimes.toml` when runtime behavior changes.
7. Add or update intent router rows in `harness/intents.toml` (trigger phrases
   → dispatch shape for `/hi`).
8. Update `.agents/skills/atelier/SKILL.md` if the Codex workflow changes.
9. Keep native Codex agent adapters and hooks under `.codex/`; keep their
   shared behavior in the registries, role briefs, and scripts.
10. Keep Claude-specific syntax in `.claude/` and Codex-specific notes in
   `.codex/`.
11. Run `python3 scripts/harness_lint.py` before finishing.
12. Run `python3 scripts/harness_smoke.py` after helper or registry edits.
