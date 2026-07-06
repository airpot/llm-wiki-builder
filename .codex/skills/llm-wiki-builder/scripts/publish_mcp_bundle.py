#!/usr/bin/env python3
"""Publish an LLM wiki as a read-only MCP-ready bundle."""

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
    load_json,
    load_profiles,
    read_jsonl,
    relpath,
    slugify,
    utc_now,
    write_json,
)


BUNDLE_DIR = Path("reports") / "publish" / "mcp"
BUNDLE_SCHEMA = "llm-wiki-mcp-publish-v1"
RESOURCE_SCHEMA = "llm-wiki-mcp-resources-v1"
TOOL_SCHEMA = "llm-wiki-mcp-tools-v1"
PROMPT_SCHEMA = "llm-wiki-mcp-prompts-v1"
QUALITY_SCHEMA = "llm-wiki-mcp-quality-v1"
SERVER_CONFIG_SCHEMA = "llm-wiki-mcp-server-config-v1"

REQUIRED_FILES = [
    "manifest.json",
    "resources.json",
    "tools.json",
    "prompts.json",
    "quality.json",
    "server-config.json",
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
    return {
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
    }


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


def resources_contract(root: Path, pages: list[dict[str, Any]], *, mode: str) -> dict[str, Any]:
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
    ]
    html_root = root / "reports" / "publish" / "html" / "pages"
    for page in pages:
        page_path = str(page.get("path") or "")
        if not page_path:
            continue
        slug = slugify(Path(page_path).with_suffix("").as_posix())
        page_scope, scoped_page_path = scoped_path(mode, page_path)
        resources.append(
            {
                "id": f"page-md-{slug}",
                "uri": f"llm-wiki://page/{slug}.md",
                "name": str(page.get("title") or page_path),
                "mime_type": "text/markdown",
                "path": scoped_page_path,
                "path_scope": page_scope,
                "canonical": True,
                "confidence": page.get("confidence", "unknown"),
                "contested": bool(page.get("contested", False)),
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
                }
            )
    return {"schema": RESOURCE_SCHEMA, "resources": resources}


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


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
            "reasons": {"type": "array", "items": {"type": "string"}},
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
                {"path": {"type": "string"}, "format": {"type": "string"}, "content": {"type": "string"}},
                ["path", "format", "content"],
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
                    "excerpt_budget_chars": {"type": "integer", "minimum": 0},
                    "format": {"type": "string", "enum": ["json", "markdown"]},
                },
                ["query"],
            ),
            "output_schema": object_schema(
                {
                    "query": {"type": "string"},
                    "seed_pages": {"type": "array", "items": {"type": "string"}},
                    "context_pages": {"type": "array", "items": {"type": "string"}},
                    "budget": {"type": "object"},
                    "pages": {"type": "array", "items": hit_schema},
                },
                ["query", "seed_pages", "context_pages", "pages"],
            ),
            "read_only": True,
        },
        {
            "name": "wiki_quality_report",
            "description": "Return validation, health, retrieval, and freshness status for the wiki.",
            "input_schema": object_schema({"profile_id": {"type": "string"}}),
            "output_schema": object_schema({"status": {"type": "string"}, "blockers": {"type": "array"}}, ["status"]),
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


def server_config(mode: str) -> dict[str, Any]:
    return {
        "schema": SERVER_CONFIG_SCHEMA,
        "transport": "stdio",
        "mode": mode,
        "status": "contract-only",
        "bundle_manifest": (BUNDLE_DIR / "manifest.json").as_posix(),
        "adapter": {
            "implemented": False,
            "reason": "First release keeps MCP bundle generation dependency-light; executable server adapter is follow-up work.",
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


def copy_tree(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def build_snapshot(root: Path, out: Path, expected_index: dict[str, Any], expected_graph: dict[str, Any]) -> None:
    snapshot = out / "snapshot"
    if snapshot.exists():
        shutil.rmtree(snapshot)
    snapshot.mkdir(parents=True, exist_ok=True)
    for rel in ["SCHEMA.md", "index.md", "log.md", "retrieval-evals.jsonl", "query-log.jsonl", "glossary.json", "glossary.jsonl"]:
        src = root / rel
        if src.exists():
            dst = snapshot / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    write_json(snapshot / "memory-index.json", expected_index)
    write_json(snapshot / "link-graph.json", expected_graph)
    copy_tree(root / "profiles", snapshot / "profiles")
    copy_tree(root / "wiki", snapshot / "wiki")
    copy_tree(root / "reports" / "context-packs", snapshot / "reports" / "context-packs")
    copy_tree(root / "reports" / "publish" / "html", snapshot / "reports" / "publish" / "html")


def validate_contract(root: Path, out: Path, contracts: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (out / rel).exists():
            errors.append(f"missing MCP artifact: {rel}")
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
    return "\n".join(
        [
            "# LLM Wiki MCP Bundle",
            "",
            "This directory is a generated, read-only MCP-ready publication target.",
            "",
            f"- Schema: `{manifest['schema']}`",
            f"- Mode: `{manifest['mode']}`",
            f"- Generated At: `{manifest['generated_at']}`",
            "- Canonical memory remains `wiki/**/*.md`.",
            "- Raw sources are excluded from snapshot mode by default.",
            "- `server-config.json` currently declares a contract-only stdio target; executable adapters are follow-up work.",
            "",
        ]
    )


def publish_mcp_bundle(root: Path, *, mode: str = "linked", clean: bool = False) -> dict[str, Any]:
    if mode not in {"linked", "snapshot"}:
        raise ValueError("mode must be linked or snapshot")
    root = root.resolve()
    out = root / BUNDLE_DIR
    if clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    html_manifest = publish_html(root, clean=False)
    expected_index, expected_graph = build_memory_artifacts(root)
    pages = [page for page in expected_index.get("pages", []) if isinstance(page, dict)]
    if mode == "snapshot":
        build_snapshot(root, out, expected_index, expected_graph)

    generated_at = utc_now()
    resources = resources_contract(root, pages, mode=mode)
    tools = tools_contract()
    prompts = prompts_contract()
    quality = quality_report(root, expected_index, expected_graph)
    config = server_config(mode)

    write_json(out / "resources.json", resources)
    write_json(out / "tools.json", tools)
    write_json(out / "prompts.json", prompts)
    write_json(out / "quality.json", quality)
    write_json(out / "server-config.json", config)

    manifest = {
        "schema": BUNDLE_SCHEMA,
        "generated_at": generated_at,
        "mode": mode,
        "root": root.as_posix(),
        "canonical_source": "wiki/**/*.md",
        "source_policy": {
            "markdown_is_canonical": True,
            "mcp_artifacts_are_generated": True,
            "raw_sources_excluded_by_default": True,
            "read_only": True,
        },
        "resources": "resources.json",
        "tools": "tools.json",
        "prompts": "prompts.json",
        "quality": "quality.json",
        "server_config": "server-config.json",
        "html_manifest": html_manifest,
        "pages": [{"path": page["path"], "title": page.get("title", ""), "slug": page.get("slug", "")} for page in pages],
        "source_hashes": source_records(root, pages),
    }
    write_json(out / "manifest.json", manifest)
    (out / "README.md").write_text(readme_text(manifest), encoding="utf-8")

    contract_errors = validate_contract(root, out, [resources, tools, prompts, quality, config])
    manifest["contract_status"] = "fail" if contract_errors else "pass"
    manifest["contract_errors"] = contract_errors
    write_json(out / "manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument("--mode", choices=["linked", "snapshot"], default="linked", help="Publication mode")
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
