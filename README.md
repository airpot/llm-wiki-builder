# LLM Wiki Builder

`llm-wiki-builder` is a Codex skill for building durable, file-first Markdown LLM wikis. It keeps `wiki/**/*.md` as canonical compiled memory, then generates retrieval indexes, agent-ready context packs, semantic HTML views, and read-only MCP-ready publish bundles for agent systems.

This repository is the installable skill package. It is not a generated wiki and does not contain user wiki data.

## What It Builds

An initialized wiki has this shape:

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
- `reports/context-packs/` stores bounded agent input packs.
- `reports/publish/html/` stores clean semantic HTML views.
- `reports/publish/mcp/` stores generated read-only MCP-ready bundles.

Generated context packs, HTML, and MCP bundles are rebuildable artifacts. They do not replace canonical Markdown wiki pages.

## Capabilities

- Purpose-led wiki initialization with Wiki Core Direction and extraction profiles.
- Source-preserving raw notes plus profile-aware compiled pages.
- Deterministic lexical retrieval with profile filtering, bilingual glossary expansion, seed/context separation, and query logging.
- Validation, structural health checks, stale generated artifact detection, raw source hash drift checks, and retrieval benchmarks.
- Agent-ready context pack generation in JSON and Markdown.
- Clean semantic HTML publishing with page metadata.
- Read-only MCP-ready bundle generation with linked and snapshot modes.

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
python3 .codex/skills/llm-wiki-builder/scripts/build_context_pack.py notes/wiki "your task" --json
```

Publish semantic HTML:

```bash
python3 .codex/skills/llm-wiki-builder/scripts/publish_semantic_html.py notes/wiki --clean
```

Publish an MCP-ready bundle:

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
- `README.md`

The first release is local, read-only, stdio-first at the contract level, and dependency-light. It does not add write tools, HTTP/auth, external model calls, vector stores, crawlers, secrets, or non-standard-library Python dependencies to the core workflow.

Publication modes:

- `linked`: resources point at the live local wiki root.
- `snapshot`: published files are copied under `reports/publish/mcp/snapshot/`; `raw/` is excluded by default.

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

