---
description: Structured decision journal with framework cross-validation.
---
# Decision Journal

> Also reachable via `/hi <natural language>` (e.g., `/hi should I take the offer`,
> `/hi help me decide`, `/hi torn between`). See `harness/intents.toml`
> `[intents.decision]` for the full pattern list. Both paths execute this same procedure.

Structured decision-making session for important choices. Uses thinking frameworks to analyze a decision from multiple angles.

## Trigger

User says something like:
- "I need to decide..."
- "Should I..."
- "Help me think through..."
- "I'm torn between..."

## Prerequisites

1. Read `profile/identity.md` and `profile/directions.md` for context.
2. Read `frameworks/cross-validation.md` for framework selection.

## The Decision Process

### Step 1: Frame the Decision

Ask the user:
- "What's the decision you're facing?"
- "What are the options?" (push for at least 3 — binary choices often hide a better third option)
- "What's the timeline? When must you decide?"
- "What makes this hard? What are you afraid of?"

### Step 2: Classify the Decision (Cynefin)

Read `frameworks/cynefin.md`. Determine the domain:
- **Clear**: Best practice exists → just follow it
- **Complicated**: Analyzable → gather expert input
- **Complex**: Unknowable in advance → design experiments
- **Chaotic**: Urgent → act now, analyze later

This determines how much analysis is appropriate.

### Step 3: Search for Relevant History

Pull prior thinking from the local vault.
- `Bash: uv run scripts/semantic.py query "<decision topic>" --top 10` — **primary**: has the user thought about adjacent versions of this before? Reframe and retry if thin.
- `Grep(pattern: "<key terms>", path: "$OV/")` — exact-match related notes for structural follow-up. Try both languages.
- `Grep(pattern: "<goal keyword>", path: "<paths.gtd>/")` AND `Grep(pattern: "<goal keyword>", path: "<paths.wiki>/")` — two separate calls; `Grep`'s `path` takes a single root, not a space-separated list. Checks which active goals (gtd) and which certified directions (wiki) are affected by this decision.

### Step 4: Apply Two Frameworks (Cross-Validation)

Based on the decision type, select the right pairing from `frameworks/cross-validation.md`:

| Decision Type | Primary Framework | Cross-Validation |
|--------------|-------------------|------------------|
| Career/direction | Ikigai | Regret Minimization |
| Risk assessment | Pre-Mortem | Inversion |
| Resource allocation | Pareto Principle | Eisenhower Matrix |
| Stuck/blocked | Immunity to Change | Five Whys |
| Build/invest | First Principles | Wardley Mapping |
| Binary choice | Dialectical Thinking | Second-Order Thinking |

**Dual-leg dispatch (cross-provider).** `/decision` is a multi-leg call site (`protocols/orchestrator.md` § "Currently-enabled multi-leg call sites"). Fire both Thinker legs in parallel — one message with two tool calls.

**Before dispatch — shadow group setup (best-effort):** Run a single Bash call to create the witness file. Parse the UUID from the output line `export ATELIER_SHADOW_GROUP="<uuid>"` and **remember it** for the direct-API leg and for cleanup. Best-effort: if the call fails, proceed without correlation.

```bash
NATIVE_MODEL=$(python3 scripts/shadow.py native-model --agent thinker)
DIRECT_MODEL=$(python3 -c "import tomllib; print(tomllib.loads(open('harness/agents.toml','rb').read().decode()).get('agents',{}).get('thinker',{}).get('voices',{}).get('direct',''))")
EXPECTED='[{"model":"'"$NATIVE_MODEL"'","leg":"native","subagent_type":"thinker"},{"model":"'"$DIRECT_MODEL"'","leg":"direct"}]'
python3 scripts/shadow.py group-start --task decision --expected "$EXPECTED"
```

**Do NOT use `eval` + `trap EXIT` here.** Claude Code and Codex run each workflow shell call in an isolated subprocess; an EXIT trap would destroy the witness immediately when that call returns, before the native project-agent dispatch fires. The witness file must stay open on disk until explicit `group-close` after both legs complete.

**Native-leg logging is in-band.** After the selected runtime's project agent returns, log its response via `shadow.py log` with `--prompt-text` and `--response-text`. The runtime-aware `native-model` helper prevents Codex results from being labeled with a Claude model identity.

- Native project agent `thinker`, prompt: "Apply <primary framework> + <cross-validation framework> to this decision: <user's framing>. Read the framework files yourself from `frameworks/`. Return verdict + reasoning. End with a line consisting of `Verdict: ` followed by exactly one word: proceed, defer, or reject."
- Direct-api shell leg; it must **inline** the framework files in the prompt, because the direct leg has no filesystem access and would otherwise apply a generic model-memory version of each framework. Resolve framework display names to slugged filenames (lowercase, hyphen-separated): "First Principles" → `first-principles.md`, "Wardley Mapping" → `wardley-mapping.md`, etc. Confirm `ls frameworks/` matches before dispatch.
  ```bash
  PRIMARY=frameworks/<primary-slug>.md   # e.g., frameworks/first-principles.md
  CROSS=frameworks/<cross-slug>.md
  REPO=$(git rev-parse --show-toplevel)
  DIRECT_MODEL=$(python3 -c "import tomllib; print(tomllib.loads(open('$REPO/harness/agents.toml','rb').read().decode()).get('agents',{}).get('thinker',{}).get('voices',{}).get('direct',''))")
  [ -n "$DIRECT_MODEL" ] || { echo "ERROR: thinker.direct not found in agents.toml" >&2; exit 1; }
  [ -f "$REPO/$PRIMARY" ] && [ -f "$REPO/$CROSS" ] || { echo "ERROR: framework file missing (check slug mapping)" >&2; exit 1; }
  {
    printf 'Apply the two frameworks below to this decision: <user'\''s framing>.\nReturn verdict + reasoning. End with a line consisting of "Verdict: " followed by exactly one word: proceed, defer, or reject.\n\n--- PRIMARY FRAMEWORK (%s) ---\n' "$PRIMARY"
    cat "$REPO/$PRIMARY"
    printf '\n\n--- CROSS-VALIDATION FRAMEWORK (%s) ---\n' "$CROSS"
    cat "$REPO/$CROSS"
  } | uv run scripts/chat_completion.py --model "$DIRECT_MODEL" --max-tokens 0 --shadow-group "<SHADOW_UUID>" --task-type decision --prompt -
  ```

Replace `<SHADOW_UUID>` with the UUID captured from `group-start` output. If group-start failed or was skipped, omit `--shadow-group` and `--task-type`.

**After both legs return — log native leg and close the shadow group (best-effort):**

```bash
NATIVE_MODEL=$(python3 scripts/shadow.py native-model --agent thinker)
python3 scripts/shadow.py log \
  --group "<SHADOW_UUID>" --task decision --model "$NATIVE_MODEL" --leg native \
  --prompt-text "<agent prompt summary>" \
  --response-text "<full agent response text>"
python3 scripts/shadow.py group-close --group "<SHADOW_UUID>" --mark-closed
```

Replace `<agent prompt summary>` with a short summary of the dispatch prompt, and `<full agent response text>` with the project agent's actual response. If group-start was skipped, skip this step too.

Wait for both before synthesizing. Surface any disagreement on framework choice or verdict before presenting to the user. If the direct leg soft-skips (exit 2 — api_env unset), note `Cross-provider check downgraded: thinker ran native-only (<reason>)` per orchestrator's operational-visibility rule, and continue with the native leg.

### Step 5: Decision Matrix (if applicable)

For decisions with clear criteria:

| Criteria (weighted) | Option A | Option B | Option C |
|--------------------|----------|----------|----------|
| [Criterion 1] (weight) | Score | Score | Score |
| [Criterion 2] (weight) | Score | Score | Score |
| Weighted total | X | X | X |

### Step 6: The Hard Questions

After analysis, ask:
1. "If you woke up tomorrow and this was decided for you as [Option X], how would you feel?" (Gut check)
2. "What would you advise your best friend in this situation?" (Distance)
3. "What will you regret NOT doing in 10 years?" (Regret minimization)
4. "What are you most afraid of? Is that fear based on evidence?" (Fear audit)

### Step 7: Decision Record

Don't push for a decision. If the user is ready, capture it. If not, capture the analysis.

## Output

**File:** `<paths.reflections>/YYYY-MM-DD-decision-<slugified-topic>.md`

Note: Slugify the topic for the filename — lowercase, replace spaces with hyphens, remove special characters (e.g., "SF vs NYC job" → `sf-vs-nyc-job`). Keep the original topic text in the file content.

```markdown
# Decision Journal — YYYY-MM-DD
## Topic: [Decision description]

## Options Considered
1. [Option A]: [description]
2. [Option B]: [description]
3. [Option C]: [description]

## Domain Classification
[Cynefin domain] — [implication for approach]

## Framework Analysis
### [Framework 1 Name]
- Applied insight: [specific to this decision]

### [Framework 2 Name] (Cross-validation)
- Applied insight: [specific to this decision]
- Agreement/Tension with Framework 1: [what the tension reveals]

## Decision Matrix
[If applicable]

## Key Questions & Answers
- [Question]: [User's response or open]

## Linked Notes
- [[Note Title]] — [relevance]

## Decision
[If made]: [The decision + rationale]
[If not made]: [What needs to happen before deciding]

## Review Date
[When to revisit this decision — 30/60/90 days]

## Session Meta
- User engagement: high / medium / low
- Surprise factor: yes / no
```

## Session Log

After writing the decision file, emit a session log:
1. `Bash: uv run scripts/session_log.py --type decision --duration <minutes>`
2. `Edit` the created file to populate sections from session data (agents dispatched, searches, questions, frameworks, anomalies). The canonical fill-in guide lives in `protocols/session-log.md` § "Section Guidance". Leave empty sections with headers only. If the write fails, warn and continue.

## Wrap Up

The decision file in `<paths.reflections>/` is the durable session output. Daily notes are user-authored; the system reads them but does not modify them. Tell the user the decision journal has been saved and where to find it.
