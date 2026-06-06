# Conflict Handling

LLM wikis should preserve uncertainty instead of hiding it.

## Contradicting Sources

When a new source contradicts existing wiki content:

1. Do not silently overwrite the old claim.
2. Preserve competing claims with source attribution.
3. Mark the page or section `contested: true` when the conflict is material.
4. Lower `confidence` when the available sources do not support a stable conclusion.
5. Add a short conflict note in the compiled page and record the event in `log.md`.

## Confidence Values

- `high`: strong source support and no known conflict.
- `medium`: plausible source support, incomplete coverage, or ordinary uncertainty.
- `low`: weak support, outdated source, conflict, or unresolved ambiguity.
- `unknown`: page exists as a placeholder or query archive with insufficient evidence.

## Merge And Split Safety

Merges, splits, deletes, and substantial rewrites are semantic operations. Generate a proposed plan first, then apply only after explicit user write-mode approval.
