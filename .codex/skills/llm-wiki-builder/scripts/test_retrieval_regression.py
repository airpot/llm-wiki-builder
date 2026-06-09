#!/usr/bin/env python3
"""Regression checks for deterministic wiki retrieval."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import subprocess
import tempfile
from pathlib import Path

from init_wiki import init_wiki
from wiki_lib import build_memory_artifacts, retrieve, write_json

SCRIPT_DIR = Path(__file__).resolve().parent


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


def write_contract_page(root: Path) -> None:
    page = root / "wiki" / "concepts" / "retrieval-contract.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        """---
title: Retrieval Contract
slug: retrieval-contract
created: 2026-06-09
updated: 2026-06-09
type: concept
summary: Retrieval contract defines seed hits and context expansion.
aliases: []
tags: [retrieval]
sources: []
profiles: [core]
confidence: medium
contested: false
---

# Retrieval Contract

A retrieval contract defines seed hits and context expansion.
""",
        encoding="utf-8",
    )


def write_playbook_page(root: Path) -> None:
    page = root / "wiki" / "concepts" / "playbook-contract.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        """---
title: Playbook Contract
slug: playbook-contract
created: 2026-06-09
updated: 2026-06-09
type: concept
summary: Playbook contract is profile-isolated.
aliases: []
tags: [retrieval]
sources: []
profiles: [playbook]
confidence: medium
contested: false
---

# Playbook Contract

Playbook contract is profile-isolated.
""",
        encoding="utf-8",
    )


def write_path_stem_page(root: Path) -> None:
    page = root / "wiki" / "concepts" / "internal-code.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        """---
title: Different Name
slug: different-name
created: 2026-06-09
updated: 2026-06-09
type: concept
summary: This page intentionally omits the filename terms.
aliases: []
tags: []
sources: []
profiles: [core]
confidence: medium
contested: false
---

# Different Name

This body intentionally avoids filename words.
""",
        encoding="utf-8",
    )


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="llm-wiki-retrieval-regression-") as tmp:
        root = Path(tmp)
        init_wiki(root)
        write_page(root)
        write_contract_page(root)
        write_playbook_page(root)
        write_path_stem_page(root)
        (root / "profiles").mkdir(exist_ok=True)
        write_json(
            root / "profiles" / "core.json",
            {
                "schema": "llm-wiki-extraction-profile-v1",
                "profile_id": "core",
                "purpose": "Core retrieval contract.",
                "target_audience": ["agent"],
                "extract_dimensions": ["retrieval"],
                "exclude_dimensions": ["playbook"],
                "page_types": ["concept"],
                "granularity": "topic-level",
                "evidence_policy": "source-attributed",
                "conflict_policy": "preserve",
                "output_roots": ["wiki/concepts"],
                "retrieval": {
                    "min_seed_score": 1,
                    "min_recall_at_k": 1.0,
                    "min_mrr_at_k": 1.0,
                    "allow_glossary_expansion": True,
                },
            },
        )
        write_json(
            root / "profiles" / "playbook.json",
            {
                "schema": "llm-wiki-extraction-profile-v1",
                "profile_id": "playbook",
                "purpose": "Playbook retrieval contract.",
                "target_audience": ["agent"],
                "extract_dimensions": ["steps"],
                "exclude_dimensions": ["core"],
                "page_types": ["concept"],
                "granularity": "task-level",
                "evidence_policy": "source-attributed",
                "conflict_policy": "preserve",
                "output_roots": ["wiki/concepts"],
                "retrieval": {"allow_glossary_expansion": False},
            },
        )
        write_json(
            root / "glossary.json",
            {
                "schema": "llm-wiki-glossary-v1",
                "terms": [
                    {"canonical": "retrieval", "aliases": ["retrieval", "检索"]},
                    {"canonical": "contract", "aliases": ["contract", "契约"]},
                ],
            },
        )
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
        path_stem_hits = retrieve(root, "internal-code", limit=5, profile="core")
        if not path_stem_hits or path_stem_hits[0]["path"] != "wiki/concepts/internal-code.md":
            print("error: path-stem query did not return expected page")
            print(path_stem_hits)
            return 1
        if "path_stem" not in path_stem_hits[0].get("reasons", []):
            print("error: path-stem hit did not expose path_stem reason")
            print(path_stem_hits)
            return 1
        full_path_hits = retrieve(root, "wiki/concepts/internal-code.md", limit=5, profile="core")
        if not full_path_hits or full_path_hits[0]["path"] != "wiki/concepts/internal-code.md":
            print("error: full path query did not return expected page")
            print(full_path_hits)
            return 1
        if "path" not in full_path_hits[0].get("reasons", []):
            print("error: full path hit did not expose path reason")
            print(full_path_hits)
            return 1

        glossary_hits = retrieve(root, "检索 契约", limit=5, profile="core")
        if not glossary_hits or glossary_hits[0]["path"] != "wiki/concepts/retrieval-contract.md":
            print("error: glossary query did not return expected page")
            print(glossary_hits)
            return 1
        if glossary_hits[0].get("match_type") != "seed" or "glossary" not in glossary_hits[0].get("reasons", []):
            print("error: glossary hit did not expose seed/glossary reasons")
            print(glossary_hits)
            return 1
        profile_filtered = retrieve(root, "检索 契约", limit=5, profile="playbook")
        if any(hit["path"] == "wiki/concepts/retrieval-contract.md" for hit in profile_filtered):
            print("error: glossary expansion bypassed profile filter")
            print(profile_filtered)
            return 1
        if any("glossary" in hit.get("reasons", []) for hit in profile_filtered):
            print("error: disabled glossary expansion still produced glossary reasons")
            print(profile_filtered)
            return 1

        good_eval = {
            "id": "path-stem",
            "query": "internal-code",
            "expected_pages": ["wiki/concepts/internal-code.md"],
            "profile_id": "core",
            "require_seed_hit": True,
        }
        negative_eval = {"id": "negative", "query": "zzzz no-overlap-query", "expect_miss": True}
        (root / "retrieval-evals.jsonl").write_text(
            json.dumps(good_eval) + "\n" + json.dumps(negative_eval) + "\n",
            encoding="utf-8",
        )
        eval_result = run_command([sys.executable, str(SCRIPT_DIR / "evaluate_retrieval.py"), str(root), "--json", "--no-report"])
        if eval_result.returncode != 0:
            print("error: profile gates failed unexpectedly for passing eval")
            print(eval_result.stdout)
            print(eval_result.stderr)
            return 1

        profile = root / "profiles" / "core.json"
        profile_data = json.loads(profile.read_text(encoding="utf-8"))
        profile_data["retrieval"]["min_seed_score"] = 9999
        write_json(profile, profile_data)
        gate_result = run_command([sys.executable, str(SCRIPT_DIR / "evaluate_retrieval.py"), str(root), "--json", "--no-report"])
        if gate_result.returncode == 0 or "profile_gate_failures" not in gate_result.stdout:
            print("error: min_seed_score gate failure was not enforced")
            print(gate_result.stdout)
            print(gate_result.stderr)
            return 1

        profile_data["retrieval"]["min_seed_score"] = 1
        profile_data["retrieval"]["min_recall_at_k"] = 1.1
        write_json(profile, profile_data)
        invalid_profile_result = run_command([sys.executable, str(SCRIPT_DIR / "validate_wiki.py"), str(root), "--strict"])
        if invalid_profile_result.returncode == 0:
            print("error: invalid profile recall gate passed strict validation")
            print(invalid_profile_result.stdout)
            return 1

        profile_data["retrieval"]["min_recall_at_k"] = 1.0
        write_json(profile, profile_data)
        bad_negative = {
            "id": "bad-negative",
            "query": "zzzz no-overlap-query",
            "expect_miss": True,
            "expected_pages": ["wiki/concepts/internal-code.md"],
        }
        (root / "retrieval-evals.jsonl").write_text(json.dumps(bad_negative) + "\n", encoding="utf-8")
        bad_validation = run_command([sys.executable, str(SCRIPT_DIR / "validate_wiki.py"), str(root), "--json"])
        if bad_validation.returncode == 0 or "expected_pages must be omitted or empty" not in bad_validation.stdout:
            print("error: malformed expected-miss eval was not rejected by validation")
            print(bad_validation.stdout)
            print(bad_validation.stderr)
            return 1

    print("retrieval regression checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
