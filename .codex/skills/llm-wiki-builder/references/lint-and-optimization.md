# Lint And Optimization

The optimization loop improves wiki structure and retrieval quality without unsafe silent content rewrites.

## Validation Checks

Validate:

- required baseline files and directories;
- compiled page frontmatter fields and allowed values;
- JSON shape for `memory-index.json` and `link-graph.json`;
- JSONL shape for `query-log.jsonl` and `retrieval-evals.jsonl`;
- internal Markdown link targets;
- index coverage for compiled pages;
- memory index freshness;
- retrieval eval schema.

## Safe-Fix Mode

Safe-fix mode may repair only deterministic issues:

- missing generated directories or baseline empty files;
- stale memory index and link graph;
- missing index rows that can be derived from page frontmatter;
- uniquely repairable links;
- mechanical frontmatter defaults;
- log formatting drift.

Safe-fix mode must not rewrite raw source body text, merge pages, split pages, delete pages, or substantially reorganize page content.

## Suggestion-Only Optimization

Report, but do not apply, semantic changes such as:

- duplicate topics;
- overlong pages;
- weak summaries;
- missing aliases;
- sparse link graph;
- frequent query misses;
- low-confidence pages;
- unresolved contested pages.

Write optimization reports under `reports/optimization/` and append `log.md`.

## Retrieval Benchmarks

`retrieval-evals.jsonl` cases require `id`, `query`, and `expected_pages`. Optional fields: `forbidden_pages`, `tags`, `notes`.

When optimization changes retrieval-relevant files, rerun the benchmark or state why it could not run, then compare before/after metrics in the report.
