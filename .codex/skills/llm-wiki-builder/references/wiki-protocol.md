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
  profiles/
    core.json
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
    health/
    optimization/
    retrieval/
```

Create missing files and directories without overwriting existing user files. `profiles/` stores extraction profile JSON. `raw/` stores source-preserving notes. `wiki/` stores agent-maintained compiled pages. `reports/` stores local validation, optimization, and retrieval evidence.

## Wiki Core Direction

New normal initialization must persist a `## Wiki Core Direction` section in `SCHEMA.md`. It records:

- purpose;
- primary users;
- core knowledge targets;
- out-of-scope material;
- landing granularity;
- evidence policy;
- conflict policy;
- success queries.

Draft initialization must mark the core direction incomplete. Default validation keeps legacy wikis compatible, but strict validation fails until the core direction is complete.

## Extraction Profiles

Profiles are standard JSON files under `profiles/*.json` using `schema: llm-wiki-extraction-profile-v1`. Required fields:

- `schema`
- `profile_id`
- `purpose`
- `target_audience`
- `extract_dimensions`
- `exclude_dimensions`
- `page_types`
- `granularity`
- `evidence_policy`
- `conflict_policy`
- `output_roots`

Optional fields include `name`, `required_sections_by_type`, and `eval_queries`. `profile_id` must be stable because pages, retrieval evals, and query logs refer to it.

A wiki is profile-enabled when it has at least one valid profile or a complete Wiki Core Direction. Legacy wikis have neither. Default validation treats legacy profile gaps as warnings at most; strict validation enforces profile completeness for profile-enabled wikis.

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

Profile-aware pages created or substantially updated under an active profile should also include:

```yaml
profiles: [core]
extraction_goal: source-to-core-wiki-knowledge
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
- `sha256`
- `ingested_at`
- `extraction_status`

When `sha256` or `source_hash` is present, it should be the SHA-256 hash of the source body after the closing frontmatter delimiter. Validation recomputes this body hash and reports drift when the raw source body changes.

If the user explicitly requests raw note deletion, archival, or replacement, record it in `log.md`.

## Indexes And Logs

`index.md` is the human-facing table of contents and should list compiled wiki pages. `memory-index.json` and `link-graph.json` are generated files. `log.md` is append-oriented and records initialization, ingest, safe fixes, optimization plans, accepted write-mode changes, and benchmark runs.

`query-log.jsonl` entries should include timestamp, query text, selected page identifiers, miss status, and retrieval mode. Profile-filtered retrieval also records `profile_id`.

`retrieval-evals.jsonl` cases require `id`, `query`, and `expected_pages`; optional fields are `profile_id`, `forbidden_pages`, `tags`, and `notes`. Retrieval reports include hit rate plus ranking-aware metrics: `recall_at_k`, `precision_at_k`, `mrr_at_k`, and `ndcg_at_k`.
