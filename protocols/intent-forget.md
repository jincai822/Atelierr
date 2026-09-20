## Forget intent

Outcome: identify low-signal or stale material without deleting anything.

Resolve `scope_path` from the user; default to `<paths.wip>/`. Dispatch the
Forgetter agent with that bounded scope. It returns findings through the
`---forgetter-result---` / `---end-result---` envelope.

Persist the returned findings to
`<paths.agent_findings>/decay-<RUN_TS>-<scope-slug>.md`. Surface proposals to
the user. Forgetter never deletes or rewrites source notes.
