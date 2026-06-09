---
name: llm-wiki-builder
description: Build and maintain durable Markdown LLM wikis with source ingest, compiled pages, deterministic memory retrieval, validation, agent-mediated safe fixes, optimization reports, and retrieval benchmarks.
---

# LLM Wiki Builder

## Overview

Use this skill to build and maintain durable, file-first Markdown LLM wikis. It supports purpose-led initialization, extraction profiles, source ingest, compiled wiki pages, deterministic memory retrieval, wiki validation, agent-mediated safe fixes, optimization reports, and retrieval benchmarks.

An LLM wiki is a user-owned directory, not this repository. The default structure is documented in `references/wiki-protocol.md` and initialized by `scripts/init_wiki.py`.

## Use When

- The user asks to create, initialize, lint, query, optimize, or benchmark a Markdown LLM wiki.
- The user asks to ingest source material into durable wiki memory.
- The user needs the same source material landed differently for separate wiki purposes or audiences.
- The user asks what an existing wiki knows and expects page citations.
- The user asks to improve retrieval quality, query misses, aliases, links, summaries, contested pages, or low-confidence pages.

## Do Not Use When

- The request is generic writing, documentation, or app work with no durable wiki target.
- The user wants a vector database, embedding pipeline, RAG server, crawler, SaaS app, or browser extension.
- The user asks for another production skill's domain workflow unless they explicitly request a `llm-wiki-builder` adapter.

## Workflow

1. Classify the request: initialize, ingest, retrieve/query, lint, optimize, benchmark, or adapter planning.
2. For new normal initialization, interview for the wiki purpose first. Confirm the Wiki Core Direction and at least one extraction profile before running `scripts/init_wiki.py` without `--draft`.
3. For existing wikis, read `SCHEMA.md`, available `profiles/*.json`, `index.md`, and recent `log.md` entries before writing.
4. Load the narrow reference needed for the workflow:
   - `references/wiki-protocol.md` for structure, frontmatter, indexes, and logs.
   - `references/ingest-workflow.md` for source intake and compiled page updates.
   - `references/retrieval-workflow.md` for deterministic memory retrieval and query logging.
   - `references/lint-and-optimization.md` for validation, agent-mediated safe fixes, optimization reports, and benchmarks.
   - `references/conflict-handling.md` for contradictions, confidence, and contested claims.
5. Prefer scripts for deterministic operations:
   - Initialize with `scripts/init_wiki.py`.
   - Validate with `scripts/validate_wiki.py`.
   - Run zero-LLM structural health checks with `scripts/health_check.py`.
   - Rebuild retrieval files with `scripts/build_memory_index.py`.
   - Retrieve candidate pages with `scripts/retrieve_wiki.py`.
   - Benchmark retrieval with `scripts/evaluate_retrieval.py`.
6. When compiling or editing pages, keep raw source notes under `raw/` source-preserving and write profile-aware compiled pages under `wiki/`.
7. When multiple profiles exist, select an active profile before semantic ingest. Do not update an incompatible-profile page just because title, slug, alias, or tag matches.
8. After retrieval-relevant edits, rebuild `memory-index.json` and `link-graph.json`, append `log.md`, and run retrieval evals when cases exist. When mixed-language misses recur, prefer explicit page aliases or wiki-owned glossary entries over implicit translation.
9. Report changed wiki files, validation results, retrieval metrics, active profiles, and any low-confidence or contested areas.

## Resources

- `references/wiki-protocol.md`: runtime structure, Wiki Core Direction, extraction profiles, glossary files, frontmatter fields, page types, indexes, raw source policy, and logs.
- `references/ingest-workflow.md`: source classification, active profile selection, raw note creation, compiled page updates, and cascade updates.
- `references/retrieval-workflow.md`: deterministic ranking, Retrieval Contract, bilingual alias/glossary expansion, profile filtering, seed-vs-context expansion, citations, and query-log schema.
- `references/lint-and-optimization.md`: validation, glossary coverage, profile coverage, agent-mediated safe-fix/write-mode boundaries, reports, negative evals, and retrieval evals.
- `references/conflict-handling.md`: source attribution, contradictions, contested pages, and confidence rules.
- `references/external-patterns.md`: concise ecosystem patterns and isolation notes.
- `scripts/init_wiki.py`: create missing wiki structure, Wiki Core Direction, and profiles without overwriting user files; use `--draft` only for explicit underspecified initialization.
- `scripts/validate_wiki.py`: validate wiki structure, profile files, glossary files, frontmatter, links, JSON/JSONL files, generated artifact freshness, and source provenance.
- `scripts/health_check.py`: run zero-LLM structural health checks for stubs, links, orphans, index coverage, log coverage, tags, page size, and profile coverage.
- `scripts/build_memory_index.py`: rebuild `memory-index.json` and `link-graph.json` from `wiki/`.
- `scripts/retrieve_wiki.py`: retrieve pages with deterministic lexical ranking and optional query logging.
- `scripts/evaluate_retrieval.py`: run positive and expected-miss `retrieval-evals.jsonl` cases and write ranking-aware retrieval reports.
- `assets/templates/`: baseline output templates used by scripts and agent workflows.

## Guardrails

- Keep this skill isolated. Do not depend on another production skill's private files, scripts, schemas, examples, data model, or release boundary.
- Do not create a normal new wiki before confirming Wiki Core Direction and extraction profile data; use explicit draft mode only when the user accepts an underspecified wiki.
- Do not silently rewrite source claims, replace raw source notes, or delete raw source body text.
- Do not treat profiles as cosmetic tags. They control extraction dimensions, page matching, retrieval filtering, validation coverage, and optimization reports.
- Do not treat retrieval hits as proof that a claim is true; retrieval only selects candidate memory pages.
- Do not smooth over `confidence=low` or `contested=true`; surface uncertainty in answers.
- Do not rewrite, merge, split, delete, or substantially reorganize compiled pages unless the user explicitly requests write-mode execution for an accepted plan.
- For agent-mediated safe-fix requests, apply only deterministic repairs whose target and replacement can be derived without semantic judgment.
- Do not imply a dedicated auto-fix or semantic optimization CLI exists unless a script is explicitly provided; otherwise use validation, health, index, and eval scripts plus user-approved agent edits.
- Do not introduce required external API keys, network calls, vector databases, embedding services, or non-standard-library Python dependencies in the core workflow.
- Preserve unrelated user changes.
