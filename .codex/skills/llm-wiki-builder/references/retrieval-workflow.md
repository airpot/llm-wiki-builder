# Retrieval Workflow

Use deterministic file-first retrieval before answering from wiki memory.

## Ranking Order

1. Load `memory-index.json` and `link-graph.json`. If either artifact is missing, invalid, or stale, retrieval rebuilds fresh artifacts in memory for that command; run `scripts/build_memory_index.py <wiki-root> --write` when you want to persist the refreshed files.
2. Score exact title, slug, alias, and tag matches.
3. Score lexical matches in summaries, headings, and page text, including deterministic Unicode/CJK token fallback without external segmentation dependencies.
4. When `--profile <profile_id>` is provided, search only pages declaring that profile. Exclude unrelated-profile and unprofiled pages unless `--include-unprofiled` is explicitly set.
5. Expand one hop through `link-graph.json` when linked pages add useful context; profile-filtered retrieval must not expand into unrelated-profile pages.
6. Apply light recency weighting without overriding relevance.
7. Surface `confidence=low` and `contested=true`.
8. Cite wiki page paths in the answer.

Do not treat a retrieval hit as proof that a claim is true. It only selects candidate memory pages.

## Miss Handling

If no adequate page is found:

- state that the wiki lacks sufficient memory for the query;
- suggest ingesting source material or creating a page;
- append a miss to `query-log.jsonl` when logging is enabled.

Query logging is enabled by default when `query-log.jsonl` exists unless the user or command explicitly disables it.

## Profile Filtering

Default retrieval with no profile remains broad and searches all compiled pages.

Profile-filtered retrieval:

- requires a known `profile_id`;
- includes pages whose `profiles` list contains that id;
- includes multi-profile pages when any listed profile matches;
- excludes unrelated-profile pages;
- excludes unprofiled pages by default;
- may include unprofiled pages with `--include-unprofiled`, ranked below true profile matches.

## Query Log Schema

Each JSONL entry should include:

```json
{
  "timestamp": "2026-06-06T00:00:00Z",
  "query": "example query",
  "selected_pages": ["wiki/concepts/example.md"],
  "miss": false,
  "retrieval_mode": "deterministic-file-first",
  "profile_id": "core"
}
```

Additional fields such as scores, limit, or notes are allowed.
