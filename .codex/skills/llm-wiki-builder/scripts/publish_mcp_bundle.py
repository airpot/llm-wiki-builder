#!/usr/bin/env python3
"""Publish an LLM wiki as a read-only MCP bundle with an optional companion Skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from evaluate_retrieval import average_metric, evaluate_case, profile_gate_failures
from health_check import check_health
from publish_semantic_html import html_page_name, publish_html
from validate_wiki import validate_wiki
from wiki_lib import (
    artifact_matches,
    build_memory_artifacts,
    confined_output_path,
    confined_output_tree,
    default_delivery_contract,
    load_json,
    load_profiles,
    read_jsonl,
    relpath,
    slugify,
    utc_now,
    validate_delivery_contract_data,
    write_json,
)


BUNDLE_DIR = Path("reports") / "publish" / "mcp"
BUNDLE_SCHEMA = "llm-wiki-mcp-publish-v1"
RESOURCE_SCHEMA = "llm-wiki-mcp-resources-v1"
TOOL_SCHEMA = "llm-wiki-mcp-tools-v1"
PROMPT_SCHEMA = "llm-wiki-mcp-prompts-v1"
QUALITY_SCHEMA = "llm-wiki-mcp-quality-v1"
SERVER_CONFIG_SCHEMA = "llm-wiki-mcp-server-config-v1"
SCHEMA_MANIFEST_SCHEMA = "llm-wiki-generated-schemas-v1"
CONTEXT_PACK_SCHEMA_ID = "llm-wiki-context-pack-v1"
HTML_MANIFEST_SCHEMA_ID = "llm-wiki-semantic-html-manifest-v1"
SECTION_CHUNK_SCHEMA_ID = "llm-wiki-section-chunk-v1"

REQUIRED_FILES = [
    "manifest.json",
    "resources.json",
    "tools.json",
    "prompts.json",
    "quality.json",
    "server-config.json",
    "schemas/manifest.json",
    "schemas/context-pack.schema.json",
    "schemas/mcp-tools.schema.json",
    "schemas/quality.schema.json",
    "schemas/html-manifest.schema.json",
    "schemas/section-chunk.schema.json",
    "README.md",
]


def confined_path(root: Path, rel: str) -> Path:
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"path escapes wiki root: {rel}")
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"path escapes wiki root: {rel}")
    return resolved


def file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_freshness(root: Path, rel: str, expected: dict[str, Any]) -> dict[str, Any]:
    path = root / rel
    data, error = load_json(path, {})
    if not path.exists():
        status = "missing"
    elif error:
        status = "invalid"
    elif artifact_matches(data, expected):
        status = "fresh"
    else:
        status = "stale"
    return {
        "path": rel,
        "status": status,
        "sha256": file_sha256(path),
        "error": error,
    }


def retrieval_quality(root: Path, limit: int = 5) -> dict[str, Any]:
    cases, errors = read_jsonl(root / "retrieval-evals.jsonl")
    if errors:
        return {"status": "fail", "errors": errors, "case_count": len(cases)}
    if not cases:
        return {"status": "skipped", "reason": "no retrieval eval cases", "case_count": 0}

    profiles, profile_errors = load_profiles(root)
    if profile_errors:
        return {"status": "fail", "errors": profile_errors, "case_count": len(cases)}

    invalid: list[str] = []
    valid_cases: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case.get("id"), str) or not isinstance(case.get("query"), str):
            invalid.append(f"case {index}: requires id and query")
            continue
        if case.get("expect_miss") is not True and not case.get("expected_pages"):
            invalid.append(f"case {case['id']}: expected_pages required unless expect_miss is true")
            continue
        profile_id = case.get("profile_id")
        if profile_id and profile_id not in profiles:
            invalid.append(f"case {case['id']}: unknown profile_id {profile_id}")
            continue
        valid_cases.append(case)
    if invalid:
        return {"status": "fail", "errors": invalid, "case_count": len(cases)}

    results = [evaluate_case(root, case, limit) for case in valid_cases]
    positive = [result for result in results if not result.get("expect_miss")]
    negative = [result for result in results if result.get("expect_miss")]
    failures = [result["id"] for result in results if not result.get("passed")]
    gates = profile_gate_failures(profiles, positive)
    metrics = {
        "recall_at_k": round(average_metric(positive, "recall_at_k"), 3),
        "precision_at_k": round(average_metric(positive, "precision_at_k"), 3),
        "mrr_at_k": round(average_metric(positive, "mrr_at_k"), 3),
        "ndcg_at_k": round(average_metric(positive, "ndcg_at_k"), 3),
    }
    miss_accuracy = (
        round(sum(1 for result in negative if result.get("passed")) / len(negative), 3)
        if negative
        else None
    )
    return {
        "status": "fail" if failures or gates else "pass",
        "case_count": len(results),
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "failures": failures,
        "profile_gate_failures": gates,
        "metrics": metrics,
        "miss_accuracy": miss_accuracy,
    }


def profile_quality(root: Path, expected_index: dict[str, Any], retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    profiles, errors = load_profiles(root)
    if errors:
        return [{"profile_id": "profiles", "status": "unsafe", "issues": errors}]
    if not profiles:
        return []
    eval_cases, eval_errors = read_jsonl(root / "retrieval-evals.jsonl")
    pages = [page for page in expected_index.get("pages", []) if isinstance(page, dict)]
    summaries: list[dict[str, Any]] = []
    gates = retrieval.get("profile_gate_failures", {}) if isinstance(retrieval, dict) else {}
    for profile_id in sorted(profiles):
        page_count = sum(1 for page in pages if profile_id in page.get("profiles", []))
        eval_count = sum(1 for case in eval_cases if isinstance(case, dict) and case.get("profile_id") == profile_id)
        issues: list[str] = []
        if page_count == 0:
            issues.append("profile has no compiled pages")
        if eval_errors:
            issues.extend(eval_errors)
        elif eval_count == 0:
            issues.append("profile has no retrieval eval cases")
        gate_failures = gates.get(profile_id, []) if isinstance(gates, dict) else []
        issues.extend(str(item) for item in gate_failures)
        summaries.append(
            {
                "profile_id": profile_id,
                "page_count": page_count,
                "retrieval_eval_cases": eval_count,
                "status": "degraded" if issues else "ready",
                "issues": issues,
            }
        )
    return summaries


def readiness_fields(
    blockers: list[str],
    degradation_reasons: list[str],
    stale_artifacts: list[str],
) -> dict[str, Any]:
    if blockers:
        return {
            "readiness_level": "unsafe",
            "unsafe_to_answer": True,
            "agent_use_recommendation": "Do not answer from this wiki until blocking quality issues are repaired.",
            "blocking_reasons": blockers,
            "degradation_reasons": degradation_reasons,
            "stale_artifacts": stale_artifacts,
        }
    if degradation_reasons or stale_artifacts:
        return {
            "readiness_level": "degraded",
            "unsafe_to_answer": False,
            "agent_use_recommendation": "Use this wiki with caution: preserve uncertainty, inspect cited pages, and avoid unsupported claims.",
            "blocking_reasons": [],
            "degradation_reasons": degradation_reasons,
            "stale_artifacts": stale_artifacts,
        }
    return {
        "readiness_level": "ready",
        "unsafe_to_answer": False,
        "agent_use_recommendation": "The wiki is ready for read-only agent use with normal citation and uncertainty handling.",
        "blocking_reasons": [],
        "degradation_reasons": [],
        "stale_artifacts": [],
    }


def apply_readiness(report: dict[str, Any], contract_errors: list[str] | None = None) -> dict[str, Any]:
    contract_errors = contract_errors or []
    blockers = list(report.get("blockers", []))
    blockers.extend(f"contract: {item}" for item in contract_errors)
    degradation_reasons: list[str] = []
    validation = report.get("validation", {})
    health = report.get("health", {})
    retrieval = report.get("retrieval", {})
    if validation.get("warnings"):
        degradation_reasons.append("validation warnings present")
    for item in health.get("findings", []):
        if isinstance(item, dict) and item.get("severity") == "warning":
            degradation_reasons.append(f"health warning: {item.get('check')}")
    if retrieval.get("status") == "skipped":
        degradation_reasons.append(f"retrieval evals skipped: {retrieval.get('reason', 'unknown reason')}")
    profile_quality_items = report.get("profile_quality", [])
    for item in profile_quality_items:
        if isinstance(item, dict) and item.get("status") != "ready":
            degradation_reasons.append(f"profile {item.get('profile_id')} quality is {item.get('status')}")
    stale_artifacts = [
        str(item.get("path") or name)
        for name, item in report.get("freshness", {}).items()
        if isinstance(item, dict) and item.get("status") in {"missing", "invalid", "stale"}
    ]
    readiness = readiness_fields(blockers, sorted(set(degradation_reasons)), stale_artifacts)
    report.update(readiness)
    report["status"] = "fail" if readiness["readiness_level"] == "unsafe" else "pass"
    report["blockers"] = blockers
    report["contract"] = {"status": "fail" if contract_errors else "pass", "errors": contract_errors}
    return report


def quality_report(root: Path, expected_index: dict[str, Any], expected_graph: dict[str, Any]) -> dict[str, Any]:
    validation = validate_wiki(root)
    health = check_health(root)
    retrieval = retrieval_quality(root)
    freshness = {
        "memory-index.json": artifact_freshness(root, "memory-index.json", expected_index),
        "link-graph.json": artifact_freshness(root, "link-graph.json", expected_graph),
        "html_manifest": {
            "path": "reports/publish/html/manifest.json",
            "status": "present" if (root / "reports" / "publish" / "html" / "manifest.json").exists() else "missing",
            "sha256": file_sha256(root / "reports" / "publish" / "html" / "manifest.json"),
        },
    }
    blockers: list[str] = []
    blockers.extend(f"validation: {item}" for item in validation.get("errors", []))
    for item in health.get("findings", []):
        if item.get("severity") == "error":
            blockers.append(f"health: {item.get('check')} {item.get('path')}: {item.get('message')}")
    if retrieval.get("status") == "fail":
        blockers.append("retrieval: eval failures or profile gate failures")
    report = {
        "schema": QUALITY_SCHEMA,
        "generated_at": utc_now(),
        "status": "fail" if blockers else "pass",
        "blockers": blockers,
        "validation": {
            "status": validation.get("status"),
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []),
            "pages": validation.get("pages", 0),
            "profiles": validation.get("profiles", []),
        },
        "health": {
            "status": health.get("status"),
            "counts": health.get("counts", {}),
            "findings": health.get("findings", []),
        },
        "retrieval": retrieval,
        "freshness": freshness,
        "profile_quality": profile_quality(root, expected_index, retrieval),
    }
    return apply_readiness(report)


def source_records(root: Path, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for rel in ["SCHEMA.md", "index.md", "memory-index.json", "link-graph.json", "retrieval-evals.jsonl"]:
        path = root / rel
        if path.exists():
            records.append({"path": rel, "sha256": file_sha256(path)})
    for page in pages:
        path = str(page.get("path", ""))
        if path:
            records.append({"path": path, "sha256": file_sha256(root / path), "type": "wiki-page"})
    return records


def scoped_path(mode: str, rel: str) -> tuple[str, str]:
    if mode == "snapshot":
        return "bundle-root", f"snapshot/{rel}"
    return "wiki-root", rel


def resources_contract(
    root: Path,
    pages: list[dict[str, Any]],
    *,
    mode: str,
    bundle_root: Path | None = None,
) -> dict[str, Any]:
    index_scope, index_path = scoped_path(mode, "index.md")
    graph_scope, graph_path = scoped_path(mode, "link-graph.json")
    memory_scope, memory_path = scoped_path(mode, "memory-index.json")
    resources: list[dict[str, Any]] = [
        {
            "id": "manifest",
            "uri": "llm-wiki://manifest",
            "name": "MCP publish manifest",
            "mime_type": "application/json",
            "path": "manifest.json",
            "path_scope": "bundle-root",
            "generated": True,
        },
        {
            "id": "index",
            "uri": "llm-wiki://index",
            "name": "Wiki index",
            "mime_type": "text/markdown",
            "path": index_path,
            "path_scope": index_scope,
        },
        {
            "id": "graph",
            "uri": "llm-wiki://graph",
            "name": "Link graph",
            "mime_type": "application/json",
            "path": graph_path,
            "path_scope": graph_scope,
        },
        {
            "id": "memory-index",
            "uri": "llm-wiki://memory-index",
            "name": "Memory index",
            "mime_type": "application/json",
            "path": memory_path,
            "path_scope": memory_scope,
        },
        {
            "id": "quality",
            "uri": "llm-wiki://quality",
            "name": "Wiki quality report",
            "mime_type": "application/json",
            "path": "quality.json",
            "path_scope": "bundle-root",
            "generated": True,
        },
        {
            "id": "schemas",
            "uri": "llm-wiki://schemas",
            "name": "Generated schema manifest",
            "mime_type": "application/json",
            "path": "schemas/manifest.json",
            "path_scope": "bundle-root",
            "generated": True,
        },
    ]
    html_root = root / "reports" / "publish" / "html" / "pages"
    for page in pages:
        page_path = str(page.get("path") or "")
        if not page_path:
            continue
        slug = Path(html_page_name(page_path)).stem
        page_scope, scoped_page_path = scoped_path(mode, page_path)
        published_page = (bundle_root / "snapshot" / page_path) if mode == "snapshot" and bundle_root else root / page_path
        resources.append(
            {
                "id": f"page-md-{slug}",
                "uri": f"llm-wiki://page/{slug}.md",
                "name": str(page.get("title") or page_path),
                "mime_type": "text/markdown",
                "path": scoped_page_path,
                "path_scope": page_scope,
                "canonical": True,
                "content_hash": file_sha256(published_page),
                "confidence": page.get("confidence", "unknown"),
                "contested": bool(page.get("contested", False)),
                "profiles": page.get("profiles", []),
                "sources": page.get("sources", []),
            }
        )
        html_path = html_root / html_page_name(page_path)
        if html_path.exists():
            html_rel = relpath(html_path, root)
            html_scope, scoped_html_path = scoped_path(mode, html_rel)
            resources.append(
                {
                    "id": f"page-html-{slug}",
                    "uri": f"llm-wiki://page/{slug}.html",
                    "name": str(page.get("title") or page_path),
                    "mime_type": "text/html",
                    "path": scoped_html_path,
                    "path_scope": html_scope,
                    "generated": True,
                    "content_hash": file_sha256(
                        bundle_root / "snapshot" / html_rel
                        if mode == "snapshot" and bundle_root
                        else html_path
                    ),
                    "confidence": page.get("confidence", "unknown"),
                    "contested": bool(page.get("contested", False)),
                    "profiles": page.get("profiles", []),
                    "sources": page.get("sources", []),
                }
            )
    return {"schema": RESOURCE_SCHEMA, "resources": resources}


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


def string_array_schema() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def reason_counts_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": {"type": "integer"}}


def section_schema() -> dict[str, Any]:
    return object_schema(
        {
            "section_id": {"type": "string"},
            "heading": {"type": "string"},
            "heading_level": {"type": "integer"},
            "heading_path": string_array_schema(),
            "char_start": {"type": "integer"},
            "char_end": {"type": "integer"},
            "content_hash": {"type": "string"},
        },
        ["section_id", "heading", "heading_path", "char_start", "char_end"],
    )


def chunk_schema() -> dict[str, Any]:
    return object_schema(
        {
            "chunk_id": {"type": "string"},
            "path": {"type": "string"},
            "section_id": {"type": "string"},
            "heading": {"type": "string"},
            "heading_path": string_array_schema(),
            "char_start": {"type": "integer"},
            "char_end": {"type": "integer"},
            "excerpt": {"type": "string"},
            "excerpt_hash": {"type": "string"},
            "content_hash": {"type": "string"},
            "confidence": {"type": "string"},
            "contested": {"type": "boolean"},
            "sources": string_array_schema(),
            "match_type": {"type": "string", "enum": ["seed", "context"]},
            "score": {"type": "number"},
            "primary_score": {"type": "number"},
            "reasons": string_array_schema(),
            "reason_counts": reason_counts_schema(),
        },
        ["chunk_id", "path", "section_id", "heading_path", "char_start", "char_end", "excerpt", "excerpt_hash"],
    )


def context_page_schema() -> dict[str, Any]:
    return object_schema(
        {
            "path": {"type": "string"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "confidence": {"type": "string"},
            "contested": {"type": "boolean"},
            "profiles": string_array_schema(),
            "sources": string_array_schema(),
            "score": {"type": "number"},
            "primary_score": {"type": "number"},
            "match_type": {"type": "string", "enum": ["seed", "context"]},
            "seed": {"type": "boolean"},
            "reasons": string_array_schema(),
            "reason_counts": reason_counts_schema(),
            "excerpt": {"type": "string"},
            "excerpt_hash": {"type": "string"},
            "excerpt_budget_chars": {"type": "integer", "minimum": 1},
            "excerpt_chars_used": {"type": "integer", "minimum": 0},
            "max_chunks": {"type": "integer", "minimum": 1},
            "truncated": {"type": "boolean"},
            "section_index": {"type": "array", "items": section_schema()},
            "chunks": {"type": "array", "items": chunk_schema()},
        },
        [
            "path",
            "title",
            "match_type",
            "excerpt",
            "excerpt_budget_chars",
            "excerpt_chars_used",
            "max_chunks",
            "truncated",
            "chunks",
        ],
    )


def context_pack_schema() -> dict[str, Any]:
    return object_schema(
        {
            "schema": {"type": "string", "const": CONTEXT_PACK_SCHEMA_ID},
            "generated_at": {"type": "string"},
            "root": {"type": "string"},
            "query": {"type": "string"},
            "retrieval_mode": {"type": "string"},
            "options": object_schema(
                {
                    "limit": {"type": "integer", "minimum": 1},
                    "max_chars_per_page": {"type": "integer", "minimum": 1},
                    "max_chunks_per_page": {"type": "integer", "minimum": 1},
                    "expand_links": {"type": "boolean"},
                    "profile_id": {"type": ["string", "null"]},
                    "include_unprofiled": {"type": "boolean"},
                },
                ["limit", "max_chars_per_page", "max_chunks_per_page", "expand_links", "include_unprofiled"],
            ),
            "miss": {"type": "boolean"},
            "seed_pages": string_array_schema(),
            "context_pages": string_array_schema(),
            "pages": {"type": "array", "items": context_page_schema()},
            "report": {"type": "string"},
            "report_json": {"type": "string"},
        },
        ["schema", "generated_at", "query", "retrieval_mode", "options", "miss", "seed_pages", "context_pages", "pages"],
    )


def page_metadata_schema() -> dict[str, Any]:
    return object_schema(
        {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "confidence": {"type": "string"},
            "contested": {"type": "boolean"},
            "profiles": string_array_schema(),
            "sources": string_array_schema(),
            "headings": string_array_schema(),
            "section_index": {"type": "array", "items": section_schema()},
        },
    )


def tools_contract() -> dict[str, Any]:
    hit_schema = object_schema(
        {
            "path": {"type": "string"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "confidence": {"type": "string"},
            "contested": {"type": "boolean"},
            "profiles": {"type": "array", "items": {"type": "string"}},
            "score": {"type": "number"},
            "primary_score": {"type": "number"},
            "match_type": {"type": "string", "enum": ["seed", "context"]},
            "seed": {"type": "boolean"},
            "reasons": {"type": "array", "items": {"type": "string"}},
            "reason_counts": reason_counts_schema(),
        },
        ["path", "title", "match_type"],
    )
    tools = [
        {
            "name": "wiki_search",
            "description": "Run deterministic file-first retrieval over compiled wiki pages.",
            "input_schema": object_schema(
                {
                    "query": {"type": "string"},
                    "profile_id": {"type": "string"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 50},
                    "include_unprofiled": {"type": "boolean"},
                },
                ["query"],
            ),
            "output_schema": object_schema({"hits": {"type": "array", "items": hit_schema}}, ["hits"]),
            "read_only": True,
        },
        {
            "name": "wiki_read",
            "description": "Read one published Markdown, HTML, or metadata page by slug or path.",
            "input_schema": object_schema(
                {
                    "slug_or_path": {"type": "string"},
                    "format": {"type": "string", "enum": ["markdown", "html", "metadata"]},
                },
                ["slug_or_path"],
            ),
            "output_schema": object_schema(
                {
                    "path": {"type": "string"},
                    "format": {"type": "string", "enum": ["markdown", "html", "metadata"]},
                    "content": {"type": "string"},
                    "content_hash": {"type": "string"},
                    "canonical": {"type": "boolean"},
                    "generated": {"type": "boolean"},
                    "metadata": page_metadata_schema(),
                },
                ["path", "format", "content", "content_hash", "canonical", "generated"],
            ),
            "read_only": True,
        },
        {
            "name": "wiki_context_pack",
            "description": "Generate bounded task context with seed and one-hop context pages separated.",
            "input_schema": object_schema(
                {
                    "query": {"type": "string"},
                    "profile_id": {"type": "string"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 50},
                    "excerpt_budget_chars": {"type": "integer", "minimum": 1},
                    "max_chunks_per_page": {"type": "integer", "minimum": 1},
                    "format": {"type": "string", "enum": ["json", "markdown"]},
                },
                ["query"],
            ),
            "output_schema": context_pack_schema(),
            "read_only": True,
        },
        {
            "name": "wiki_quality_report",
            "description": "Return validation, health, retrieval, and freshness status for the wiki.",
            "input_schema": object_schema({"profile_id": {"type": "string"}}),
            "output_schema": object_schema(
                {
                    "status": {"type": "string"},
                    "readiness_level": {"type": "string", "enum": ["ready", "degraded", "unsafe"]},
                    "unsafe_to_answer": {"type": "boolean"},
                    "agent_use_recommendation": {"type": "string"},
                    "blocking_reasons": string_array_schema(),
                    "stale_artifacts": string_array_schema(),
                    "blockers": {"type": "array"},
                },
                ["status", "readiness_level", "unsafe_to_answer"],
            ),
            "read_only": True,
        },
    ]
    return {"schema": TOOL_SCHEMA, "tools": tools}


def prompts_contract() -> dict[str, Any]:
    prompts = [
        {
            "name": "answer_with_wiki",
            "description": "Search first, cite wiki paths, preserve low-confidence/contested uncertainty, and report misses.",
            "arguments": [{"name": "question", "required": True}],
        },
        {
            "name": "inspect_wiki_gaps",
            "description": "Inspect validation, health, profile, alias, glossary, retrieval-eval, and freshness gaps.",
            "arguments": [{"name": "profile_id", "required": False}],
        },
        {
            "name": "prepare_context_pack",
            "description": "Prepare bounded agent context instead of loading the whole wiki.",
            "arguments": [{"name": "task", "required": True}, {"name": "budget", "required": False}],
        },
    ]
    return {"schema": PROMPT_SCHEMA, "prompts": prompts}


def server_config(mode: str, executable: bool) -> dict[str, Any]:
    return {
        "schema": SERVER_CONFIG_SCHEMA,
        "transport": "stdio",
        "mode": mode,
        "status": "executable" if executable else "contract-only",
        "bundle_manifest": (BUNDLE_DIR / "manifest.json").as_posix(),
        "adapter": {
            "implemented": executable,
            "entrypoint": "server.py" if executable else None,
            "sdk": "mcp>=1.28,<2" if executable else None,
            "owner": "generated-wiki-application" if executable else None,
        },
        "policy": {
            "read_only": True,
            "path_confined": True,
            "raw_sources_excluded_by_default": True,
            "external_network_required": False,
            "external_model_required": False,
            "vector_store_required": False,
            "secrets_required": False,
        },
    }


def load_delivery_contract(root: Path) -> dict[str, Any]:
    path = root / "delivery-contract.json"
    if not path.exists():
        return default_delivery_contract()
    data, error = load_json(path, {})
    errors = ([f"invalid JSON: {error}"] if error else validate_delivery_contract_data(data))
    if errors:
        raise ValueError("; ".join(f"delivery-contract.json: {item}" for item in errors))
    return data


def privacy_replacements(root: Path, pages: list[dict[str, Any]]) -> dict[str, str]:
    replacements = {root.resolve().as_posix(): "[redacted-wiki-root]"}
    for page in pages:
        for source in page.get("sources", []):
            value = str(source)
            if Path(value).is_absolute():
                replacements[value] = "[redacted-absolute-source]"
    for rel in ("query-log.jsonl", "retrieval-evals.jsonl"):
        entries, _ = read_jsonl(root / rel)
        for entry in entries:
            query = entry.get("query")
            if isinstance(query, str) and query:
                replacements[query] = "[redacted-query]"
    return replacements


def sanitize_public_value(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_public_value(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_public_value(item, replacements) for item in value]
    if isinstance(value, str):
        sanitized = value
        for private, replacement in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            sanitized = sanitized.replace(private, replacement)
        return sanitized
    return value


def sanitize_snapshot_files(snapshot: Path, replacements: dict[str, str]) -> None:
    for path in sorted(snapshot.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        sanitized = sanitize_public_value(text, replacements)
        if sanitized != text:
            path.write_text(sanitized, encoding="utf-8")


def template_text(name: str, values: dict[str, str]) -> str:
    path = Path(__file__).resolve().parents[1] / "assets" / "templates" / name
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def write_runtime_artifacts(out: Path, root: Path, contract: dict[str, Any], executable: bool) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    if executable:
        (out / "server.py").write_text(template_text("mcp_server.py.tmpl", {}), encoding="utf-8")
        (out / "requirements.txt").write_text("mcp>=1.28,<2\n", encoding="utf-8")
        artifacts.update({"server": "server.py", "requirements": "requirements.txt"})
    if contract.get("publish_target") == "mcp-skill":
        skill_name = f"{slugify(root.name)[:52]}-wiki"
        skill_dir = out / "skills" / skill_name
        (skill_dir / "agents").mkdir(parents=True, exist_ok=True)
        values = {"skill_name": skill_name, "wiki_name": root.name}
        (skill_dir / "SKILL.md").write_text(template_text("mcp_skill.md.tmpl", values), encoding="utf-8")
        (skill_dir / "agents" / "openai.yaml").write_text(
            template_text("mcp_skill_openai.yaml.tmpl", values), encoding="utf-8"
        )
        artifacts["skill"] = f"skills/{skill_name}/SKILL.md"
    return artifacts


def tools_file_schema() -> dict[str, Any]:
    return object_schema(
        {
            "schema": {"type": "string", "const": TOOL_SCHEMA},
            "tools": {
                "type": "array",
                "items": object_schema(
                    {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                        "read_only": {"type": "boolean"},
                    },
                    ["name", "input_schema", "output_schema", "read_only"],
                ),
            },
        },
        ["schema", "tools"],
    )


def quality_file_schema() -> dict[str, Any]:
    return object_schema(
        {
            "schema": {"type": "string", "const": QUALITY_SCHEMA},
            "generated_at": {"type": "string"},
            "status": {"type": "string", "enum": ["pass", "fail"]},
            "readiness_level": {"type": "string", "enum": ["ready", "degraded", "unsafe"]},
            "unsafe_to_answer": {"type": "boolean"},
            "agent_use_recommendation": {"type": "string"},
            "blocking_reasons": string_array_schema(),
            "degradation_reasons": string_array_schema(),
            "stale_artifacts": string_array_schema(),
            "blockers": string_array_schema(),
            "validation": {"type": "object"},
            "health": {"type": "object"},
            "retrieval": {"type": "object"},
            "freshness": {"type": "object"},
            "profile_quality": {"type": "array"},
            "contract": {"type": "object"},
        },
        ["schema", "generated_at", "status", "readiness_level", "unsafe_to_answer"],
    )


def html_manifest_schema() -> dict[str, Any]:
    return object_schema(
        {
            "schema": {"type": "string", "const": HTML_MANIFEST_SCHEMA_ID},
            "generated_at": {"type": "string"},
            "root": {"type": "string"},
            "source": {"type": "string"},
            "index": {"type": "string"},
            "pages": string_array_schema(),
            "page_details": {
                "type": "array",
                "items": object_schema(
                    {
                        "path": {"type": "string"},
                        "html_path": {"type": "string"},
                        "title": {"type": "string"},
                        "confidence": {"type": "string"},
                        "contested": {"type": "boolean"},
                        "content_hash": {"type": "string"},
                        "section_count": {"type": "integer"},
                        "sections": {"type": "array", "items": section_schema()},
                    },
                    ["path", "html_path", "title", "sections"],
                ),
            },
            "page_count": {"type": "integer"},
        },
        ["schema", "generated_at", "index", "pages", "page_count"],
    )


def section_chunk_schema() -> dict[str, Any]:
    return {
        "schema": SECTION_CHUNK_SCHEMA_ID,
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "LLM Wiki Section Or Chunk Payload",
        "oneOf": [
            section_schema(),
            chunk_schema(),
        ],
        "$defs": {
            "section": section_schema(),
            "chunk": chunk_schema(),
        },
    }


def generated_schema_artifacts() -> dict[str, dict[str, Any]]:
    return {
        "context-pack.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "LLM Wiki Context Pack",
            **context_pack_schema(),
        },
        "mcp-tools.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "LLM Wiki MCP Tools Contract",
            **tools_file_schema(),
        },
        "quality.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "LLM Wiki MCP Quality Report",
            **quality_file_schema(),
        },
        "html-manifest.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "LLM Wiki Semantic HTML Manifest",
            **html_manifest_schema(),
        },
        "section-chunk.schema.json": section_chunk_schema(),
    }


def write_schema_artifacts(out: Path, generated_at: str) -> dict[str, Any]:
    schemas_dir = out / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schemas = generated_schema_artifacts()
    entries = []
    for filename, schema in sorted(schemas.items()):
        path = schemas_dir / filename
        write_json(path, schema)
        entries.append(
            {
                "id": filename.removesuffix(".schema.json"),
                "path": f"schemas/{filename}",
                "schema": schema.get("schema") or schema.get("title", ""),
                "sha256": file_sha256(path),
            }
        )
    manifest = {
        "schema": SCHEMA_MANIFEST_SCHEMA,
        "generated_at": generated_at,
        "schemas": entries,
    }
    write_json(schemas_dir / "manifest.json", manifest)
    return manifest


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for path in [src, *sorted(src.rglob("*"))]:
        if path.is_symlink():
            raise ValueError(f"snapshot source contains symbolic link: {path}")
    shutil.copytree(src, dst, dirs_exist_ok=True)


def build_snapshot(
    root: Path,
    out: Path,
    expected_index: dict[str, Any],
    expected_graph: dict[str, Any],
    replacements: dict[str, str],
) -> None:
    snapshot = out / "snapshot"
    confined_output_path(root, snapshot, scope="wiki root")
    if snapshot.exists():
        shutil.rmtree(snapshot)
    snapshot.mkdir(parents=True, exist_ok=True)
    for rel in ["SCHEMA.md", "delivery-contract.json", "index.md", "glossary.json", "glossary.jsonl"]:
        src = root / rel
        if src.exists():
            if src.is_symlink():
                raise ValueError(f"snapshot source contains symbolic link: {src}")
            confined_path(root, rel)
            dst = snapshot / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    write_json(snapshot / "memory-index.json", sanitize_public_value(expected_index, replacements))
    write_json(snapshot / "link-graph.json", sanitize_public_value(expected_graph, replacements))
    copy_tree(root / "profiles", snapshot / "profiles")
    copy_tree(root / "wiki", snapshot / "wiki")
    copy_tree(root / "reports" / "publish" / "html", snapshot / "reports" / "publish" / "html")
    snapshot_html_manifest = snapshot / "reports" / "publish" / "html" / "manifest.json"
    html_data, html_error = load_json(snapshot_html_manifest, {})
    if html_error or not isinstance(html_data, dict):
        raise ValueError(f"invalid semantic HTML manifest for snapshot: {html_error or 'not an object'}")
    html_data["root"] = "snapshot"
    write_json(snapshot_html_manifest, html_data)
    sanitize_snapshot_files(snapshot, replacements)


def validate_contract(
    root: Path,
    out: Path,
    contracts: list[dict[str, Any]],
    *,
    executable: bool,
    companion_skill_path: str | None,
) -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (out / rel).exists():
            errors.append(f"missing MCP artifact: {rel}")
    if executable:
        for rel in ("server.py", "requirements.txt"):
            if not (out / rel).is_file():
                errors.append(f"missing executable MCP artifact: {rel}")
    if companion_skill_path:
        skill_root = Path(companion_skill_path).parent
        for rel in (skill_root / "SKILL.md", skill_root / "agents" / "openai.yaml"):
            if not (out / rel).is_file():
                errors.append(f"missing companion Skill artifact: {rel}")
    seen_ids: set[str] = set()
    resources = contracts[0].get("resources", [])
    if not isinstance(resources, list) or not resources:
        errors.append("resources.json must contain resources")
    for resource in resources:
        if not isinstance(resource, dict):
            errors.append("resource entries must be objects")
            continue
        resource_id = str(resource.get("id") or "")
        uri = str(resource.get("uri") or "")
        path = str(resource.get("path") or "")
        if not resource_id or resource_id in seen_ids:
            errors.append(f"resource id is missing or duplicated: {resource_id}")
        seen_ids.add(resource_id)
        if not uri.startswith("llm-wiki://"):
            errors.append(f"resource {resource_id} URI must use llm-wiki://")
        path_parts = Path(path).parts
        if "raw" in path_parts:
            errors.append(f"resource {resource_id} must not expose raw sources by default")
        path_scope = str(resource.get("path_scope") or "wiki-root")
        if path_scope not in {"wiki-root", "bundle-root"}:
            errors.append(f"resource {resource_id} has invalid path_scope: {path_scope}")
            continue
        scope_root = out if path_scope == "bundle-root" else root
        try:
            resolved = confined_path(scope_root, path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if path_scope == "bundle-root" and not resolved.exists():
            errors.append(f"resource {resource_id} path is missing from bundle: {path}")
    for tool in contracts[1].get("tools", []):
        if not isinstance(tool.get("input_schema"), dict) or tool["input_schema"].get("type") != "object":
            errors.append(f"tool {tool.get('name')} input_schema must be an object schema")
        if not isinstance(tool.get("output_schema"), dict) or tool["output_schema"].get("type") != "object":
            errors.append(f"tool {tool.get('name')} output_schema must be an object schema")
        if tool.get("read_only") is not True:
            errors.append(f"tool {tool.get('name')} must be read-only")
    return errors


def readme_text(manifest: dict[str, Any]) -> str:
    lines = [
        "# LLM Wiki MCP Bundle",
        "",
        "This directory is a generated, read-only MCP publication target.",
        "",
        f"- Schema: `{manifest['schema']}`",
        f"- Mode: `{manifest['mode']}`",
        f"- Generated At: `{manifest['generated_at']}`",
        "- Canonical memory remains `wiki/**/*.md`.",
        "- Raw sources are excluded from snapshot mode by default.",
        "- Generated schemas are available under `schemas/`.",
        "- `server-config.json` declares runtime status and read-only safety policy.",
    ]
    runtime = manifest.get("runtime_artifacts", {})
    if runtime.get("server"):
        lines.append("- Install `requirements.txt`, then run `python3 server.py` from this directory.")
    else:
        lines.append("- This bundle is contract-only; provide a compatible adapter for `tools.json` and `resources.json`.")
    if runtime.get("skill"):
        lines.append(f"- Install `{Path(str(runtime['skill'])).parent.as_posix()}/` in the target agent host.")
    lines.append("")
    return "\n".join(lines)


def publish_mcp_bundle(root: Path, *, mode: str | None = None, clean: bool = False) -> dict[str, Any]:
    root = root.resolve()
    contract = load_delivery_contract(root)
    mode = mode or str(contract.get("publication_mode") or "snapshot")
    if mode not in {"linked", "snapshot"}:
        raise ValueError("mode must be linked or snapshot")
    executable = contract.get("mcp_runtime") == "executable" and contract.get("publish_target") in {"mcp", "mcp-skill"}
    out = root / BUNDLE_DIR
    confined_output_tree(root, out, scope="wiki root")
    if clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    html_manifest = publish_html(root, clean=True)
    expected_index, expected_graph = build_memory_artifacts(root)
    pages = [page for page in expected_index.get("pages", []) if isinstance(page, dict)]
    replacements = privacy_replacements(root, pages) if mode == "snapshot" else {}
    if mode == "snapshot":
        build_snapshot(root, out, expected_index, expected_graph, replacements)
        published_html_manifest = sanitize_public_value(dict(html_manifest), replacements)
        published_html_manifest["root"] = "snapshot"
    else:
        published_html_manifest = html_manifest

    generated_at = utc_now()
    public_pages = sanitize_public_value(pages, replacements)
    resources = resources_contract(root, public_pages, mode=mode, bundle_root=out)
    tools = tools_contract()
    prompts = prompts_contract()
    quality = sanitize_public_value(quality_report(root, expected_index, expected_graph), replacements)
    config = server_config(mode, executable)
    schema_manifest = write_schema_artifacts(out, generated_at)

    write_json(out / "resources.json", resources)
    write_json(out / "tools.json", tools)
    write_json(out / "prompts.json", prompts)
    write_json(out / "quality.json", quality)
    write_json(out / "server-config.json", config)
    runtime_artifacts = write_runtime_artifacts(out, root, contract, executable)

    manifest = {
        "schema": BUNDLE_SCHEMA,
        "generated_at": generated_at,
        "mode": mode,
        "root": root.as_posix() if mode == "linked" else "snapshot",
        "canonical_source": "wiki/**/*.md",
        "source_policy": {
            "markdown_is_canonical": True,
            "mcp_artifacts_are_generated": True,
            "raw_sources_excluded_by_default": True,
            "read_only": True,
        },
        "delivery_contract": sanitize_public_value(contract, replacements),
        "runtime_artifacts": runtime_artifacts,
        "resources": "resources.json",
        "tools": "tools.json",
        "prompts": "prompts.json",
        "quality": "quality.json",
        "server_config": "server-config.json",
        "schemas": schema_manifest,
        "html_manifest": published_html_manifest,
        "pages": [{"path": page["path"], "title": page.get("title", ""), "slug": page.get("slug", "")} for page in public_pages],
        "source_hashes": source_records(root, pages),
    }
    write_json(out / "manifest.json", manifest)
    (out / "README.md").write_text(readme_text(manifest), encoding="utf-8")

    contract_errors = validate_contract(
        root,
        out,
        [resources, tools, prompts, quality, config],
        executable=executable,
        companion_skill_path=runtime_artifacts.get("skill"),
    )
    quality = apply_readiness(quality, contract_errors)
    write_json(out / "quality.json", quality)
    manifest["contract_status"] = "fail" if contract_errors else "pass"
    manifest["contract_errors"] = contract_errors
    write_json(out / "manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument(
        "--mode",
        choices=["linked", "snapshot"],
        default=None,
        help="Publication mode override; defaults to delivery-contract.json (snapshot for new wikis)",
    )
    parser.add_argument("--clean", action="store_true", help="Remove previous MCP bundle before publishing")
    parser.add_argument("--strict", action="store_true", help="Fail when quality status is not pass")
    parser.add_argument("--json", action="store_true", help="Print manifest JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        manifest = publish_mcp_bundle(Path(args.wiki_root), mode=args.mode, clean=args.clean)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    quality, _ = load_json(Path(args.wiki_root) / BUNDLE_DIR / "quality.json", {})
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(f"published: {(BUNDLE_DIR / 'manifest.json').as_posix()}")
        print(f"mode: {manifest['mode']}")
        print(f"contract: {manifest.get('contract_status')}")
        print(f"quality: {quality.get('status', 'unknown') if isinstance(quality, dict) else 'unknown'}")
    if manifest.get("contract_status") != "pass":
        return 1
    if args.strict and isinstance(quality, dict) and quality.get("status") != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
