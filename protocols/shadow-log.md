# Shadow-Log System

Cross-provider correlation, cost tracking, and verdict-agreement reporting for multi-leg LLM dispatches. Companion to `protocols/backend-taxonomy.md` § Shadow logs.

## Scope

This system instruments the multi-leg verification workloads the atelier already runs today:

- `/system-review` Step 1c (privacy 2-leg: native Anthropic + direct DeepSeek)
- `scripts/review.sh` (external-reviewer 2-leg: direct DeepSeek + codex)
- `/decision` (Thinker 2-leg)
- Quantitative-claim fact-check gate (when it dual-fires)

**Out of scope (M2 workstream):** routing decisions for single-leg generative workloads (Researcher, Synthesizer, Reader, Scout, Curator). These are 80-90% of LLM cost; their quality cannot be machine-judged on the unstructured prose they emit. The procedure for answering "should I move Researcher from Opus to DeepSeek?" lives in § M2 below.

## Mechanism

| Component | Where | What it does |
|---|---|---|
| Cost catalog | `harness/model_costs.toml` (committed) + `profile/model_costs.toml` (gitignored override) | Per-model USD prices with `last_verified` date. Used by report at compute time; `scripts/shadow.py report` fails closed when any aggregated model is >90d stale, unless `--accept-stale-costs`. |
| Log schema | `scripts/chat_completion.py` (auto-logs direct-API calls) | Adds `shadow_group_id`, `task_type`, `task_dispatch_kind` fields. Reads env `ATELIER_SHADOW_GROUP` / `ATELIER_TASK_TYPE`; explicit `--shadow-group` / `--task-type` flags override. Writes to `~/.cache/atelier/llm_calls/<date>.jsonl` (full) + `$OV/_meta/shadow_logs/<date>.jsonl` (skeleton). |
| Group manager | `scripts/shadow.py group-start` | Issues a UUID, writes witness file at `~/.cache/atelier/shadow_groups/<uuid>.json` declaring expected dispatches `[{model, leg}]`. Prints shell-eval-able env exports. |
| Native-leg shim | `scripts/shadow.py log` | Orchestrator calls after each Claude Code `Agent` dispatch at a multi-leg site. Writes synthetic JSONL entry with `usage_estimate.method = "char_approx"` (Agent tool doesn't surface tokens). |
| Verdict-token config | `harness/shadow_tasks.toml` | Per-task regex (word-boundary, case-aware, last-match-wins) for extracting structured verdicts from leg responses. |
| Report | `scripts/shadow.py report` | Aggregates logs, dedups, groups by UUID, extracts verdicts, computes cost retroactively from current catalog, emits per-task-type-per-leg-pair agreement + cost ratio + latency. Output prefixed with permanent SCOPE banner naming the 10-20% coverage caveat. |
| Lint guard | `scripts/harness_lint.py check_shadow_group_start` | Greps known multi-leg call sites for `shadow.py group-start` invocation; fails ERROR if missing. Catches the outer-discipline regression that would silently empty the report. |

## Per-call-site recipe

At every multi-leg call site, do this at flow entry:

```bash
eval "$(python3 scripts/shadow.py group-start \
  --task system-review \
  --expected '[{"model":"opus","leg":"native"},{"model":"deepseek_pro_max","leg":"direct"}]')"

# Bash legs auto-inherit env (ATELIER_SHADOW_GROUP / ATELIER_TASK_TYPE):
uv run scripts/chat_completion.py --model deepseek_pro_max --prompt-file <path> ...

# For Claude Code Agent dispatches: env does NOT propagate through the Agent
# tool boundary. Instead, after the Agent call returns, write a synthetic
# native-leg entry explicitly using the UUID from group-start:
python3 scripts/shadow.py log \
  --group "$ATELIER_SHADOW_GROUP" \
  --task system-review \
  --model opus \
  --leg native \
  --prompt-file <agent-prompt-text> \
  --response-file <agent-output>

unset ATELIER_SHADOW_GROUP ATELIER_TASK_TYPE
```

The lint check fires ERROR if a known site is missing the `group-start` invocation. Per-leg correctness (did each declared dispatch actually log?) is detection-only via the witness file; the report surfaces missing legs in WARNINGS.

## Report output

```
SCOPE: shadow logs cover multi-leg verification workloads (~10-20% of LLM spend).
       ...

task=system-review  groups=23 (since 2026-05-01)
  opus[native] vs deepseek_pro_max[direct]
    verdict agreement: 21/23 = 91.3%
    avg cost: left $0.0823, right $0.0015
    avg latency: left 28.1s, right 14.2s
  ...

WARNINGS:
- opus cost computed via char_approx (±25% true cost); ...
- 3 groups missing expected legs (witness expected 2, got 1): ...
- 5 logged groups have no witness file; treated as single-leg ...
```

When verdict agreement is high (≥90%) AND cost ratio is meaningful (e.g., 50×), the user has evidence to swap the expensive leg at the call site.

## Privacy

`$OV/_meta/shadow_logs/` contains correlation skeletons only: model, leg, usage, latency, verdict, response preview (first 200 chars + SHA-256). Full prompts/responses stay machine-local at `~/.cache/atelier/llm_calls/`. The skeleton still carries some signal (task type, verdict tokens, response preview); users who push `$OV` to a private GitHub remote SHOULD add `_meta/shadow_logs/` to `$OV/.gitignore`. The atelier cannot enforce vault gitignore; this is a documented recommendation.

## M2 — manual A/B for single-leg generative routing

R1 instrumentation does NOT cover single-leg workloads (Researcher, Synthesizer, etc.) because: (a) Anthropic native leg has no token usage exposure to parents, (b) the response is unstructured prose with no verdict token, (c) machine-judging quality requires either an LLM judge (defeats cost minimization) or human eyeball.

The 30-minute manual procedure for answering "should I move Researcher from Opus to DeepSeek?":

1. Pick 3-5 representative recent Researcher prompts from `~/.cache/atelier/llm_calls/`.
2. For each, run via direct API on both providers (`scripts/chat_completion.py --model opus`, `--model deepseek_pro_max`) using the same system prompt and user prompt.
3. Open both responses side-by-side in a markdown table or split view.
4. Score each leg on 3 axes (1-5 each):
   - **Faithfulness**: does the response cite the right notes, avoid hallucinated claims?
   - **Depth**: does it reach the depth a serious user query deserves?
   - **Usability**: is it directly useful for the user's next action?
5. Aggregate: if cheap-leg averages within 0.5 of expensive-leg on all 3 axes across the 5 prompts, the swap is justified. Otherwise keep the expensive leg or run more samples.

Cost: ~$0.10-$0.50 total in API calls + 30 minutes of human judgment. No infrastructure. Answers the routing question for one specific role; repeat per role.

The R1 shadow-log infrastructure scaffolds M2 by providing the prompt corpus (`~/.cache/atelier/llm_calls/`) and the cost catalog. M2 itself is a procedure, not a tool.

## Cross-references

- `protocols/backend-taxonomy.md` — backend role + SOT + failure mode + identifier-leakage contract
- `protocols/orchestrator.md` § Voice Dispatch — multi-leg call-site enumeration
- `scripts/chat_completion.py` docstring — log event schema
- `scripts/shadow.py --help` — subcommand reference
- `harness/model_costs.toml` — cost catalog (refresh quarterly)
- `harness/shadow_tasks.toml` — verdict-token extraction rules
