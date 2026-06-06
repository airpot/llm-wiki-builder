# Ingest Workflow

Use this workflow when the user provides pasted text, local source files, or already-fetched source text for durable wiki memory.

## Steps

1. Identify the target wiki root and read `SCHEMA.md`, `index.md`, and recent `log.md` entries if they exist.
2. Classify the source as `article`, `paper`, `transcript`, or `snippet`; choose a stable raw note path under `raw/`.
3. Create a normalized raw source note with metadata and source body. Do not rewrite source claims or silently replace a prior raw note.
4. Decide whether to create a new compiled page or update an existing one by checking titles, slugs, aliases, tags, and `index.md`.
5. Compile source material into one or more `wiki/**/*.md` pages with required frontmatter.
6. Preserve source attribution near claims. If a new source contradicts existing content, preserve both claims and mark the page or section contested or low-confidence.
7. Rebuild `memory-index.json` and `link-graph.json`.
8. Update `index.md` if new pages were created.
9. Append `log.md` with raw note paths, compiled page paths, and any contested or low-confidence updates.
10. Run validation before handing off.

## Page Update Rules

- Prefer updating an existing page when aliases, titles, tags, or index entries identify the same topic.
- Prefer a new page when the source introduces a distinct topic or a comparison that would make an existing page too broad.
- Do not merge, split, delete, or substantially reorganize existing compiled pages unless the user explicitly asks for write-mode execution.
- Keep page summaries concise; retrieval depends on them.

## Source Attribution

Use stable references such as raw note path, source URL, local file path, title, or source id. Retrieval can find a page, but attribution tells the user where claims came from.
