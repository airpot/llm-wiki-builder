#!/usr/bin/env python3
"""End-to-end regression checks for the llm-wiki-builder lifecycle."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

from health_check import check_health
from init_wiki import init_wiki
from validate_wiki import validate_wiki
from wiki_lib import build_memory_artifacts, retrieve, source_body_hash, write_json


SCRIPT_DIR = Path(__file__).resolve().parent


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def write_raw_source(root: Path) -> None:
    body = """# Transformer Memory Source

Transformer memory work connects attention, retrieval, and context management.
It also motivates memory index maintenance for agent-owned Markdown wikis.
"""
    source = root / "raw" / "articles" / "transformer-memory-source.md"
    source.write_text(
        f"""---
source_id: transformer-memory-source
title: Transformer Memory Source
source_type: article
source_path:
source_hash: {source_body_hash(body)}
sha256: {source_body_hash(body)}
ingested_at: 2026-06-06T00:00:00Z
extraction_status: manual
---
{body}""",
        encoding="utf-8",
    )


def write_page(root: Path, rel: str, title: str, slug: str, summary: str, links: str) -> None:
    page = root / rel
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        f"""---
title: {title}
slug: {slug}
created: 2026-06-06
updated: 2026-06-06
type: concept
summary: {summary}
aliases: []
tags: [memory]
sources: [raw/articles/transformer-memory-source.md]
confidence: medium
contested: false
---

# {title}

{summary}

## Connections

{links}

## Notes

The compiled page preserves source-attributed claims while making retrieval faster.
""",
        encoding="utf-8",
    )


def prepare_wiki(root: Path) -> None:
    init_wiki(root)
    write_raw_source(root)
    write_page(
        root,
        "wiki/concepts/transformer-memory.md",
        "Transformer Memory",
        "transformer-memory",
        "Transformer memory tracks attention, retrieval, and context management.",
        "- [[Memory Index]] supports durable retrieval.",
    )
    write_page(
        root,
        "wiki/concepts/memory-index.md",
        "Memory Index",
        "memory-index",
        "A memory index stores compiled wiki metadata for deterministic retrieval.",
        "- [[Transformer Memory]] gives the index useful retrieval context.",
    )
    (root / "index.md").write_text(
        """# Wiki Index

## Pages

- wiki/concepts/transformer-memory.md - Transformer memory.
- wiki/concepts/memory-index.md - Memory index.
""",
        encoding="utf-8",
    )
    (root / "log.md").write_text(
        """# Wiki Log

- 2026-06-06T00:00:00Z created wiki/concepts/transformer-memory.md and wiki/concepts/memory-index.md.
""",
        encoding="utf-8",
    )
    memory_index, link_graph = build_memory_artifacts(root)
    write_json(root / "memory-index.json", memory_index)
    write_json(root / "link-graph.json", link_graph)
    (root / "retrieval-evals.jsonl").write_text(
        json.dumps(
            {
                "id": "transformer-memory",
                "query": "transformer memory retrieval",
                "expected_pages": ["wiki/concepts/transformer-memory.md"],
                "forbidden_pages": ["wiki/concepts/not-present.md"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def assert_no_pycache(root: Path) -> None:
    findings = list(SCRIPT_DIR.parent.rglob("__pycache__")) + list(root.rglob("__pycache__"))
    if findings:
        raise AssertionError("unexpected __pycache__: " + ", ".join(path.as_posix() for path in findings))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="llm-wiki-lifecycle-") as tmp:
        root = Path(tmp)
        prepare_wiki(root)

        validation = validate_wiki(root)
        if validation["errors"] or validation["warnings"]:
            print(json.dumps(validation, indent=2, ensure_ascii=False))
            return 1

        hits = retrieve(root, "transformer memory retrieval", limit=5)
        if not hits or hits[0]["path"] != "wiki/concepts/transformer-memory.md":
            print("error: retrieval did not rank expected page first")
            print(hits)
            return 1
        if retrieve(root, "zzzz unrelated no overlap", limit=5):
            print("error: unrelated retrieval returned hits")
            return 1

        eval_result = run_command([sys.executable, str(SCRIPT_DIR / "evaluate_retrieval.py"), str(root), "--json"])
        if eval_result.returncode != 0:
            print(eval_result.stdout)
            print(eval_result.stderr)
            return eval_result.returncode
        eval_json = json.loads(eval_result.stdout)
        metrics = eval_json.get("metrics", {})
        if metrics.get("recall_at_k", 0) < 1.0 or metrics.get("mrr_at_k", 0) < 1.0:
            print("error: retrieval metrics did not meet lifecycle expectations")
            print(eval_result.stdout)
            return 1

        health = check_health(root)
        if health["status"] != "pass":
            print(json.dumps(health, indent=2, ensure_ascii=False))
            return 1

        stale_page = root / "wiki" / "concepts" / "transformer-memory.md"
        stale_page.write_text(stale_page.read_text(encoding="utf-8") + "\nAdditional retrieval-relevant text.\n", encoding="utf-8")
        stale_validation = validate_wiki(root)
        if not any("memory-index.json content is stale" in warning for warning in stale_validation["warnings"]):
            print("error: stale memory index warning was not detected")
            print(json.dumps(stale_validation, indent=2, ensure_ascii=False))
            return 1
        stale_strict = run_command([sys.executable, str(SCRIPT_DIR / "validate_wiki.py"), str(root), "--strict"])
        if stale_strict.returncode == 0:
            print("error: strict validation did not fail for stale memory artifacts")
            print(stale_strict.stdout)
            return 1

        prepare_wiki(root)
        raw = root / "raw" / "articles" / "transformer-memory-source.md"
        raw.write_text(raw.read_text(encoding="utf-8") + "\nHash drift.\n", encoding="utf-8")
        drift_validation = validate_wiki(root)
        if not any("source hash mismatch" in warning for warning in drift_validation["warnings"]):
            print("error: raw source hash mismatch was not detected")
            print(json.dumps(drift_validation, indent=2, ensure_ascii=False))
            return 1
        drift_strict = run_command([sys.executable, str(SCRIPT_DIR / "validate_wiki.py"), str(root), "--strict"])
        if drift_strict.returncode == 0:
            print("error: strict validation did not fail for raw source hash mismatch")
            print(drift_strict.stdout)
            return 1

        assert_no_pycache(root)

    print("wiki lifecycle regression checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
