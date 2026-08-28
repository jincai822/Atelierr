---
description: Bot-only adapter for one archived private local-routine prompt.
---

## /run-routine

Bot-only adapter for local scheduled routines. Invocation shape:

```text
/run-routine <routine-name>
```

The orchestrator must execute this procedure sequentially and without asking
for interactive input.

## Preflight

1. Require exactly one argument matching
   `[A-Za-z0-9][A-Za-z0-9._-]*`. Call it `ROUTINE`.
2. Require a non-empty `ATELIER_ROUTINE_PROFILE`. The shell wrapper has already
   validated exactly one local watch-registry row, support compatibility,
   capability profile, dependencies, owner eligibility, and launchd state.
   Do not repeat that harness audit inside the model session.
3. Require a non-empty comma-separated `ATELIER_ROUTINE_PERMISSIONS`. It is the
   effective action allowlist resolved from the selected profile.
4. Read `$OV/_routine_prompts/<ROUTINE>.md` completely. This private archive is
   the authoritative routine procedure. Refuse if it is absent.
5. The shell wrapper runs `scripts/atelier/routine_prompt_guard.py` before starting the
   model. It requires a `LOCAL EXECUTION OVERRIDE` first line and an `ORIGINAL
   ROUTINE PROMPT` boundary marker, then scans for literal credentials. If a
   literal credential is ever found after startup, stop without executing the
   prompt and report the offending line number without printing the credential.

## Execute

Follow the archived prompt exactly once using its local-adapter preamble. The
local filesystem path is canonical, so write directly under `$OV`; do not call
Google Drive MCP. Treat any archived Google Drive read path rooted at `zk/` as
the equivalent path under `$OV/`; Gmail remains a connector operation rather
than a filesystem read. Apply the action-authorization contract in
`protocols/remote-routines.md` § Capability and permission boundary using
`ATELIER_ROUTINE_PERMISSIONS`.

Honor the archived prompt's single-pass, cost-ceiling, idempotency, output-path,
and graceful-degradation rules. Do not modify `routine_watch.toml`, the machine
owner record, or launchd state during the routine.

## Finish

Return only the structured result object requested by the shell wrapper:

```json
{
  "routine": "<routine-name>",
  "outcome": "delivered",
  "output_file": "<path under $OV>",
  "summary": "<compact result summary>",
  "skipped_inputs": []
}
```

Use `delivered` only after writing the canonical output. Use `noop` only for
an intentional documented no-op that still writes its audit artifact. Use
`failed` when the procedure stops without a valid artifact and set
`output_file` to `null`. The wrapper independently checks the reported file
against the routine's declared output directory, glob, size, and claim time
before it records completion.
