# LLM Wiki Builder

`llm-wiki-builder` is a Codex skill for building durable, file-first Markdown LLM wikis. It keeps `wiki/**/*.md` as canonical compiled memory, then generates retrieval indexes, query-localized context packs, semantic HTML, and executable read-only stdio MCP snapshots with wiki-specific thin companion Skills.

This repository is the installable skill package. It is not a generated wiki and does not contain user wiki data.

## What It Builds

An initialized wiki has this shape:

```text
<wiki-root>/
  SCHEMA.md
  delivery-contract.json
  index.md
  log.md
  memory-index.json
  link-graph.json
  query-log.jsonl
  retrieval-evals.jsonl
  glossary.json
  glossary.jsonl
  profiles/
  raw/
  wiki/
  reports/
    context-packs/
    publish/
      html/
      mcp/
```

The important boundary is:

- `raw/` preserves source notes and provenance.
- `wiki/**/*.md` is the canonical compiled knowledge layer.
- `memory-index.json` and `link-graph.json` are generated retrieval accelerators.
- `reports/context-packs/` stores agent input packs with aggregate per-page excerpt budgets and bounded section/chunk localization.
- `reports/publish/html/` stores collision-free clean semantic HTML views with safe local links, page metadata, and stable heading/section anchors.
- `reports/publish/mcp/` stores generated path-confined executable MCP bundles, portable snapshots, quality guidance, schemas, and a thin companion Skill.

Generated context packs, HTML, schemas, and MCP bundles are rebuildable artifacts. They do not replace canonical Markdown wiki pages.

## Capabilities

- Purpose-led wiki initialization with Wiki Core Direction, extraction profiles, and an explicit overridable Delivery Contract.
- Source-preserving raw notes plus profile-aware compiled pages.
- Deterministic lexical retrieval with profile filtering, bilingual glossary expansion, seed/context separation, and query logging.
- Validation, structural health checks, stale generated artifact detection, raw source hash drift checks, and retrieval benchmarks.
- Agent-ready context pack generation in JSON and Markdown with positive aggregate excerpt budgets, bounded chunk counts, stable chunk ids, offsets, hashes, sources, confidence, contested status, and retrieval reasons.
- Clean semantic HTML publishing with collision-free names, rewritten local links, safe URL schemes, page metadata, stable anchors, section metadata, and table head/body semantics.
- Executable read-only MCP generation with application-owned SDK metadata, linked/allowlisted snapshot modes, symlink confinement, transitive privacy sanitization, a thin companion Skill, aligned contracts, and readiness guidance.

## Install

Install this repository as a project-local Codex skill:

```bash
mkdir -p .codex/skills
tmp=$(mktemp -d)
git clone --depth 1 https://github.com/airpot/llm-wiki-builder.git "$tmp/llm-wiki-builder"
cp -R "$tmp/llm-wiki-builder/.codex/skills/llm-wiki-builder" .codex/skills/
```

Then reload Codex so the new skill is discovered.

The skill entrypoint is:

```text
.codex/skills/llm-wiki-builder/SKILL.md
```

## Common Commands

Initialize a draft wiki:

```bash
python3 .codex/skills/llm-wiki-builder/scripts/init_wiki.py notes/wiki --draft
```

Validate a wiki:

```bash
python3 .codex/skills/llm-wiki-builder/scripts/validate_wiki.py notes/wiki --json
```

Rebuild retrieval artifacts:

```bash
python3 .codex/skills/llm-wiki-builder/scripts/build_memory_index.py notes/wiki --write
```

Retrieve candidate pages:

```bash
python3 .codex/skills/llm-wiki-builder/scripts/retrieve_wiki.py notes/wiki "your query" --json
```

Build an agent-ready context pack:

```bash
python3 .codex/skills/llm-wiki-builder/scripts/build_context_pack.py notes/wiki "your task" --max-chars-per-page 1800 --max-chunks-per-page 8 --json
```

Publish semantic HTML:

```bash
python3 .codex/skills/llm-wiki-builder/scripts/publish_semantic_html.py notes/wiki --clean
```

Publish the default executable MCP plus companion Skill snapshot:

```bash
python3 .codex/skills/llm-wiki-builder/scripts/publish_mcp_bundle.py notes/wiki --mode snapshot --clean --strict
```

Run retrieval evals:

```bash
python3 .codex/skills/llm-wiki-builder/scripts/evaluate_retrieval.py notes/wiki --json
```

Run structural health checks:

```bash
python3 .codex/skills/llm-wiki-builder/scripts/health_check.py notes/wiki --json
```

## MCP Publish Target

`reports/publish/mcp/` is the primary agent-facing publication target. Generated bundles include:

- `manifest.json`
- `resources.json`
- `tools.json`
- `prompts.json`
- `quality.json`
- `server-config.json`
- `server.py`
- `requirements.txt`
- `skills/<wiki-name>-wiki/SKILL.md`
- `skills/<wiki-name>-wiki/agents/openai.yaml`
- `schemas/manifest.json`
- `schemas/*.schema.json`
- `README.md`

The default release is local, executable, read-only, stdio, and snapshot-based. The builder remains standard-library-only; the generated wiki application declares `mcp>=1.28,<2` in its own `requirements.txt`. It does not add write tools, HTTP/auth, external model calls, vector stores, crawlers, or secrets.

Publication modes:

- `linked`: resources point at the live local wiki root for development.
- `snapshot`: the final-publication default; an allowlisted portable subset is copied under `reports/publish/mcp/snapshot/`, with raw sources, original queries, logs, history, stale HTML, symlinks, and absolute host paths excluded transitively.

## Repository Layout

```text
.codex/skills/llm-wiki-builder/
  SKILL.md
  agents/
  assets/
  references/
  scripts/
```

## Development Validation

From the source workspace, the release gate is:

```bash
PYTHONDONTWRITEBYTECODE=1 make release-check SKILL=llm-wiki-builder
```

The release package should contain this README, `LICENSE`, `.gitignore`, and `.codex/skills/llm-wiki-builder/`.
