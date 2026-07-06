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
  glossary.json
  glossary.jsonl
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
    context-packs/
    publish/
      html/
      mcp/
```

Create missing files and directories without overwriting existing user files. `profiles/` stores extraction profile JSON. Optional `glossary.json` or `glossary.jsonl` stores explicit multilingual retrieval term mappings. `raw/` stores source-preserving notes. `wiki/` stores agent-maintained compiled pages. `reports/` stores local validation, optimization, and retrieval evidence.

## Output Layers

An LLM wiki has separate source, retrieval, agent-consumption, and publish/view layers:

- `raw/` is the source-preserving layer. It keeps source body text and provenance metadata.
- `wiki/**/*.md` is the canonical compiled knowledge layer. It is the durable editable memory for humans and agents.
- `memory-index.json` and `link-graph.json` are generated retrieval accelerators derived from `wiki/`.
- `reports/context-packs/` stores generated agent-ready context packs for a query or task.
- `reports/publish/html/` stores generated semantic HTML views derived from `wiki/`.
- `reports/publish/mcp/` stores the generated read-only MCP-ready bundle for agent systems.

Generated context packs, HTML, and MCP bundles are rebuildable artifacts. They must not be treated as authoritative wiki memory, and retrieval must continue to build from `wiki/**/*.md`, not from generated HTML or MCP artifacts.

## MCP Publish Target

`reports/publish/mcp/` is the primary agent-facing publish target. It is generated from canonical Markdown pages, retrieval artifacts, context-pack contracts, and semantic HTML. First-release bundles are local, read-only, and stdio-first at the contract level; executable MCP server adapters are optional follow-up work unless they can remain dependency-light.

Required generated files:

- `manifest.json` using `schema: llm-wiki-mcp-publish-v1`;
- `resources.json` declaring manifest, index, page, HTML, graph, memory-index, and quality resources;
- `tools.json` declaring read-only `wiki_search`, `wiki_read`, `wiki_context_pack`, and `wiki_quality_report` contracts;
- `prompts.json` declaring `answer_with_wiki`, `inspect_wiki_gaps`, and `prepare_context_pack`;
- `quality.json` summarizing validation, health, retrieval evals, freshness, blockers, and warnings;
- `server-config.json` declaring transport/adaptor status and read-only safety policy;
- `README.md` explaining the generated bundle.

Publication modes:

- `linked` points resources at the live local wiki root.
- `snapshot` copies only the published subset under `reports/publish/mcp/snapshot/`; it excludes `raw/` by default.

MCP publish artifacts must be path-confined to the wiki root, must not require secrets, network access, external models, vector stores, crawlers, or non-standard-library dependencies, and must surface low-confidence or contested pages through search/context/quality metadata.

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

Profiles may also include optional retrieval gates:

```json
{
  "retrieval": {
    "min_seed_score": 1,
    "min_recall_at_k": 0.8,
    "min_mrr_at_k": 0.7,
    "allow_glossary_expansion": true
  }
}
```

`allow_glossary_expansion: false` disables glossary-expanded matches for profile-filtered retrieval while leaving direct title, slug, exact page path, path stem, alias, tag, heading, summary, and body lexical matches available. `min_seed_score`, `min_recall_at_k`, and `min_mrr_at_k` are surfaced as retrieval benchmark gate failures.

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

`retrieval-evals.jsonl` positive cases require `id`, `query`, and `expected_pages`; optional fields are `profile_id`, `forbidden_pages`, `tags`, `notes`, `min_score`, `require_seed_hit`, and `allow_forbidden_context`. Expected-miss cases may set `expect_miss: true` and must omit or leave `expected_pages` empty. Retrieval reports include hit rate for positive cases, miss accuracy for expected-miss cases, ranking-aware metrics, and profile gate failures: `recall_at_k`, `precision_at_k`, `mrr_at_k`, and `ndcg_at_k`.

## Glossary

`glossary.json` may define:

```json
{
  "schema": "llm-wiki-glossary-v1",
  "terms": [
    {
      "canonical": "retrieval",
      "aliases": ["retrieval", "检索", "召回"],
      "notes": "Retrieval-stage terminology."
    }
  ]
}
```

`glossary.jsonl` may contain one term object per line. Glossary entries are retrieval aids only; they do not establish source truth. Validation reports malformed entries, duplicate canonical terms, conflicting alias mappings, placeholder values, and non-string aliases.
