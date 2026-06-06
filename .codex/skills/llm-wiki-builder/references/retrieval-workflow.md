# Retrieval Workflow

Use deterministic file-first retrieval before answering from wiki memory.

## Ranking Order

1. Load `memory-index.json`. If it is missing or stale, run `scripts/build_memory_index.py <wiki-root> --write`.
2. Score exact title, slug, alias, and tag matches.
3. Score lexical matches in summaries, headings, and page text.
4. Expand one hop through `link-graph.json` when linked pages add useful context.
5. Apply light recency weighting without overriding relevance.
6. Surface `confidence=low` and `contested=true`.
7. Cite wiki page paths in the answer.

Do not treat a retrieval hit as proof that a claim is true. It only selects candidate memory pages.

## Miss Handling

If no adequate page is found:

- state that the wiki lacks sufficient memory for the query;
- suggest ingesting source material or creating a page;
- append a miss to `query-log.jsonl` when logging is enabled.

Query logging is enabled by default when `query-log.jsonl` exists unless the user or command explicitly disables it.

## Query Log Schema

Each JSONL entry should include:

```json
{
  "timestamp": "2026-06-06T00:00:00Z",
  "query": "example query",
  "selected_pages": ["wiki/concepts/example.md"],
  "miss": false,
  "retrieval_mode": "deterministic-file-first"
}
```

Additional fields such as scores, limit, or notes are allowed.
