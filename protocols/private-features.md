## Private Features

Private features extend Atelier without putting personal workflows, names,
integration details, or policy into the public repository. The source location,
not a visibility flag, defines whether a feature is private.

## Source contract

Canonical private sources live at:

```text
<paths.private_features>/<feature-name>/
├── SKILL.md
├── references/       # optional, loaded on demand
└── scripts/          # optional deterministic helpers
```

Each immediate child is one portable skill. `SKILL.md` frontmatter contains
only `name` and `description`, and `name` matches the directory. Feature source
directories must not be symlinks. This keeps ownership and Git visibility
unambiguous.

`<paths.private_features>` resolves to an `_tools` surface. The semantic corpus
policy excludes `_tools` directories at any depth, so skill instructions and
operational state do not enter knowledge retrieval.

## Runtime activation

| Runtime | Default target |
|---|---|
| Claude Code | `~/.claude/skills/<feature-name>` |
| Codex | `~/.agents/skills/<feature-name>` |

The links point to the same canonical feature directory. Resolve
`<paths.private_features>` through the path registry, then create both links
with the native filesystem rather than a feature manager:

```bash
ln -s "<resolved-private-features-root>/<name>" "$HOME/.claude/skills/<name>"
ln -s "<resolved-private-features-root>/<name>" "$HOME/.agents/skills/<name>"
```

Inspect both target paths before linking and refuse to replace an existing
directory or unrelated symlink. In a personal harness where the canonical
Claude-to-Codex synchronizer is installed, the Claude source link is enough;
the synchronizer resolves it and creates the Codex link. Runtime-specific
invocation policy belongs at the runtime edge, not in shared `SKILL.md`
frontmatter.

## Public and private movement

Activation and publication are separate operations:

- Activating a private feature creates runtime links only. Removing those
  links deactivates it without deleting the source.
- Publishing requires a reviewed copy into the public skill source, public
  dependencies only, and the privacy and harness gates.
- Making a public feature private removes it from the public tip and installs a
  private source. Git history is rewritten only when historical availability is
  itself unacceptable.

Do not store credentials in feature packs. Refer to the runtime credential
provider or a private configuration file outside the skill source.
