# Local Papers

Research papers stored as local PDFs in `$OV/papers/` (L3 externally certified knowledge: peer-reviewed or high-citation). Used for deep reading sessions when a paper is not available via URL or when the workflow needs the canonical PDF on disk.

## Directory Structure

```
$OV/papers/
├── <firstauthor>_<venue>_<year>_<name>.pdf        ← raw PDF (flat, agent-only)
├── <firstauthor>_<venue>_<year>_<name>-notes.md   ← optional notes/artifacts
└── ...
```

## How to Use

Papers are referenced by filename. The Reader agent reads PDFs directly via the Read tool. Use a stable, descriptive slug (kebab-case title or `<venue>-<id>`) as the basename.

### Naming convention
`<firstauthor>_<venue>_<year>_<name>.pdf` (flat store, agent-only). Example: `nvidia_techreport_2026_cosmos3.pdf`. `<firstauthor>` is the first-author surname or the corporate author (e.g. `nvidia`); `<venue>` is the publication venue, or `arxiv` / `preprint` / `techreport` when there is none; `<year>` is the 4-digit year; `<name>` is a short lower-case stem.

Legacy `<slugified-title>.pdf` and `<source>-<id>.pdf` files are tolerated on read. The cache-hit check in `read.md` (Local cache check) globs the store on author or distinctive keyword, so either grammar resolves; new files should use the structured grammar above so that glob stays reliable.

## No CLI

This is a local source — no CLI or API. The agent reads PDFs directly from the filesystem.
