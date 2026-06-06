---
name: llm-wiki-builder
description: Build and maintain durable Markdown LLM wikis with source ingest, compiled pages, deterministic memory retrieval, linting, safety-gated self-optimization, and retrieval benchmarks.
---

# LLM Wiki Builder

## Overview

Use this skill to build and maintain durable, file-first Markdown LLM wikis. It supports source ingest, compiled wiki pages, deterministic memory retrieval, wiki linting, safety-gated self-optimization, and retrieval benchmarks.

An LLM wiki is a user-owned directory, not this repository. The default structure is documented in `references/wiki-protocol.md` and initialized by `scripts/init_wiki.py`.

## Use When

- The user asks to create, initialize, lint, query, optimize, or benchmark a Markdown LLM wiki.
- The user asks to ingest source material into durable wiki memory.
- The user asks what an existing wiki knows and expects page citations.
- The user asks to improve retrieval quality, query misses, aliases, links, summaries, contested pages, or low-confidence pages.

## Do Not Use When

- The request is generic writing, documentation, or app work with no durable wiki target.
- The user wants a vector database, embedding pipeline, RAG server, crawler, SaaS app, or browser extension.
- The user asks for another production skill's domain workflow unless they explicitly request a `llm-wiki-builder` adapter.

## Workflow

1. Classify the request: initialize, ingest, retrieve/query, lint, optimize, benchmark, or adapter planning.
2. For existing wikis, read `SCHEMA.md`, `index.md`, and recent `log.md` entries before writing.
3. Load the narrow reference needed for the workflow:
   - `references/wiki-protocol.md` for structure, frontmatter, indexes, and logs.
   - `references/ingest-workflow.md` for source intake and compiled page updates.
   - `references/retrieval-workflow.md` for deterministic memory retrieval and query logging.
   - `references/lint-and-optimization.md` for validation, safe fixes, reports, and benchmarks.
   - `references/conflict-handling.md` for contradictions, confidence, and contested claims.
4. Prefer scripts for deterministic operations:
   - Initialize with `scripts/init_wiki.py`.
   - Validate with `scripts/validate_wiki.py`.
   - Rebuild retrieval files with `scripts/build_memory_index.py`.
   - Retrieve candidate pages with `scripts/retrieve_wiki.py`.
   - Benchmark retrieval with `scripts/evaluate_retrieval.py`.
5. When compiling or editing pages, keep raw source notes under `raw/` source-preserving and write compiled pages under `wiki/`.
6. After retrieval-relevant edits, rebuild `memory-index.json` and `link-graph.json`, append `log.md`, and run retrieval evals when cases exist.
7. Report changed wiki files, validation results, retrieval metrics, and any low-confidence or contested areas.

## Resources

- `references/wiki-protocol.md`: runtime structure, frontmatter fields, page types, indexes, raw source policy, and logs.
- `references/ingest-workflow.md`: source classification, raw note creation, compiled page updates, and cascade updates.
- `references/retrieval-workflow.md`: deterministic ranking, one-hop expansion, citations, and query-log schema.
- `references/lint-and-optimization.md`: validation, safe-fix/write-mode boundaries, reports, and retrieval evals.
- `references/conflict-handling.md`: source attribution, contradictions, contested pages, and confidence rules.
- `references/external-patterns.md`: concise ecosystem patterns and isolation notes.
- `scripts/init_wiki.py`: create missing wiki structure and baseline files without overwriting user files.
- `scripts/validate_wiki.py`: validate wiki structure, frontmatter, links, JSON/JSONL files, and report health.
- `scripts/build_memory_index.py`: rebuild `memory-index.json` and `link-graph.json` from `wiki/`.
- `scripts/retrieve_wiki.py`: retrieve pages with deterministic lexical ranking and optional query logging.
- `scripts/evaluate_retrieval.py`: run `retrieval-evals.jsonl` cases and write retrieval reports.
- `assets/templates/`: baseline output templates used by scripts and agent workflows.

## Guardrails

- Keep this skill isolated. Do not depend on another production skill's private files, scripts, schemas, examples, data model, or release boundary.
- Do not silently rewrite source claims, replace raw source notes, or delete raw source body text.
- Do not treat retrieval hits as proof that a claim is true; retrieval only selects candidate memory pages.
- Do not smooth over `confidence=low` or `contested=true`; surface uncertainty in answers.
- Do not rewrite, merge, split, delete, or substantially reorganize compiled pages unless the user explicitly requests write-mode execution for an accepted plan.
- In safe-fix mode, apply only deterministic repairs whose target and replacement can be derived without semantic judgment.
- Do not introduce required external API keys, network calls, vector databases, embedding services, or non-standard-library Python dependencies in the core workflow.
- Preserve unrelated user changes.
