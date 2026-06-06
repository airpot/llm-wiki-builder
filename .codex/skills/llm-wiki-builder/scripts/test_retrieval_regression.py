#!/usr/bin/env python3
"""Regression checks for deterministic wiki retrieval."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import tempfile
from pathlib import Path

from init_wiki import init_wiki
from wiki_lib import build_memory_artifacts, retrieve, write_json


def write_page(root: Path) -> None:
    page = root / "wiki" / "concepts" / "transformer-memory.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        """---
title: Transformer Memory
slug: transformer-memory
created: 2026-06-06
updated: 2026-06-06
type: concept
summary: Transformer memory tracks how attention and context windows preserve useful information.
aliases: [attention memory, context memory]
tags: [transformer, memory]
sources: []
confidence: medium
contested: false
---

# Transformer Memory

Transformer memory is represented through attention over context and supporting retrieval structures.
""",
        encoding="utf-8",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="llm-wiki-retrieval-regression-") as tmp:
        root = Path(tmp)
        init_wiki(root)
        write_page(root)
        memory_index, link_graph = build_memory_artifacts(root)
        write_json(root / "memory-index.json", memory_index)
        write_json(root / "link-graph.json", link_graph)

        unrelated_hits = retrieve(root, "zzzz no-overlap-query", limit=5)
        if unrelated_hits:
            print("error: unrelated query returned hits")
            for hit in unrelated_hits:
                print(f"  {hit['path']} score={hit['score']} reasons={hit['reasons']}")
            return 1

        related_hits = retrieve(root, "transformer memory", limit=5)
        if not related_hits or related_hits[0]["path"] != "wiki/concepts/transformer-memory.md":
            print("error: related query did not return expected page")
            print(related_hits)
            return 1

    print("retrieval regression checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
