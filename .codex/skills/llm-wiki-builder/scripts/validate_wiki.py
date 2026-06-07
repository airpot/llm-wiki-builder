#!/usr/bin/env python3
"""Validate a file-first Markdown LLM wiki."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from wiki_lib import (
    CONFIDENCE_VALUES,
    PAGE_TYPES,
    REQUIRED_DIRS,
    REQUIRED_FILES,
    REQUIRED_FRONTMATTER,
    artifact_matches,
    build_memory_artifacts,
    file_body_hash,
    is_external_target,
    is_local_reference,
    iter_wiki_pages,
    load_json,
    normalize_list,
    parse_frontmatter,
    read_jsonl,
    relpath,
    write_report,
)


def local_markdown_targets(body: str, page_path: Path, root: Path) -> list[tuple[str, Path]]:
    targets: list[tuple[str, Path]] = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", body):
        target = match.group(1).split("#", 1)[0].strip()
        if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        targets.append((target, (page_path.parent / target).resolve()))
    return targets


def validate_page(path: Path, root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    text = path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(text)
    page = relpath(path, root)
    if not metadata:
        errors.append(f"{page}: missing frontmatter")
        return errors, warnings

    for field in REQUIRED_FRONTMATTER:
        if field not in metadata:
            errors.append(f"{page}: missing frontmatter field {field}")
    page_type = metadata.get("type")
    if page_type is not None and page_type not in PAGE_TYPES:
        errors.append(f"{page}: invalid type {page_type!r}")
    confidence = metadata.get("confidence")
    if confidence is not None and confidence not in CONFIDENCE_VALUES:
        errors.append(f"{page}: invalid confidence {confidence!r}")
    if "contested" in metadata and not isinstance(metadata["contested"], bool):
        errors.append(f"{page}: contested must be boolean")
    for list_field in ("aliases", "tags", "sources"):
        if list_field in metadata and not isinstance(metadata[list_field], list):
            warnings.append(f"{page}: {list_field} should be a list")

    for source in normalize_list(metadata.get("sources")):
        if is_local_reference(source) and not (root / source).exists():
            warnings.append(f"{page}: source path does not exist: {source}")

    for raw_target, resolved in local_markdown_targets(body, path, root):
        if not resolved.exists():
            warnings.append(f"{page}: broken local markdown link {raw_target}")
    return errors, warnings


def iter_raw_source_files(root: Path) -> list[Path]:
    raw = root / "raw"
    if not raw.exists():
        return []
    return sorted(path for path in raw.rglob("*.md") if path.is_file())


def validate_source_provenance(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for path in iter_raw_source_files(root):
        rel = relpath(path, root)
        text = path.read_text(encoding="utf-8")
        metadata, _ = parse_frontmatter(text)
        source_path = metadata.get("source_path")
        if isinstance(source_path, str) and source_path and not is_external_target(source_path):
            candidate = root / source_path
            if not candidate.exists():
                warnings.append(f"{rel}: source_path does not exist: {source_path}")
        expected_hash = metadata.get("sha256") or metadata.get("source_hash")
        if expected_hash in (None, ""):
            continue
        if not isinstance(expected_hash, str):
            warnings.append(f"{rel}: source hash should be a string")
            continue
        actual_hash, hash_error = file_body_hash(path)
        if hash_error:
            errors.append(f"{rel}: cannot compute source hash: {hash_error}")
        elif actual_hash != expected_hash:
            warnings.append(f"{rel}: source hash mismatch")
    return errors, warnings


def validate_eval_cases(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    cases, jsonl_errors = read_jsonl(root / "retrieval-evals.jsonl")
    errors.extend(jsonl_errors)
    seen_ids: set[str] = set()
    for index, case in enumerate(cases, start=1):
        case_id = case.get("id")
        query = case.get("query")
        expected = case.get("expected_pages")
        label = case_id or f"line {index}"
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"retrieval-evals.jsonl {label}: id is required")
        elif case_id in seen_ids:
            errors.append(f"retrieval-evals.jsonl {label}: duplicate id")
        else:
            seen_ids.add(case_id)
        if not isinstance(query, str) or not query.strip():
            errors.append(f"retrieval-evals.jsonl {label}: query is required")
        if not isinstance(expected, list) or not expected:
            errors.append(f"retrieval-evals.jsonl {label}: expected_pages must be a non-empty list")
        for optional in ("forbidden_pages", "tags"):
            if optional in case and not isinstance(case[optional], list):
                warnings.append(f"retrieval-evals.jsonl {label}: {optional} should be a list")
    return errors, warnings


def validate_query_log(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    entries, jsonl_errors = read_jsonl(root / "query-log.jsonl")
    errors.extend(jsonl_errors)
    for index, entry in enumerate(entries, start=1):
        for field in ("timestamp", "query", "selected_pages", "miss", "retrieval_mode"):
            if field not in entry:
                warnings.append(f"query-log.jsonl line {index}: missing {field}")
        if "selected_pages" in entry and not isinstance(entry["selected_pages"], list):
            errors.append(f"query-log.jsonl line {index}: selected_pages must be a list")
        if "miss" in entry and not isinstance(entry["miss"], bool):
            errors.append(f"query-log.jsonl line {index}: miss must be boolean")
    return errors, warnings


def validate_json_artifacts(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    memory_index, memory_error = load_json(root / "memory-index.json", {})
    link_graph, graph_error = load_json(root / "link-graph.json", {})
    if memory_error:
        errors.append(f"memory-index.json invalid JSON: {memory_error}")
    if graph_error:
        errors.append(f"link-graph.json invalid JSON: {graph_error}")
    if not memory_error and (not isinstance(memory_index, dict) or not isinstance(memory_index.get("pages"), list)):
        errors.append("memory-index.json must be an object with pages list")
    if not graph_error and (not isinstance(link_graph, dict) or not isinstance(link_graph.get("links"), list)):
        errors.append("link-graph.json must be an object with links list")
    if not errors:
        expected_index, expected_graph = build_memory_artifacts(root)
        current_paths = sorted(page.get("path") for page in memory_index.get("pages", []) if isinstance(page, dict))
        expected_paths = sorted(page.get("path") for page in expected_index.get("pages", []))
        if current_paths != expected_paths:
            warnings.append("memory-index.json page set is stale; run build_memory_index.py --write")
        elif not artifact_matches(memory_index, expected_index):
            warnings.append("memory-index.json content is stale; run build_memory_index.py --write")
        current_nodes = sorted(link_graph.get("nodes", []))
        expected_nodes = sorted(expected_graph.get("nodes", []))
        if current_nodes != expected_nodes:
            warnings.append("link-graph.json nodes are stale; run build_memory_index.py --write")
        elif not artifact_matches(link_graph, expected_graph):
            warnings.append("link-graph.json content is stale; run build_memory_index.py --write")
    return errors, warnings


def validate_wiki(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    for rel in REQUIRED_FILES:
        if not (root / rel).exists():
            errors.append(f"missing required file: {rel}")
    for rel in REQUIRED_DIRS:
        if not (root / rel).exists():
            errors.append(f"missing required directory: {rel}/")

    page_paths = iter_wiki_pages(root)
    for page in page_paths:
        page_errors, page_warnings = validate_page(page, root)
        errors.extend(page_errors)
        warnings.extend(page_warnings)

    if (root / "index.md").exists():
        index_text = (root / "index.md").read_text(encoding="utf-8")
        for page in page_paths:
            page_rel = relpath(page, root)
            if page_rel not in index_text and page.name not in index_text:
                warnings.append(f"index.md does not mention {page_rel}")

    json_errors, json_warnings = validate_json_artifacts(root)
    eval_errors, eval_warnings = validate_eval_cases(root)
    query_errors, query_warnings = validate_query_log(root)
    provenance_errors, provenance_warnings = validate_source_provenance(root)
    errors.extend(json_errors + eval_errors + query_errors + provenance_errors)
    warnings.extend(json_warnings + eval_warnings + query_warnings + provenance_warnings)

    return {
        "root": root.as_posix(),
        "pages": len(page_paths),
        "errors": errors,
        "warnings": warnings,
        "status": "fail" if errors else "pass",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    parser.add_argument("--report", action="store_true", help="Write a validation report under reports/validation")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.wiki_root)
    result = validate_wiki(root)
    exit_code = 1 if result["errors"] or (args.strict and result["warnings"]) else 0

    if args.report:
        markdown = ["# Wiki Validation Report", "", f"- Status: {result['status']}", f"- Pages: {result['pages']}", ""]
        markdown.append("## Errors")
        markdown.extend(f"- {item}" for item in result["errors"] or ["None"])
        markdown.append("")
        markdown.append("## Warnings")
        markdown.extend(f"- {item}" for item in result["warnings"] or ["None"])
        md_path, json_path = write_report(root, "validation", "validation", "\n".join(markdown), result)
        result["report"] = md_path.as_posix()
        if json_path:
            result["report_json"] = json_path.as_posix()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        print(f"pages: {result['pages']}")
        print(f"errors: {len(result['errors'])}")
        for item in result["errors"]:
            print(f"  error: {item}")
        print(f"warnings: {len(result['warnings'])}")
        for item in result["warnings"]:
            print(f"  warning: {item}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
