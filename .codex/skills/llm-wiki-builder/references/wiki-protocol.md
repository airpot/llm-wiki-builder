# Wiki Protocol

`llm-wiki-builder` targets user-owned Markdown wiki directories. The wiki is file-first: humans can inspect it directly, and agents use the generated JSON/JSONL files as retrieval accelerators.

## Baseline Layout

```text
<wiki-root>/
  SCHEMA.md
  index.md
  log.md
  memory-index.json
  link-graph.json
  query-log.jsonl
  retrieval-evals.jsonl
  raw/
    articles/
    papers/
    transcripts/
    snippets/
  wiki/
    concepts/
    entities/
    comparisons/
    queries/
  reports/
    validation/
    optimization/
    retrieval/
```

Create missing files and directories without overwriting existing user files. `raw/` stores source-preserving notes. `wiki/` stores agent-maintained compiled pages. `reports/` stores local validation, optimization, and retrieval evidence.

## Compiled Page Frontmatter

Every `wiki/**/*.md` page needs YAML-like frontmatter with these fields:

```yaml
---
title: Example Topic
slug: example-topic
created: 2026-06-06
updated: 2026-06-06
type: concept
summary: One sentence summary used by retrieval.
aliases: []
tags: []
sources: []
confidence: medium
contested: false
---
```

Allowed `type` values: `concept`, `entity`, `comparison`, `query`, `note`, `source-summary`.

Allowed `confidence` values: `high`, `medium`, `low`, `unknown`.

`contested` must be boolean. Use `contested: true` when sources conflict or when the page intentionally preserves competing claims.

## Raw Source Notes

Raw notes preserve source meaning. Mechanical metadata may be added, but source claims and source body text must not be silently rewritten or replaced.

Recommended raw note metadata:

- `source_id`
- `title`
- `source_type`
- `source_path`
- `source_hash`
- `ingested_at`
- `extraction_status`

If the user explicitly requests raw note deletion, archival, or replacement, record it in `log.md`.

## Indexes And Logs

`index.md` is the human-facing table of contents and should list compiled wiki pages. `memory-index.json` and `link-graph.json` are generated files. `log.md` is append-oriented and records initialization, ingest, safe fixes, optimization plans, accepted write-mode changes, and benchmark runs.

`query-log.jsonl` entries should include timestamp, query text, selected page identifiers, miss status, and retrieval mode. `retrieval-evals.jsonl` cases require `id`, `query`, and `expected_pages`; optional fields are `forbidden_pages`, `tags`, and `notes`.
