---
description: Universal entry point — intent router for reflection, planning, action, reading, learning, capture, and more.
---

Outcome: select one intent, load only its bounded context and procedure, and
execute it through the active runtime.
Done when: the route is visible, ambiguity is resolved, and the selected
procedure's completion criteria are met.
Evidence: the injected route packet or canonical registry row, bounded context
metadata when used, and the procedure's own output evidence.
Output: one routing announcement followed by the selected workflow.

## No-context invocation

When `/hi` or `$hi` has no following text, do not load the intent registry.
Read `protocols/hi-menu.md`, ask its two-stage menu, then load only the chosen
procedure. Its recommendation branch may dispatch Librarian.

## Contextual routing

Prefer the hook-injected line beginning `ATELIER_INTENT_ROUTE `. A valid normal
packet has `schema = 2`, `source = "harness/intents.toml"`, and registry-derived
`name`, `mode`, `procedure`, `context_budget_bytes`, `agents`, `profile_reads`,
`priority`, `matched_pattern`, `parallel`, `fallback`, and `ambiguous` fields.
Use it without reading the full registry.

Read `harness/intents.toml` only when the packet is absent, malformed,
oversized, or has `fallback = true`. A fallback packet is not a semantic
classification: compare the full request with the registry rows and override
to a clear match; otherwise execute `intents.general`, whose procedure hands
off to the active runtime's skill, app, agent, or normal tool routing. Never
start `intents.reflection` merely because deterministic matching missed. A
date-prefixed factual narrative without an analytical question may override to
`intents.capture`.

If `ambiguous = true`, clarify among `tied_candidates`. Also clarify when a
short generic substring conflicts with the message's main request, or when a
fallback message contains an action signal such as a URL, imperative, or
date-prefixed narrative. Offer the likely alternatives plus reflection. Never
silently open a file, call an external service, write, or start a multi-agent
chain on a low-confidence route.

The hook logs deterministic fallback and ambiguity misses. For an
LLM-identified low-confidence match, run `scripts/atelier/intent_coverage.py
intent-log` with the raw input, runtime, initial match fields, and final route.
Logging is best-effort and must not block dispatch.

## Load and dispatch

Announce `Routing as intents.<name> → <agents>`, adding `(parallel)` when
declared. After a semantic override, say `Deterministic route missed; routing
semantically as intents.<name> → <agents>`. If no registry row fits, say
`No Atelier intent matched; handing off semantically → <capability>` and
execute `intents.general`.

When `profile_reads` is non-empty, run:

```bash
uv run scripts/atelier/context_bundle.py \
  --route-json '<ATELIER_INTENT_ROUTE packet>' \
  --format json
```

On the full-registry fallback path, replace `--route-json ...` with
`--intent '<selected-name>'`. Never synthesize a route packet from prose.

The helper revalidates the registry row and applies its
`context_budget_bytes`. Reuse the projection; do not reload the same profile
or continuity sources. Skip it for empty `profile_reads` unless the procedure
requests a specific source.

Read only the packet or row's `procedure` file and execute it as the selected
workflow. When `parallel = true`, dispatch the declared initial agents in one
native batch. Procedure-level parallel steps follow the same rule. All writes
retain the approvals and daily-note boundaries from `CLAUDE.md`.
