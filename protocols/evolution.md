## Evolution Root Principles

Read this before changing `protocols/`, `.claude/agents/`, `.claude/commands/`,
`harness/`, or `scripts/`. Every improvement passes these six. Backstop names
the mechanical guard; a principle without one is review-only and is checked at
`/system-review`.

| # | Principle | Backstop |
|---|---|---|
| 1 | Cost = bytes × load frequency. Know which load path a change rides (every turn, every invocation, nightly, on-demand) before writing prose there. | `prose-budget`, `hot-path-ceiling` lints |
| 2 | Cut by provenance. Rationale prose, dual-source duplication, and deterministic logic are safe cuts (rationale to the ledger, logic down to scripts). A behavior rule earned by a ledger glitch may be compressed, never deleted. | review-only; ledger under `$OV/research/` |
| 3 | Judgment in prompts, determinism in scripts, cross-cutting rules in protocols, one source of truth per fact. Derived surfaces are generated or validated, never hand-kept. | `render_runtime_edges --check`, drift lints, smoke needles |
| 4 | Subtract before adding. Before any new rule: is it already covered, can an existing rule generalize, what does it displace? | `prose-budget` ratchet; pruning trigger via `session_stats` |
| 5 | Every fix ships a mechanical guard and a ledger row (glitch / root cause / fix / guard / lesson). A guard is not a guard until it has failed on its target bug. | mutation-test pattern in `tests/test_lint_guards.py` |
| 6 | Evidence over intuition. Change because something failed or measured poorly, not because it could be "better". Measure before sweeping; a dropped low-yield sweep is recorded, not silently skipped. | review-only; eval snapshots under `$OV/_meta/evals/` |

Named failure shapes for review live in `antipatterns.md`. Evolver workflow
specifics (OODA loop, output format, working rules) live in
`.claude/agents/evolver.md`; this page binds every harness editor, human or
agent, not just the Evolver role. This file is lint-capped at 4096 bytes —
if a principle does not fit, one must leave.
