# Ingest Workflow

Use this workflow when the user provides pasted text, local source files, or already-fetched source text for durable wiki memory.

## Steps

1. Identify the target wiki root and read `SCHEMA.md`, available `profiles/*.json`, `index.md`, and recent `log.md` entries if they exist.
2. Classify the source as `article`, `paper`, `transcript`, or `snippet`; choose a stable raw note path under `raw/`.
3. Create a normalized raw source note with metadata and source body. Do not rewrite source claims or silently replace a prior raw note.
4. Select the active extraction profile before semantic compilation:
   - use the profile explicitly named by the user when it exists;
   - use the only profile when the wiki has exactly one;
   - keep legacy behavior when no profiles exist;
   - ask the user to choose when multiple profiles exist and the request does not identify one.
5. Decide whether to create a new compiled page or update an existing one by checking titles, slugs, aliases, tags, `index.md`, and profile compatibility.
6. Compile source material into one or more `wiki/**/*.md` pages with required frontmatter and active `profiles` metadata when a profile is selected.
7. Preserve source attribution near claims. If a new source contradicts existing content, preserve both claims and mark the page or section contested or low-confidence.
8. Rebuild `memory-index.json` and `link-graph.json`.
9. Update `index.md` if new pages were created.
10. Append `log.md` with raw note paths, compiled page paths, active profile, and any contested or low-confidence updates.
11. Run validation before handing off.

## Page Update Rules

- Prefer updating an existing page when aliases, titles, tags, or index entries identify the same topic.
- When an active profile is selected, update only pages whose `profiles` list contains that profile.
- Do not substantially update a page with a different non-empty `profiles` list just because title or slug matches.
- Do not substantially update an unprofiled page in a profile-enabled wiki unless the user explicitly approves migrating that page to the active profile.
- Prefer a new page when the source introduces a distinct topic or a comparison that would make an existing page too broad.
- Do not merge, split, delete, or substantially reorganize existing compiled pages unless the user explicitly asks for write-mode execution.
- Keep page summaries concise; retrieval depends on them.

## Source Attribution

Use stable references such as raw note path, source URL, local file path, title, or source id. Retrieval can find a page, but attribution tells the user where claims came from.
