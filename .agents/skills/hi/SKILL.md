---
name: hi
description: "Run the Atelier `/hi` workflow in Codex using the shared command registry. Use when the user explicitly invokes `$hi`. Universal entry point: intent router for reflection, planning, action, reading, learning, capture, and more."
---

## Atelier Command

Run the explicit Codex `$hi` skill. Its authoritative workflow source is
the Claude Code `/hi` command specification.

1. Read `AGENTS.md` and `CLAUDE.md`.
2. Read the authoritative `.claude/commands/hi.md` command specification directly.
3. Execute it in this thread using the Codex adaptation table in `AGENTS.md`.
4. Treat text following `$hi` as command context or arguments.
5. Do not start a nested Codex process; complete the workflow in this thread.
