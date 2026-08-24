# Atelier

> **A personal workshop, published.** A reflective-thinking system built for [Codex CLI](https://github.com/openai/codex), [Claude Code](https://docs.anthropic.com/en/docs/claude-code), and a local-first Zettelkasten. It covers daily reflection, decision-making, deep reading, goal tracking, and knowledge crystallization. It is not a product, and not aiming to be one. The patterns are reusable; the configuration is bespoke. Read the code, fork what's useful, build your own.

The system surrounds an **œuvre**, the accumulating body of notes, decisions, and reflections kept as local Markdown under `$OV/` and outside this public repository. Workflows send relevant context to whichever model runtimes the user configures. A 15-specialist agent team (le cercle) coordinates session work; a deterministic trust engine (`scripts/trust.py`) scores the wiki layer; the lint workflow keeps the corpus self-consistent.

Capture what you learn. Reflect on what you think. Research what you don't know. Read deeply. Make decisions. Track goals across life chapters. Crystallize knowledge you trust.

Runs natively on both Codex and Claude Code through one runtime-adapter contract. Codex is the shipped default; Claude remains a supported local choice. Each runtime keeps its own command, agent, and lifecycle surfaces while sharing the same workflow and role specifications.

## Who is this for?

Honest framing matters more here than feature lists. Three rough audiences:

1. **Pattern students.** You want to see how someone wired native Codex and Claude Code runtimes to a personal-knowledge-management substrate end-to-end: agent contracts in `harness/agents.toml`, command portability in `harness/commands.toml`, trust scoring in `scripts/trust.py`, the five-tier (L1–L5) model in `protocols/local-first-architecture.md`, and the wiki schema in `protocols/wiki-schema.md`. Take the patterns; leave the configuration. **This is the primary audience.**

2. **System forkers.** You want to run something like this for your own thinking. The repo is MIT-licensed, you can fork it. But: a fresh clone has no `$OV/` vault, no `profile/identity.md`, no Readwise inbox, no archetype mnemonics that mean anything to you. The Atelier vocabulary (le cercle, the Painter, le œuvre) is bespoke. Expect to rip and replace; don't expect to clone-and-run.

3. **Maintainer.** Daily use. Self-improving on a weekly cadence via Codex `$system-review` or Claude `/system-review`, plus `scripts/review.sh`.

If you want a turnkey "second brain," this isn't it — it's also not trying to be. The fastest path to disappointment with this kind of system is to inherit someone else's vocabulary, taxonomy, and tier model wholesale; the value lives in writing your own.

## What It Does

**Reflect** — Daily check-ins grounded in what you actually wrote. Surfaces forgotten connections, challenges assumptions, tracks goals across life chapters.

**Read** — Deep-reads articles, saved notes, and transcripts through multiple lenses (critical, structural, practical, dialectical). Multiple readers analyze in parallel; you discuss what they found.

**Plan** — Goal reviews, decision journals, and energy audits. Tracks what's progressing, what's neglected, what's emerging. Uses 22+ thinking frameworks with cross-validation.

**Act** — Compact redundant notes, deep-dive into a topic with 4 agents in parallel, triage notes for cleanup, or curate your Readwise inbox.

**Learn** — Get reading recommendations, or introspect to rebuild your self-model.

**Wiki:** Crystallize validated thinking into `$OV/wiki/` entries with structured claims, external anchors, and bi-temporal markers. `scripts/trust.py` runs Personalized PageRank with external anchors as trust seeds. Codex `$lint` or Claude `/lint` enforces corpus-level structure and harness health.

Session reflections write to `$OV/reflections/`. Daily notes are user-authored — the system reads them; the sole write path is the Scribe agent recording user-dictated content verbatim.

## Forking the patterns (the primary use case)

If you read one thing in this repo, read these in order:

1. **`protocols/local-first-architecture.md`** — the five-tier (L1–L5) model. This is the load-bearing idea: directory = certification level, no tags required.
2. **`protocols/wiki-schema.md`** — claim markers (`[C1]`, `@anchor`, `@cite`, `@pass`), bi-temporal `valid_at`/`invalid_at` fields, and how `scripts/trust.py` reads them.
3. **`harness/agents.toml`, `harness/commands.toml`, `harness/models.toml`, `harness/capabilities.toml`** — provider-neutral registries. The Claude Code and Codex runtimes are *adapters*, not first-class consumers. This is the part most worth lifting.
4. **`scripts/trust.py`** — Personalized PageRank with external anchors as seeds. Stdlib-only, deterministic. Adapt freely.
5. **`scripts/semantic.py`** — pluggable embedder + store backends (BGE-M3 + LanceDB by default). The CLI contract is encoder-agnostic; the embedder choice is yours.
6. **`scripts/lint.py` and `scripts/privacy_check.py`** — quality gates with structured JSON output. Lint enforces wiki schema integrity; privacy_check scans private titles, local exact terms, and both worktree and staged content, and fails loud on placebo-pass conditions.
7. **`.claude/agents/*.md` and `.codex/agents/*.toml`:** fifteen shared role specs and their native Codex adapters. The adapters and the `$command` skills are rendered from the registries by `scripts/render_runtime_edges.py` (`--check` keeps them byte-identical); edit the registries, not the generated files. Useful as templates for your own agent definitions.

What's deliberately *not* portable: `profile/` (symlinked config), `$OV/personal/`, `$OV/wiki/` content, the impressionist vocabulary register (le cercle, the Painter, le œuvre), the bilingual English/Chinese behavior, the Era / Direction taxonomy, and the `civ`, `dine`, and `prm` workflows which encode a bespoke life-area model. Strip those before adapting.

## Running it (if you want to)

This is the maintainer's daily-use configuration. Running it identically end-to-end is supported, but expect a real onboarding cliff: a fresh clone has no vault, no profile, no notes. Most session commands will ask for Codex `$introspect` or Claude `/introspect` first, or warn that `profile/identity.md` is missing. That's working as intended for the maintainer; it's a wall for everyone else.

### Prerequisites

- [Codex CLI](https://github.com/openai/codex) (shipped default) or [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- [uv](https://docs.astral.sh/uv/) — Python package manager (3.11+)
- A `$OV/` directory with at minimum: `daily-notes/`, `wiki/`, `reflections/`. Other tiers (`papers/`, `cache/`, etc.) are optional.

**Optional:**
- [Codex CLI](https://github.com/openai/codex) is also the external reviewer leg for `system-review` (`scripts/review.sh`), even when Claude is the selected interactive runtime; a direct-API leg runs in parallel via `scripts/chat_completion.py`.
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) — optional reviewer fallback (`npm i -g @google/gemini-cli`).

### Install

```bash
git clone https://github.com/mhxie/atelier.git ~/atelier
cd ~/atelier
uv sync
echo 'export OV="$HOME/path/to/your/vault"' >> ~/.zshrc
source ~/.zshrc
```

All personal content under `$OV/` is gitignored. Only system configuration (protocols, agents, commands, scripts) is committed.

### Permissions, plugins, and feature coverage

Atelier's canonical write path is local:

```text
Codex -> local files under $OV -> Google Drive or another filesystem sync client
```

A Google Drive connector does not grant Codex permission to write local files.
When `$OV/` is outside the repository workspace, add it as a writable root while
keeping Codex in `workspace-write` mode:

```bash
codex -C . \
  --add-dir "$OV" \
  --sandbox workspace-write \
  --ask-for-approval on-request \
  '$hi'
```

This makes local writes technically possible; it does not bypass Atelier's
domain rules. Ordinary writes under `$OV/` still require user approval, and
daily notes remain user-authored except for verbatim Scribe capture.

For a separate personal Codex home, the maintainer uses this optional alias:

```bash
alias mycodex='CODEX_HOME="$HOME/.codex-personal" codex --add-dir "$OV"'
```

| Capability or permission | Required? | What it enables |
|---|---|---|
| Read access to the repository and `$OV/` | Yes | Local notes, profiles, semantic search, dashboards, and command specifications |
| Write access to `$OV/` via `--add-dir "$OV"` | For write-capable workflows | Reflections, cache files, wiki promotion, approved captures, and local routine output |
| Local shell commands | Yes | `uv`, `rg`, `git`, `jq`, lint, trust scoring, and deterministic project scripts |
| Project trust and reviewed hooks | Recommended | Session cues, intent coverage, and cleanup through `.codex/hooks.json` |
| Live web search | Optional | External research for Scout, Reader, Scholar, Librarian, and Thinker; enable with `--search` |
| Outbound shell network | Optional | Readwise CLI and API-backed scripts; this is separate from live web search and may require approval |

The local-first Atelier has no required Codex plugin. Plugins add access to
cloud data that is not already represented by local files:

| Integration | Core requirement | Authorization | Supported Atelier use |
|---|---|---|---|
| Gmail plugin | Optional | Install and enable the plugin, then complete Google OAuth | Search or read mail for user-requested Codex context; scheduled routines need Gmail attached on their hosting surface |
| Google Drive plugin | Optional locally; a Drive connector is required on whichever runtime hosts a Drive-writing routine | Install and enable the plugin, then complete Google OAuth | Search or operate on cloud-only Drive files; remote persistence uses the hosting runtime's Drive connection |
| Readwise CLI | Used by reading and curation flows; no Codex plugin required | `readwise login` or token authentication | Search Reader, fetch saved documents and transcripts, curate the inbox, and snapshot external anchors |
| GitHub plugin | Optional | Connector authentication | Remote issues, pull requests, and repository context; local `git` works without it |
| Google Calendar plugin | Optional | Google OAuth | Calendar-aware workflows added by a fork; no current core command depends on it |

Plugin readiness has four separate gates: installed, enabled, connector OAuth
completed, and tools loaded in a new Codex session. Tool actions then remain
subject to connector permissions and Codex approvals. Claude Code and
Claude.ai routines manage their own MCP connections, so authorizing a service
there does not configure the Codex plugin. Conversely, a Codex connection does
not repair a Claude.ai routine with a missing MCP connection.

Unattended local routines use a stricter Codex-only envelope. Ordinary routine
profiles make `$OV` writable while keeping this repository read-only;
maintenance is the only profile allowed to write both. Each profile also binds
an exact bot command, records a fingerprint in its evidence, and runs with a
sanitized environment plus non-interactive approvals. Interactive Claude Code
support is unchanged and does not control the launchd runtime.

References: [Codex plugins](https://learn.chatgpt.com/docs/plugins.md),
[sandbox and approvals](https://learn.chatgpt.com/docs/agent-approvals-security.md),
and [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp).

### First run

Atelier ships with Codex as its selected runtime. The selector is optional; it
only launches each CLI's native command surface:

```bash
python3 scripts/atelier_runtime.py status
python3 scripts/atelier_runtime.py run hi
python3 scripts/atelier_runtime.py run --non-interactive lint
```

To make Claude Code the persistent interactive launcher default:

```bash
python3 scripts/atelier_runtime.py use claude
python3 scripts/atelier_runtime.py run hi
```

`ATELIER_RUNTIME=codex|claude` overrides one interactive launcher process.
Direct native invocation always remains available; unattended launchd routines
remain Codex-only.

Codex:

```bash
codex -C . --add-dir "$OV" '$hi'              # fresh Codex TUI with vault write access
codex --add-dir "$OV" exec -C . '$lint'       # one-shot, no TUI
codex --add-dir "$OV" resume --last '$promote' # continue most recent session
```

Claude Code:

```bash
claude                # open Claude Code in the project
/introspect           # build profile/ from $OV/daily-notes/ - required before most session commands
/hi                   # universal entry point - session menu (`/reflect` is an alias)
```

Inside an active Codex thread, use `$hi`, `$weekly`, `$review`, or another
explicit command skill. Each skill reads the matching `.claude/commands/*.md`
specification directly, so interactive use requires no Python command bridge.
Codex reads `AGENTS.md`, discovers skills under `.agents/skills/`, dispatches
roles through `.codex/agents/`, and runs session and intent hooks from
`.codex/hooks.json`. `protocols/runtime-adapters.md` defines the translation
boundary.

Reflection workflows default to fresh sessions because reusing a prior session
pollutes the new reflection. Invoke them as `/hi`, `/weekly`, and so on in
Claude Code, or `$hi`, `$weekly`, and so on in Codex. Continuation-friendly
workflows such as Claude `/promote` and Codex `$promote` are marked
`resume_friendly = true` in `harness/commands.toml`.

## Sessions

Type `/hi` in Claude Code or `$hi` in Codex to get a menu; the main flows:

| Mode | What happens |
|------|-------------|
| Daily Reflection | Reflects on today's notes, asks questions at increasing depth, surfaces a forgotten connection |
| Weekly Review | Energy + attention audit across the week |
| Explore | Finds hidden connections and open threads across your notes |
| Goal Review | Checks progress on goals — progressing, neglected, or shifted |
| Decision Journal | Structured decision-making with framework cross-validation |
| Energy Audit | Four-dimension assessment (physical, mental, emotional, social) |
| Read & Discuss | Multi-lens reading of an article or note, then interactive discussion |
| Deep Dive | Full briefing on a topic — your notes + web research + resources + framework |
| Compact Notes | Find and merge redundant notes |
| Curate Inbox | Goal-aware triage of your Readwise inbox — score, route, and tag |
| Note Triage | Scan for compaction candidates across your notes |
| Process Meeting | Turn a work meeting transcript into structured notes with action items |

You can also go direct in Codex: `$review`, `$weekly`, `$decision`, `$explore`, `$energy-audit`, `$curate`, `$introspect`, `$lint`, `$promote`, `$dine`, `$prm`, `$civ`, `$system-review`. Replace `$` with `/` for the matching Claude command.

**Knowledge layer commands:**

| Command | What it does |
|---|---|
| `$promote` / `/promote` | Create an L4 wiki entry from L2 source notes: Researcher finds claims + anchors, Curator drafts schema-compliant entry, orchestrator writes after approval. |
| `$lint` / `/lint` | Corpus-level structural check over `$OV/wiki/` (parse errors, duplicate titles, slug drift, orphan entries, graph topology). Also harness health: CLAUDE.md size and formatting, privacy gate, ingestion hygiene. |

## The Team

Fifteen specialist agents (le cercle) work together during sessions. The orchestrator dispatches automatically; you can also talk to any of them directly:

- *"find notes about X"* — sends Researcher (the Observer)
- *"read [[Article]] with critical lens"* — sends Reader
- *"challenge my assumption about X"* — sends Challenger (the Critic)
- *"compact my notes on Y"* — sends Curator (the Collector)
- *"recommend reading on Z"* — sends Librarian (the Cataloguer)
- *"what's happening in the world on X"* — sends Scout (the Flâneur)

Full cercle archetype map (Observer / Colorist / Arbiter / Critic / Structuralist / Collector / Flâneur / Reader / Scholar / Cataloguer / Stenographer / Master / Steward / Conservator / Typewriter) lives in `protocols/atelier.md`.

## How It Works

```
Capture sources                  Local data layer ($OV/)
(Readwise inbox,                 L4  $OV/wiki/        ─ locally certified
 voice notes,                        (trust-scored canon)
 markdown editor)                L3  $OV/papers/ + $OV/preprints/ ─ peer-reviewed
                                 L2  $OV/daily-notes/ + reflections/ +
                                     research/ + agent-findings/ +
                                     wip/ + …
                                 L1  $OV/cache/ + Readwise (cloud, via CLI)

                                         ^
                                         |
                                         v
                            AI runtime (Claude Code or Codex)
                                         |
                     +-----------+-------+-------+-----------+
                     v           v               v           v
                Le Cercle    Sessions     Frameworks    Trust engine
                (15 agents)  (/hi menu)   (22 + xval)   (trust.py,
                     |           |               |        lint.py)
                     v           v               v
                Protocols    $OV/reflections/   Cross-validation
                (protocols/) (session outputs)  & Pattern Library
```

**Five-tier knowledge model.** Everything under `$OV/` is classified by depth of crystallization — raw capture (L1), working notes (L2), externally-certified papers (L3), locally-certified wiki entries (L4); L5 (universally certified) is reserved. Directory = tier; no tags required. Agents read from disk via semantic search and grep.

**TrustRank over the wiki.** Wiki entries under `$OV/wiki/` follow a structured schema: `## Claims` with `[C1]`, `[C2]`... headings, each backed by fenced `anchors` blocks containing `@anchor` (external evidence), `@cite` (internal edge to another wiki entry), and `@pass` (reviewer verification) markers with bi-temporal `valid_at`/`invalid_at` fields. `scripts/trust.py` runs Personalized PageRank with external anchors as seeds; trust mass enters the graph only at external sources and propagates through internal cites. No external anchor, no trust. `scripts/lint.py` enforces structural integrity across the corpus.

**Session output.** The orchestrator dispatches agents, gathers findings, runs a quality gate, and writes session output to `$OV/reflections/`. Daily notes are user-authored — the system reads them; the sole write path is the Scribe agent recording user-dictated content verbatim. All personal data under `$OV/` is gitignored; only system configuration is committed.

**Harness engineering.** `CLAUDE.md` stays a bounded routing map because every unconditional line consumes recurring context. Mechanical work stays in scripts: the autoevo pending queue has a single deterministic writer (`scripts/autoevo_pending.py`), fission-aware tier readers go through `_paths.tier_files()`, and Codex edge files are generated, not hand-kept. `AGENTS.md` and `.agents/skills/` give Codex the root contract and native `$command` surface. `harness/models.toml`, `harness/capabilities.toml`, `harness/commands.toml`, `harness/agents.toml`, and `protocols/runtime-adapters.md` keep provider and runtime assumptions explicit. Critical rules live at the top; detailed specifications load on demand from protocols and agent definitions. The Master of the Atelier (Evolver) has a "subtract before adding" principle and a root-instruction budget gate. `/lint` Phase 0 checks harness health alongside the wiki structural pass.

Key design choices:

- **Local-first**: the knowledge layer lives on disk under `$OV/`, not in a remote app. No external services required.
- **Deterministic trust scoring**: TrustRank is a stdlib-only Python pass, not an LLM heuristic. The same input always produces the same score.
- **Era-aware**: tracks life chapters with user-configured themes and directions.
- **Bilingual**: handles English and Chinese notes; matches your language.
- **Self-improving**: the Master of the Atelier evolves the system, reviewed by external AI models (Codex plus a direct-API leg by default; Gemini as an optional fallback) via `scripts/review.sh`.
- **Public-repo privacy gate**: personal configuration stays outside tracked files under `$OV/` and gitignored `profile/`. `scripts/privacy_check.py` gates public-bound worktree and index content against private titles and local exact terms; the Steward (privacy-reviewer agent) catches semantic leaks. This protects new commits, not copies already present in Git history, remote caches, or forks.

## Vocabulary

The system has a narrative register from the impressionist atelier — *le cercle* (the agents), *the Painter* (you), *the œuvre* (your accumulating body of work), *impression* / *étude* / *tableau* / *série* / *sitting* / *sketch* / *commission*. The register lives in conversation and identity. **Workflow names are stable across runtimes**: Claude Code exposes `/hi`, `/promote`, `/lint`, and so on; Codex exposes `$hi`, `$promote`, `$lint`. Agent dispatch keys stay `researcher`, `synthesizer`, …; file paths under `$OV/` stay as documented above. Full glossary: `CLAUDE.md` § Vocabulary and `protocols/atelier.md`.

## License

MIT — for the code. The taste, the vocabulary, and the daily-use configuration are not licensed and not portable. Fork the patterns; build your own atelier.
