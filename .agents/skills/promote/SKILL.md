---
name: promote
description: "Run the Atelier `/promote` workflow in Codex using the shared command registry. Use when the user explicitly invokes `$promote`. Promote L2 working notes into a schema-compliant L4 wiki entry."
---

## Atelier Command

Run the explicit Codex `$promote` skill. Its authoritative workflow source is
the Claude Code `/promote` command specification.

1. Read `AGENTS.md` and `CLAUDE.md`.
2. Read the authoritative `.claude/commands/promote.md` command specification directly.
3. Execute it in this thread using the Codex adaptation table in `AGENTS.md`.
4. Treat text following `$promote` as command context or arguments.
5. Do not start a nested Codex process; complete the workflow in this thread.
