# Read & Discuss

Procedure for Read intent. Owns Reader/Scholar selection, Readwise prefetch, source backup, and the three read modes (Read & Discuss, Focused Read, Multi-Lens Read).

## Menu

| Option | Label | Description |
|--------|-------|-------------|
| 1 | **Read & Discuss** | Quick read + interactive discussion (default) |
| 2 | **Focused Read** | Pick 1-2 specific lenses to focus on |
| 3 | **Multi-Lens Read** | Read with all 4 lenses in parallel — full analysis |

## Reader vs Scholar selection (applies to all three Read modes)

Before dispatching the reading agent, apply the auto-promotion check from `protocols/orchestrator.md` → "Reader → Scholar auto-promotion". If any condition fires (`word_count > 8000`, source path under `<paths.papers>/` or `<paths.preprints>/`, frontmatter `difficulty: hard`), dispatch **Scholar** instead of Reader. Same lens framework, same prompt — only the bound voices differ. All three Read modes below use this selection.

## Local cache check (before fetching; applies to all three Read modes when the source is a paper or external URL)

If the source is a paper or an external URL (arXiv, conference PDF, a paper named by title), check local material FIRST and only hit the web on a miss. The cached copy is often already on disk; a web round-trip before checking it is wasted latency.

1. Surface prior local material (related notes, not the PDF). Run `uv run scripts/semantic.py query "<title or distinctive keywords>" --top 5`. The index covers `*.md` only (`scripts/semantic.py` walks `rglob("*.md")`), so this finds reading reflections, wiki entries, and any `<slug>-notes.md` artifacts about the paper. It does NOT find the cached PDF itself; treat hits as related-reading context to fold into the session, not as the cache hit-test.

2. Test for an already-cached PDF. Glob the flat paper store for a file matching the author or title: `ls "$OV"/papers/ "$OV"/preprints/ 2>/dev/null | grep -i "<firstauthor-or-distinctive-keyword>"` (resolve `papers` / `preprints` via `harness/paths.toml`). If a match exists, pass that local path to the reading agent and skip the web fetch entirely.

3. Fetch from the web only if both the note query (step 1) and the PDF glob (step 2) miss. After a web fetch, cache the PDF into `<paths.papers>/` so the next read is a local hit (naming convention in `sources/local-papers.md`).

## Prefetch Step (Readwise podcasts, videos, articles; applies to all three Read modes)

If the source is a Readwise podcast, video, or article (user provides a Readwise URL, `document_id`, or names a podcast), **cache the transcript once before dispatching any reading agent (Reader or Scholar)**. Independent fetches across parallel reading-agent instances are the failure mode this step exists to avoid (same reasoning as the paper cache).

1. Resolve `document_id`. If the user gave a title, find it: `readwise reader-search-documents --query "<keywords>"` → pick the match.
2. Snapshot content: `readwise reader-get-document-details --document-id <id> | jq -r '.content' > <paths.cache>/rw-<id>.md`
3. Pass `cache_path: <paths.cache>/rw-<id>.md` to every reading-agent dispatch (Reader or Scholar). The convention is documented in `.claude/agents/reader.md` § "Readwise transcript cache"; Scholar follows the same convention.
4. For podcasts specifically: also pass the guest name (parsed from title) and host name (from the `author` field) in the dispatch prompt so the reading agent doesn't have to re-infer for citation.

## Backup to Readwise (final step in every Read mode)

After the reflection file is saved, fire one `readwise reader-create-document` call as a last-resort backup of the source. The reflection file in `<paths.reflections>/` remains the durable artifact; this is just so the source itself is preserved if its origin URL ever rots.

**Skip conditions (do NOT call the CLI):**
- Input was a Readwise URL or `document_id` (already in Readwise; the Prefetch Step handled it).
- Input was a local `[[Note Title]]` (no source URL exists).
- Input was a transcript paste with no accompanying URL (nothing to back up).
- `readwise` CLI is not installed in the environment (`command -v readwise` returns nothing). Backup is best-effort; absence of the CLI is not a session error.

**When it runs (orchestrator, not a separate agent):**

```bash
readwise reader-create-document \
  --url "<canonical-source-url>" \
  --tags "<comma-list>" \
  --category "<article|pdf|video|podcast>"
```

- `--url`: canonical source URL. For arXiv use the abs page (`/abs/<id>`), not the PDF URL.
- `--tags`: 3-5 tags derived from the paper/article topic. Orchestrator picks them; no user prompt.
- `--category`: default `article`; use `pdf` for arXiv/PDF papers, `video` or `podcast` for transcripts.

Print the resulting Readwise URL or `document_id` to the user as a one-liner confirmation. Do not pre-check for duplicates: if Readwise re-creates a doc, the second `document_id` is fine. Do not loop on errors; if the call fails (network, auth), report the error and continue, since the reflection file is already saved.

## Per-option flows

- **Read & Discuss:** Ask for the article/note. Run the Prefetch Step above if it's a Readwise source. Dispatch 1 Reader (Critical lens) + 1 Researcher (find related notes). Present the analysis, then enter interactive discussion mode. Before write-back, dispatch **Reviewer** + **Challenger** in parallel to verify accuracy, then create a standalone article note (see Article Note step below). After the article note is saved, run the Backup to Readwise step above. This is the lightweight default — most reading sessions start here.
- **Focused Read:** Ask the user which article/note and which lens(es): Critical, Structural, Practical, or Dialectical. Run the Prefetch Step above if it's a Readwise source. Dispatch 1-2 Reader instances with the chosen lenses. Reader automatically handles transcript format (video/podcast) with preprocessing before applying the lens. Before write-back, dispatch **Reviewer** + **Challenger** in parallel to verify accuracy, then create a standalone article note (see Article Note step below). After the article note is saved, run the Backup to Readwise step above. Use when the user knows what angle they want.
- **Multi-Lens Read:** Ask the user which article or note to read. Run the Prefetch Step above if it's a Readwise source. Then follow the Reading Hub flow below. Use for important articles worth deep multi-angle analysis.

## Reading Hub Flow (Multi-Lens Read)

1. **Parallel dispatch — Phase 1 (gather + read):**
   - 2-4x **Reader** instances, each with a different lens. Always include Critical + Structural. Add by content type:
     - Opinion/journalism/essays → + Dialectical (find the tensions)
     - How-to/research/strategy → + Practical (extract takeaways)
     - Philosophy/argument/debate → + Dialectical + Practical
     - Video/podcast transcripts → Critical + Practical (Reader auto-preprocesses transcript format)
   - **Researcher** — find user's existing notes related to the topic
   - **Scout** (1-2 instances) — gather external context on the topic
   - **Thinker** — select and apply a relevant framework

2. **Convergence — Phase 2 (synthesize):**
   - **Synthesizer** combines all Reader briefs + Researcher + Scout + Thinker into a unified reading report
   - Present the report in Chinese (reading-intensive)

3. **Discussion — Phase 3 (interact):**
   - Enter interactive discussion mode
   - User and orchestrator discuss the article, guided by the multi-lens analysis
   - Dispatch additional Reader instances with specific lenses if the user wants to go deeper on an aspect

4. **Quality gate — Phase 4 (review + challenge):**
   - Before saving, dispatch **Reviewer** + **Challenger** in parallel:
     - Reviewer checks: citation accuracy, grounding, honesty
     - Challenger checks: are we asking the right questions? What did we miss?
   - Fix any issues they surface before writing the reflection file

5. **Save — Phase 5 (local reflection file):**
   - Write the reflection file to `<paths.reflections>/YYYY-MM-DD-reading-<slug>.md`
   - Include full source text under `### Full Text` (see source-text persistence rule in CLAUDE.md)
   - No write-back to daily notes. The reflection file is the durable output.

6. **Backup to Readwise — Phase 6 (source preservation):**
   - Run the Backup to Readwise step above.
   - Skip if the input was already a Readwise source or a local `[[Note Title]]`.
