# Retrieval Workflow

Use deterministic file-first retrieval before answering from wiki memory.

## Ranking Order

1. Load `memory-index.json` and `link-graph.json`. If either artifact is missing, invalid, or stale, retrieval rebuilds fresh artifacts in memory for that command; run `scripts/build_memory_index.py <wiki-root> --write` when you want to persist the refreshed files.
2. Tokenize the query locally, including deterministic Unicode/CJK fallback without external segmentation dependencies.
3. Optionally expand query terms from explicit `glossary.json` or `glossary.jsonl` declarations.
4. When `--profile <profile_id>` is provided, search only pages declaring that profile. Exclude unrelated-profile and unprofiled pages unless `--include-unprofiled` is explicitly set.
5. Score primary seed evidence: exact title, slug, page path, path stem, alias, tag, heading, summary, body lexical, or glossary-expanded matches.
6. Apply secondary boosts only after primary evidence exists: selected profile, light freshness, and explicit unprofiled legacy handling.
7. Expand one hop through `link-graph.json` only after at least one seed hit exists; profile-filtered retrieval must not expand into unrelated-profile pages.
8. Surface `confidence=low` and `contested=true`.
9. Cite wiki page paths in the answer.

## Retrieval Contract

A returned page is either a `seed` hit or a `context` expansion.

Seed hits require positive primary evidence from page title, slug, exact page path, path stem, aliases, tags, headings, summary, body text, or explicit glossary expansion. Recency, profile compatibility, index presence, and one-hop links cannot create a seed hit.

Context expansion is one-hop incoming or outgoing link context from seed hits. Context pages are useful background, but they must not be treated as the primary answer source unless the answer also explains why they were included.

Hit objects include `score`, `primary_score`, `match_type`, `seed`, `reasons`, and `reason_counts` so agents can audit why a page was returned.

Do not treat a retrieval hit as proof that a claim is true. It only selects candidate memory pages.

## Context Packs

For agent task execution, prefer a generated context pack over ad hoc full-page reads when the user asks for bounded task/query context. Use `scripts/build_context_pack.py` after deterministic retrieval. A context pack records:

- the query, retrieval mode, profile filters, limit, and excerpt budget;
- seed hits and one-hop context hits separately;
- page path, title, summary, confidence, contested status, profiles, sources, scores, match type, reasons, and reason counts;
- bounded excerpts from canonical Markdown page bodies.

Context packs are generated artifacts under `reports/context-packs/`. They are not canonical memory and may be deleted and rebuilt. If a context pack surfaces `confidence=low`, `confidence=unknown`, or `contested=true`, the agent must carry that uncertainty into the answer.

## MCP Agent Access

For agent systems, prefer the generated MCP bundle under `reports/publish/mcp/` as the stable access layer. MCP tools must use the same deterministic file-first retrieval contract:

- `wiki_search` returns seed and one-hop context hits with scores, match type, reasons, confidence, contested status, profiles, and citations.
- `wiki_read` may read published Markdown, semantic HTML, or metadata, but must stay path-confined to the wiki root or snapshot root.
- `wiki_context_pack` generates bounded context packs instead of exposing whole-wiki dumps.
- `wiki_quality_report` surfaces validation, health, retrieval eval, and freshness status before an agent relies on the wiki.

MCP access does not make retrieval hits true claims. Agents must still cite wiki page paths, preserve uncertainty, and report misses when deterministic retrieval lacks adequate memory.

## Bilingual And Mixed-Script Matching

Mixed Chinese-English retrieval is deterministic and file-first:

- page `aliases` and `tags` are the strongest way to declare cross-language terms;
- optional `glossary.json` and `glossary.jsonl` map stable terms across languages;
- glossary expansion is lower-weight than direct title, alias, tag, heading, summary, or body matches;
- the retriever does not perform automatic translation or infer cross-language equivalence from Unicode ranges alone;
- glossary and alias expansion must still obey profile filtering.

`glossary.json` uses:

```json
{
  "schema": "llm-wiki-glossary-v1",
  "terms": [
    {"canonical": "retrieval", "aliases": ["retrieval", "检索", "召回"]}
  ]
}
```

`glossary.jsonl` may contain the same term objects one per line. When both files exist, `glossary.json` loads first, then `glossary.jsonl`; validation reports duplicate canonical terms or conflicting alias mappings.

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
- may disable glossary expansion when the selected profile declares `retrieval.allow_glossary_expansion: false`.

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
New retrieval-contract fields may include `seed_pages`, `context_pages`, `primary_scores`, and `reason_counts`.
