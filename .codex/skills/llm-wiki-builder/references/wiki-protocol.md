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
- `reports/context-packs/` stores generated agent-ready context packs for a query or task, including page-level retrieval metadata and localized section/chunk excerpts.
- `reports/publish/html/` stores generated semantic HTML views derived from `wiki/`, with stable heading/section anchors and embedded page metadata for model-friendly reading.
- `reports/publish/mcp/` stores the generated executable read-only MCP bundle, portable snapshot, quality guidance, schemas, and wiki-specific thin companion Skill.

Generated context packs, HTML, and MCP bundles are rebuildable artifacts. They must not be treated as authoritative wiki memory, and retrieval must continue to build from `wiki/**/*.md`, not from generated HTML or MCP artifacts.

Semantic HTML filenames combine a readable path slug with a deterministic path hash so nested, punctuation-normalized, and non-ASCII page paths cannot overwrite each other. Local Markdown page links are rewritten through this canonical-to-generated mapping. Active schemes such as `javascript:` and `data:` are not emitted as clickable links.

## MCP Publish Target

`reports/publish/mcp/` is the primary agent-facing publish target. It is generated from canonical Markdown pages, retrieval artifacts, context-pack contracts, and semantic HTML. The default is a local executable read-only stdio MCP snapshot plus a wiki-specific thin Skill. The builder stays standard-library-only; each generated wiki application owns its MCP SDK dependency.

Required generated files:

- `manifest.json` using `schema: llm-wiki-mcp-publish-v1`;
- `resources.json` declaring manifest, index, page, HTML, graph, memory-index, and quality resources;
- `tools.json` declaring read-only `wiki_search`, `wiki_read`, `wiki_context_pack`, and `wiki_quality_report` contracts;
- `prompts.json` declaring `answer_with_wiki`, `inspect_wiki_gaps`, and `prepare_context_pack`;
- `quality.json` summarizing validation, health, retrieval evals, freshness, blockers, warnings, `readiness_level`, `unsafe_to_answer`, `agent_use_recommendation`, `blocking_reasons`, `stale_artifacts`, and per-profile quality summaries;
- `server.py`, `requirements.txt`, and `server-config.json` declaring the executable stdio adapter and read-only safety policy;
- `skills/<wiki-name>-wiki/SKILL.md` and its `agents/openai.yaml` for an installable wiki-specific activation, tool policy, citations, uncertainty, quality gates, and miss handling package;
- `schemas/manifest.json` plus generated schemas for context packs, MCP tools, quality reports, semantic HTML manifests, and section/chunk payloads;
- `README.md` explaining the generated bundle.

Publication modes:

- `linked` points resources at the live local wiki root and is intended for development.
- `snapshot` is the final-publication default and copies only the allowlisted published subset under `reports/publish/mcp/snapshot/`: schema/Delivery Contract/index data, glossary/profile configuration, sanitized canonical wiki pages, fresh memory/link artifacts, and fresh semantic HTML. It excludes `raw/`, logs, query/eval history, prior context packs, stale HTML, original queries, and source-host absolute paths transitively.

MCP publish artifacts must be path-confined to the wiki root, must not require secrets, network access, external models, vector stores, or crawlers, and must surface low-confidence or contested pages through search/context/quality metadata. Only generated server output declares `mcp>=1.28,<2`; builder scripts do not import it.

Canonical page discovery rejects files that resolve outside `wiki/`. Snapshot tree copies reject symbolic links instead of following them, so contract validation cannot report `pass` after external content has been copied.

MCP `wiki_context_pack` contracts use the actual context-pack `options` envelope and include localized `chunks`; they must not declare stale fields such as `budget` unless the generator also emits a documented compatibility alias. MCP `wiki_read` contracts expose audit metadata such as content hash, canonical/generated status, confidence, contested status, sources, headings, and section index.

## Delivery Contract

Normal initialization writes `delivery-contract.json` using `llm-wiki-delivery-contract-v1`. Confirm or override `publish_target`, `consumer_hosts`, `mcp_runtime`, `transport`, `publication_mode`, privacy exclusions, `update_strategy`, and `skill_targets` during the initial purpose interview. Defaults are `mcp-skill`, executable, stdio, snapshot, no raw/query/absolute-path publication, and rebuild-on-change.

The generated companion Skill stays thin: it names public MCP tools/resources and behavior policy, but never embeds wiki bodies or imports private builder scripts.

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
