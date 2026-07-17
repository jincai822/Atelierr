---
name: perks
description: "Run the Atelier `/perks` workflow in Codex using the shared command registry. Use when the user explicitly invokes `$perks`. Read-only perks and trip status dashboard over local trackers."
---

## Atelier Command

Run the explicit Codex `$perks` skill. Its authoritative workflow source is
the Claude Code `/perks` command specification.

1. Read `AGENTS.md` and `CLAUDE.md`.
2. Read the authoritative `.claude/commands/perks.md` command specification directly.
3. Execute it in this thread using the Codex adaptation table in `AGENTS.md`.
4. Treat text following `$perks` as command context or arguments.
5. Do not start a nested Codex process; complete the workflow in this thread.
