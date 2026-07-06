# Lint And Optimization

The optimization loop improves wiki structure and retrieval quality without unsafe silent content rewrites. In the current skill, validation, health checks, memory index rebuilds, retrieval, and retrieval evals are deterministic scripts; safe fixes and optimization planning are agent-mediated workflows unless a dedicated script is explicitly added.

## Validation Checks

Validate:

- required baseline files and directories;
- complete Wiki Core Direction in `SCHEMA.md`, warning by default and failing in strict mode;
- extraction profile JSON shape and duplicate profile ids;
- optional profile retrieval gates;
- optional `glossary.json` and `glossary.jsonl` shape and conflicts;
- profile references on compiled pages;
- compiled page frontmatter fields and allowed values;
- JSON shape for `memory-index.json` and `link-graph.json`;
- JSONL shape for `query-log.jsonl` and `retrieval-evals.jsonl`;
- internal Markdown link targets;
- index coverage for compiled pages;
- memory index and link graph freshness, including content drift after page edits;
- local source path existence and optional raw body hash provenance;
- retrieval eval schema, including optional `profile_id`, `expect_miss`, `require_seed_hit`, `allow_forbidden_context`, and `min_score`.

Run `scripts/health_check.py` for zero-LLM structural preflight. It reports empty/stub pages, broken Markdown links, broken wikilinks, orphan pages, index completeness, log coverage, tag taxonomy drift, page size warnings, unprofiled pages, profiles with no pages, profiles with no eval cases, missing profile-required sections, profile-specific query misses, glossary issues, and mixed-language eval coverage gaps without applying fixes.

Generated output directories such as `reports/context-packs/`, `reports/publish/html/`, and `reports/publish/mcp/` are safe to create mechanically when missing. They are rebuildable artifacts and should not be optimized semantically as if they were canonical wiki pages.

## MCP Publish Quality Gates

Run `scripts/publish_mcp_bundle.py` when publishing a wiki for agent systems. The generated `quality.json` should surface:

- validation status, errors, and warnings;
- health-check status, findings, and blocker counts;
- retrieval eval metrics and profile gate failures when eval cases exist;
- freshness status for `memory-index.json`, `link-graph.json`, and semantic HTML;
- raw-source exclusion and read-only/path-confined publication policy.

The first MCP publish target is contract-only and read-only. Do not add MCP write tools, remote HTTP/auth, raw-source publication, external models, embeddings, vector stores, crawlers, or non-standard-library runtime dependencies as part of safe fixes or optimization.

## Agent-Mediated Safe-Fix Mode

Safe-fix mode is not a standalone auto-fix CLI. When the user explicitly requests safe fixes, the agent may use deterministic script output and apply only repairs whose target and replacement can be derived without semantic judgment:

- missing generated directories or baseline empty files;
- stale memory index and link graph;
- missing index rows that can be derived from page frontmatter;
- uniquely repairable links;
- mechanical frontmatter defaults;
- log formatting drift.

Safe-fix mode must not rewrite raw source body text, merge pages, split pages, delete pages, or substantially reorganize page content. If a deterministic script is not available for a proposed repair, treat the change as an agent-mediated edit and report exactly what will change before writing.

## Suggestion-Only Optimization

Report, but do not apply, semantic changes such as:

- duplicate topics;
- overlong pages;
- weak summaries;
- missing aliases;
- missing bilingual aliases or glossary mappings;
- sparse link graph;
- frequent query misses;
- low-confidence pages;
- unresolved contested pages.
- profile coverage gaps;
- profile-specific query misses;
- profile-required section gaps.

Write optimization reports under `reports/optimization/` and append `log.md`. Applying semantic optimization requires explicit user approval or explicit write-mode execution for an accepted plan.

## Retrieval Benchmarks

Positive `retrieval-evals.jsonl` cases require `id`, `query`, and non-empty `expected_pages`. Expected-miss cases may use `expect_miss: true` and must omit `expected_pages` or set it to an empty list. Optional fields: `profile_id`, `forbidden_pages`, `tags`, `notes`, `min_score`, `require_seed_hit`, `allow_forbidden_context`.

`scripts/evaluate_retrieval.py` reports positive-case hit rate, expected-miss accuracy, `recall_at_k`, `precision_at_k`, `mrr_at_k`, `ndcg_at_k`, and profile retrieval gate failures. When a profile declares `retrieval.min_seed_score`, `retrieval.min_recall_at_k`, or `retrieval.min_mrr_at_k`, benchmark execution fails if the declared gate fails. When optimization changes retrieval-relevant files, rerun the benchmark or state why it could not run, then compare before/after metrics in the report.

Use `require_seed_hit` when an expected page must be a primary match rather than a one-hop context page. Use `allow_forbidden_context` only when a forbidden page is unacceptable as a seed hit but acceptable as adjacent context.
