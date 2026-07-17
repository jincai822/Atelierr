# Runtime Adapters Protocol

Atelier should run under Claude Code and Codex without forking the reflection
system. The core idea is to separate four concerns:

| Concern | Owned by | Example |
|---|---|---|
| Workflow | `protocols/`, command specs | `/hi`, `/weekly`, `/review` |
| Role | `harness/agents.toml`, agent specs | Researcher, Synthesizer, Reviewer |
| Capability | `harness/capabilities.toml` | `semantic_query`, `write_local_file`, `web_search` |
| Runtime and model | adapters, local CLI config + `profile/models.toml` (gitignored) | one runtime per call, model bound per profile |

This follows the OpenClaw lesson: the system can use different models when the
provider and runtime are explicit metadata, not assumptions buried inside the
workflow.

## Runtime Surfaces

| Runtime | Reads | Native surface | Status |
|---|---|---|---|
| Codex | `AGENTS.md` | `.agents/skills/`, `.codex/agents/`, `.codex/hooks.json`, Codex CLI and review | First-class native harness; shipped default |
| Claude Code | `CLAUDE.md` | `.claude/agents/`, `.claude/commands/`, `.claude/skills/` (entry hints only; not authoritative dispatch) | First-class native harness; selectable default |

`.claude/skills/` is a Claude Code-only surface holding **entry hints**, not authoritative dispatch. Claude Code matches a skill's frontmatter description against user phrasing semantically: the LLM judges relevance, not substring. On a match the skill forwards into `/hi`; the canonical intent router in `harness/intents.toml` is still the single decision point for which agents run. Codex does not read `.claude/skills/`; repo-scoped skills under `.agents/skills/` provide its native entry surface. `$atelier` handles broad routing and harness work, while explicit command skills such as `$weekly` and `$review` read the matching `.claude/commands/*.md` specification directly. Skill exposure is additive at both runtime edges and produces zero workflow duplication.

`scripts/harness_lint.py` enforces structural invariants only: skill name matches its directory, frontmatter has a non-empty description that mentions `/hi` (delegation), and the skill name corresponds to an existing `intents.<name>` row. Coherence between the skill's prose description and the intent it exposes is human-curated — substring-checking an LLM-judged trigger surface would be the wrong tool.

The command files remain Claude-shaped source specifications, but both runtimes
have native execution edges. Claude Code consumes `AskUserQuestion` and
`Agent(...)` directly. Codex maps them to its available choice UI and the
project agents under `.codex/agents/`, falling back to numbered questions or
sequential role emulation only when the active surface lacks those features.

`harness/commands.toml` and `harness/agents.toml` are the registries shared by
both runtimes. They map portable names to the current Claude source files.
Codex command skills and agent TOMLs point directly to those sources;
`scripts/harness_lint.py` enforces the mapping.

Codex reserves slash-prefixed input for built-in TUI commands. Its native
repo-shared counterpart is an explicit `$skill` mention: Claude `/weekly` maps
to Codex `$weekly`, `/hi` maps to `$hi`, and so on. Each command skill is
explicit-only (`allow_implicit_invocation: false`) and reads its authoritative
Claude command specification directly. Interactive use does not launch a
helper process. From an external shell, quote the skill mention, for example
`codex -C . '$weekly'`. When a Claude-shaped workflow tells the user to invoke
another registered project command, Codex renders the `$command` form. Native
Codex built-ins such as `/hooks` keep their slash form.

Codex lifecycle hooks live in `.codex/hooks.json`. `SessionStart` reuses
`scripts/cues.py --hook --runtime codex`; `UserPromptSubmit` refreshes the
session lock and runs `scripts/intent_coverage.py intent-hook --runtime codex`;
`Stop` runs the shared shadow-log cleanup. Claude Code keeps the corresponding behavior in
`.claude/settings.json`, using `SessionEnd` for cleanup. Both edges call shared
scripts rather than duplicating hook logic.

## Runtime Selection

`harness/runtimes.toml` declares both native CLI surfaces and ships with Codex
as the default. `scripts/atelier_runtime.py` is an optional selector around
those surfaces. It never expands a workflow into an adapter prompt: it sends
the registered name directly as `$<command>` to Codex or `/<command>` to
Claude Code.

Resolution order is:

1. `--runtime codex|claude` for one selector invocation.
2. `ATELIER_RUNTIME=codex|claude` for one process and for automation.
3. Gitignored `harness/runtime.local.toml`, written by
   `python3 scripts/atelier_runtime.py use <runtime>`.
4. The committed Codex default in `harness/runtimes.toml`.

Direct CLI invocation always remains valid. The selector exists so interactive
launches and local scheduled routines can share a durable preference. The
launchd wrapper uses the same resolution chain unless `ATELIER_RUNTIME` is
explicitly present in its environment.

## Provider-Neutral Rules

- Do not add new provider-specific model names to shared protocols. Use a model
  profile from `harness/models.toml`.
- Do not add new provider-specific tool names to shared protocols. Use a
  capability from `harness/capabilities.toml`.
- Existing `.claude/` files may keep Claude frontmatter and tool names. They are
  adapter surfaces.
- New shared docs should say "run a semantic query" or "write a local file",
  not name provider-specific tools, unless they are documenting an adapter
  itself.
- If a runtime lacks a feature, degrade explicitly. Example: if Codex cannot
  spawn the registered project agent in a given environment, read the target
  agent spec and run the step sequentially.

## Model Profiles

Agent roles ask for capability classes, not fixed provider models. Profile
schema (identity names and runtime-neutral reasoning tiers) is defined in
`harness/models.toml` (committed); the
actual provider/model bindings (model id, endpoint URL, env var, request
extras) live in `profile/models.toml` (gitignored). Loaders merge schema +
bindings at runtime.

Voice dispatch model: the single source of truth is
`protocols/orchestrator.md` -> "Voice Dispatch". The agent-to-voices mapping
lives in `harness/agents.toml` as a `voices` keyed inline table per agent
(`{native = "...", direct = "..."}` or single-leg variants). `native` means
the selected runtime's project-agent surface, not Claude specifically. Claude
resolves its concrete model from agent frontmatter; Codex agents inherit the
selected Codex model unless their project adapter pins a model. The shared
`reasoning_tier` maps to Codex `model_reasoning_effort` at the adapter edge.
External provider bindings remain in gitignored `profile/models.toml`.
Shadow telemetry resolves native identity through
`scripts/shadow.py native-model`: Claude uses the role binding, while Codex
uses the dynamic `codex_native` slot so it never inherits an Anthropic cost
row.

## Capability Profiles

Capabilities describe what an agent needs, independent of the runtime:

- `read_file`
- `search_text`
- `run_shell`
- `semantic_query`
- `web_search`
- `web_fetch`
- `write_local_file`
- `spawn_role` (native `.codex/agents/<role>.toml`, sequential fallback)
- `ask_user`

The concrete tool mapping is in `harness/capabilities.toml`.

## Codex Command Execution

When a user asks Codex to run an Atelier command:

1. Read `AGENTS.md`.
2. Read `CLAUDE.md` for domain rules and safety constraints.
3. Read `.claude/commands/<command>.md` for the workflow.
4. Translate Claude-specific constructs using the table in `AGENTS.md` § Codex Adaptation.
5. Dispatch referenced roles through `.codex/agents/<role>.toml`; the adapter
   instructs the subagent to read the authoritative `.claude/agents/` brief.
   If subagents are unavailable, emulate the brief sequentially and disclose it.
6. Prefer local `$OV/` files, `rg`, and `uv run scripts/semantic.py`.
7. Ask before any local file write under `$OV/`. **Exception: Scribe capture operations** (`daily_note`, `dining_row`, `gtd_entry`, `people_stub`, `generic`) write directly without an approval gate — the user has already authored the raw content via chat and verbatim preservation is the trust property. Other agents and ad-hoc orchestrator writes still ask first.
8. Report any downgraded capability, such as missing web access or unavailable
   subagent dispatch.

For command invocation and fresh-session recipes, see `AGENTS.md` § Codex
Quick Recipes.
