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
from wiki_lib import build_memory_artifacts, retrieve, source_body_hash, tokenize, write_json


SCRIPT_DIR = Path(__file__).resolve().parent

CORE_DIRECTION = {
    "purpose": "Maintain deterministic LLM wiki retrieval knowledge.",
    "primary_users": ["agent", "engineer"],
    "core_knowledge_targets": ["memory concepts", "retrieval procedures"],
    "out_of_scope": ["unrelated background"],
    "landing_granularity": "topic-level",
    "evidence_policy": "source-attributed-claims",
    "conflict_policy": "preserve-contested-claims",
    "success_queries": ["transformer memory retrieval"],
}

CORE_PROFILE = {
    "schema": "llm-wiki-extraction-profile-v1",
    "profile_id": "core",
    "name": "Core Memory Wiki",
    "purpose": "Compile source material into core retrieval knowledge.",
    "target_audience": ["agent", "engineer"],
    "extract_dimensions": ["concepts", "links", "retrieval cues"],
    "exclude_dimensions": ["off-topic history"],
    "page_types": ["concept", "note", "query"],
    "granularity": "topic-level",
    "evidence_policy": "source-attributed-claims",
    "conflict_policy": "preserve-contested-claims",
    "output_roots": ["wiki/concepts", "wiki/queries"],
    "required_sections_by_type": {},
    "eval_queries": ["transformer memory retrieval"],
}

PLAYBOOK_PROFILE = {
    "schema": "llm-wiki-extraction-profile-v1",
    "profile_id": "playbook",
    "name": "Implementation Playbook",
    "purpose": "Compile source material into operational playbook knowledge.",
    "target_audience": ["agent", "engineer"],
    "extract_dimensions": ["steps", "failure modes", "validation"],
    "exclude_dimensions": ["concept-only background"],
    "page_types": ["concept", "note", "query"],
    "granularity": "task-level",
    "evidence_policy": "source-attributed-actionable-claims",
    "conflict_policy": "preserve-contested-claims",
    "output_roots": ["wiki/concepts", "wiki/queries"],
    "required_sections_by_type": {},
    "eval_queries": ["memory playbook validation"],
}


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def init_profile_wiki(root: Path) -> None:
    init_wiki(root, core_direction=CORE_DIRECTION, profiles=[CORE_PROFILE, PLAYBOOK_PROFILE], draft=False)


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
profiles: [core]
extraction_goal: core retrieval knowledge
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


def write_alias_page(root: Path) -> None:
    page = root / "wiki" / "concepts" / "alias-target.md"
    page.write_text(
        """---
title: Alias Target
slug: alias-target
created: 2026-06-06
updated: 2026-06-06
type: concept
summary: Alias target validates wikilink graph resolution.
aliases: [Graph Alias]
tags: [memory]
sources: [raw/articles/transformer-memory-source.md]
profiles: [core]
extraction_goal: alias graph validation
confidence: medium
contested: false
---

# Alias Target

Alias target validates wikilink graph resolution through aliases.

## Notes

This page exists so another compiled page can link to [[Graph Alias]].
""",
        encoding="utf-8",
    )


def write_cjk_page(root: Path) -> None:
    page = root / "wiki" / "concepts" / "cjk-memory.md"
    page.write_text(
        """---
title: 中文记忆索引
slug: cjk-memory
created: 2026-06-06
updated: 2026-06-06
type: concept
summary: 这个页面解释注意力记忆和上下文检索。
aliases: [记忆索引]
tags: [中文, 记忆]
sources: [raw/articles/transformer-memory-source.md]
profiles: [core]
extraction_goal: CJK retrieval coverage
confidence: medium
contested: false
---

# 中文记忆索引

注意力记忆依赖上下文检索和页面链接。
""",
        encoding="utf-8",
    )


def prepare_wiki(root: Path) -> None:
    init_profile_wiki(root)
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
        "- [[Transformer Memory]] gives the index useful retrieval context.\n- [[Graph Alias]] validates alias link resolution.",
    )
    write_alias_page(root)
    write_cjk_page(root)
    write_page(
        root,
        "wiki/concepts/memory-playbook.md",
        "Memory Playbook",
        "memory-playbook",
        "Memory playbook validation tracks operational retrieval steps.",
        "- [[Transformer Memory]] provides source context.",
    )
    playbook = root / "wiki" / "concepts" / "memory-playbook.md"
    playbook.write_text(playbook.read_text(encoding="utf-8").replace("profiles: [core]", "profiles: [playbook]"), encoding="utf-8")
    (root / "index.md").write_text(
        """# Wiki Index

## Pages

- wiki/concepts/transformer-memory.md - Transformer memory.
- wiki/concepts/memory-index.md - Memory index.
- wiki/concepts/alias-target.md - Alias target.
- wiki/concepts/cjk-memory.md - 中文记忆索引.
- wiki/concepts/memory-playbook.md - Memory playbook.
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
    if not any(
        link["source"] == "wiki/concepts/memory-index.md" and link["target"] == "wiki/concepts/alias-target.md"
        for link in link_graph["links"]
    ):
        raise AssertionError("alias wikilink did not produce a link-graph edge")
    write_json(root / "memory-index.json", memory_index)
    write_json(root / "link-graph.json", link_graph)
    (root / "retrieval-evals.jsonl").write_text(
        json.dumps(
            {
                "id": "transformer-memory",
                "query": "transformer memory retrieval",
                "expected_pages": ["wiki/concepts/transformer-memory.md"],
                "forbidden_pages": ["wiki/concepts/not-present.md"],
                "profile_id": "core",
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


def check_initialization_contract(root: Path) -> int:
    inputs = root / "init-inputs"
    core_path = inputs / "core.json"
    profile_path = inputs / "core-profile.json"
    playbook_path = inputs / "playbook-profile.json"
    write_json(core_path, CORE_DIRECTION)
    write_json(profile_path, CORE_PROFILE)
    write_json(playbook_path, PLAYBOOK_PROFILE)

    missing_inputs = run_command([sys.executable, str(SCRIPT_DIR / "init_wiki.py"), str(root / "missing-inputs")])
    if missing_inputs.returncode == 0 or "normal initialization requires" not in missing_inputs.stderr:
        print("error: normal init did not reject missing core/profile inputs")
        print(missing_inputs.stdout)
        print(missing_inputs.stderr)
        return 1

    bad_core = dict(CORE_DIRECTION)
    bad_core["purpose"] = "unspecified"
    bad_core_path = inputs / "bad-core.json"
    write_json(bad_core_path, bad_core)
    bad_core_result = run_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "init_wiki.py"),
            str(root / "bad-core"),
            "--core-direction-json",
            str(bad_core_path),
            "--profile-json",
            str(profile_path),
        ]
    )
    if bad_core_result.returncode == 0 or "core direction purpose" not in bad_core_result.stderr:
        print("error: normal init did not reject placeholder core direction")
        print(bad_core_result.stdout)
        print(bad_core_result.stderr)
        return 1

    bad_profile = dict(CORE_PROFILE)
    bad_profile["extract_dimensions"] = ["concepts", "placeholder"]
    bad_profile_path = inputs / "bad-profile.json"
    write_json(bad_profile_path, bad_profile)
    bad_profile_result = run_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "init_wiki.py"),
            str(root / "bad-profile"),
            "--core-direction-json",
            str(core_path),
            "--profile-json",
            str(bad_profile_path),
        ]
    )
    if bad_profile_result.returncode == 0 or "extract_dimensions" not in bad_profile_result.stderr:
        print("error: normal init did not reject placeholder profile list values")
        print(bad_profile_result.stdout)
        print(bad_profile_result.stderr)
        return 1

    duplicate_profile_result = run_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "init_wiki.py"),
            str(root / "duplicate-profile"),
            "--core-direction-json",
            str(core_path),
            "--profile-json",
            str(profile_path),
            "--profile-json",
            str(profile_path),
        ]
    )
    if duplicate_profile_result.returncode == 0 or "duplicate profile_id core" not in duplicate_profile_result.stderr:
        print("error: normal init did not reject duplicate profile ids")
        print(duplicate_profile_result.stdout)
        print(duplicate_profile_result.stderr)
        return 1

    normal_root = root / "normal-init"
    normal_result = run_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "init_wiki.py"),
            str(normal_root),
            "--core-direction-json",
            str(core_path),
            "--profile-json",
            str(profile_path),
            "--profile-json",
            str(playbook_path),
        ]
    )
    if normal_result.returncode != 0:
        print("error: normal init with confirmed core/profile inputs failed")
        print(normal_result.stdout)
        print(normal_result.stderr)
        return 1
    if not (normal_root / "profiles" / "core.json").exists() or not (normal_root / "profiles" / "playbook.json").exists():
        print("error: normal init did not create expected profile files")
        print(normal_result.stdout)
        return 1
    schema_text = (normal_root / "SCHEMA.md").read_text(encoding="utf-8")
    if "## Wiki Core Direction" not in schema_text or "unspecified" in schema_text.lower():
        print("error: normal init did not persist a complete core direction")
        print(schema_text)
        return 1
    strict_result = run_command([sys.executable, str(SCRIPT_DIR / "validate_wiki.py"), str(normal_root), "--strict"])
    if strict_result.returncode != 0:
        print("error: strict validation failed for normal purpose/profile initialization")
        print(strict_result.stdout)
        print(strict_result.stderr)
        return 1
    return 0


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="llm-wiki-lifecycle-") as tmp:
        root = Path(tmp)
        contract_result = check_initialization_contract(root)
        if contract_result:
            return contract_result

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
        profile_hits = retrieve(root, "memory playbook validation", limit=5, profile="playbook")
        if not profile_hits or profile_hits[0]["path"] != "wiki/concepts/memory-playbook.md":
            print("error: playbook profile retrieval did not rank expected page first")
            print(profile_hits)
            return 1
        core_filtered_hits = retrieve(root, "memory playbook validation", limit=5, profile="core")
        if any(hit["path"] == "wiki/concepts/memory-playbook.md" for hit in core_filtered_hits):
            print("error: core profile retrieval returned unrelated playbook page")
            print(core_filtered_hits)
            return 1
        cjk_hits = retrieve(root, "注意力记忆 上下文检索", limit=5)
        if not cjk_hits or cjk_hits[0]["path"] != "wiki/concepts/cjk-memory.md":
            print("error: CJK lexical retrieval did not rank expected page first")
            print({"tokens": tokenize("注意力记忆 上下文检索"), "hits": cjk_hits})
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
        new_page = root / "wiki" / "concepts" / "new-topic.md"
        new_page.write_text(
            """---
title: New Topic
slug: new-topic
created: 2026-06-06
updated: 2026-06-06
type: concept
summary: Needle retrieval topic.
aliases: []
tags: []
sources: [raw/articles/transformer-memory-source.md]
profiles: [core]
extraction_goal: stale retrieval fixture
confidence: medium
contested: false
---

# New Topic

Needle retrieval topic.
""",
            encoding="utf-8",
        )
        stale_hits = retrieve(root, "needle retrieval", limit=5)
        if not stale_hits or stale_hits[0]["path"] != "wiki/concepts/new-topic.md":
            print("error: stale generated artifacts caused a retrieval miss")
            print(stale_hits)
            return 1

        prepare_wiki(root)
        legacy_page = root / "wiki" / "concepts" / "legacy-memory.md"
        legacy_page.write_text(
            """---
title: Legacy Memory
slug: legacy-memory
created: 2026-06-06
updated: 2026-06-06
type: concept
summary: Legacy memory page is intentionally unprofiled.
aliases: []
tags: [memory]
sources: [raw/articles/transformer-memory-source.md]
confidence: medium
contested: false
---

# Legacy Memory

Legacy memory page is available only when unprofiled pages are explicitly included.
""",
            encoding="utf-8",
        )
        unprofiled_excluded = retrieve(root, "legacy memory", limit=5, profile="core")
        if any(hit["path"] == "wiki/concepts/legacy-memory.md" for hit in unprofiled_excluded):
            print("error: profile retrieval included unprofiled page without opt-in")
            print(unprofiled_excluded)
            return 1
        unprofiled_included = retrieve(root, "legacy memory", limit=5, profile="core", include_unprofiled=True)
        if not any(hit["path"] == "wiki/concepts/legacy-memory.md" for hit in unprofiled_included):
            print("error: include_unprofiled did not include legacy page")
            print(unprofiled_included)
            return 1

        prepare_wiki(root)
        raw = root / "raw" / "articles" / "transformer-memory-source.md"
        raw.write_text(raw.read_text(encoding="utf-8") + "\nHash drift.\n", encoding="utf-8")
        drift_validation = validate_wiki(root)
        if not any("sha256 mismatch" in warning for warning in drift_validation["warnings"]):
            print("error: raw source hash mismatch was not detected")
            print(json.dumps(drift_validation, indent=2, ensure_ascii=False))
            return 1
        drift_strict = run_command([sys.executable, str(SCRIPT_DIR / "validate_wiki.py"), str(root), "--strict"])
        if drift_strict.returncode == 0:
            print("error: strict validation did not fail for raw source hash mismatch")
            print(drift_strict.stdout)
            return 1

        prepare_wiki(root)
        raw = root / "raw" / "articles" / "transformer-memory-source.md"
        raw.write_text(raw.read_text(encoding="utf-8").replace("source_hash: ", "source_hash: invalid-"), encoding="utf-8")
        dual_hash_validation = validate_wiki(root)
        if not any("source_hash mismatch" in warning for warning in dual_hash_validation["warnings"]):
            print("error: source_hash mismatch was not detected when sha256 was valid")
            print(json.dumps(dual_hash_validation, indent=2, ensure_ascii=False))
            return 1

        prepare_wiki(root)
        first_report = run_command([sys.executable, str(SCRIPT_DIR / "validate_wiki.py"), str(root), "--report"])
        second_report = run_command([sys.executable, str(SCRIPT_DIR / "validate_wiki.py"), str(root), "--report"])
        if first_report.returncode != 0 or second_report.returncode != 0:
            print("error: validation report command failed")
            print(first_report.stdout)
            print(second_report.stdout)
            return 1
        reports = sorted((root / "reports" / "validation").glob("*-validation.md"))
        if len(reports) < 2 or len({report.name for report in reports}) != len(reports):
            print("error: back-to-back validation reports collided")
            print([report.name for report in reports])
            return 1

        assert_no_pycache(root)

    print("wiki lifecycle regression checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
