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
    core_direction_complete,
    file_body_hash,
    is_external_target,
    is_local_reference,
    is_profile_enabled,
    iter_wiki_pages,
    iter_glossary_entries,
    load_glossary,
    load_profiles,
    load_json,
    normalize_list,
    page_headings,
    parse_frontmatter,
    read_jsonl,
    relpath,
    write_report,
    validate_delivery_contract_data,
)


def local_markdown_targets(body: str, page_path: Path, root: Path) -> list[tuple[str, Path]]:
    targets: list[tuple[str, Path]] = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", body):
        target = match.group(1).split("#", 1)[0].strip()
        if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        targets.append((target, (page_path.parent / target).resolve()))
    return targets


def required_sections_for_page(metadata: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> set[str]:
    sections: set[str] = set()
    page_type = str(metadata.get("type") or "")
    for profile_id in normalize_list(metadata.get("profiles")):
        profile = profiles.get(profile_id)
        if not profile:
            continue
        required = profile.get("required_sections_by_type")
        if isinstance(required, dict):
            sections.update(normalize_list(required.get(page_type)))
    return sections


def validate_page(
    path: Path,
    root: Path,
    profiles: dict[str, dict[str, Any]],
    profile_enabled: bool,
) -> tuple[list[str], list[str]]:
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
    if "profiles" in metadata and not isinstance(metadata["profiles"], list):
        errors.append(f"{page}: profiles must be a list")
    page_profiles = normalize_list(metadata.get("profiles"))
    if page_profiles:
        for profile_id in page_profiles:
            if profile_id not in profiles:
                warnings.append(f"{page}: unknown profile reference: {profile_id}")
    elif profile_enabled:
        warnings.append(f"{page}: page is unprofiled in a profile-enabled wiki")

    for source in normalize_list(metadata.get("sources")):
        if is_local_reference(source) and not (root / source).exists():
            warnings.append(f"{page}: source path does not exist: {source}")

    for raw_target, resolved in local_markdown_targets(body, path, root):
        if not resolved.exists():
            warnings.append(f"{page}: broken local markdown link {raw_target}")

    headings = {heading.strip().lower() for heading in page_headings(body)}
    for required_section in sorted(required_sections_for_page(metadata, profiles)):
        if required_section.strip().lower() not in headings:
            warnings.append(f"{page}: missing required profile section: {required_section}")
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
        expected_hashes: dict[str, str] = {}
        for hash_field in ("sha256", "source_hash"):
            expected_hash = metadata.get(hash_field)
            if expected_hash in (None, ""):
                continue
            if not isinstance(expected_hash, str):
                warnings.append(f"{rel}: {hash_field} should be a string")
                continue
            expected_hashes[hash_field] = expected_hash
        if not expected_hashes:
            continue
        if len(set(expected_hashes.values())) > 1:
            warnings.append(f"{rel}: sha256 and source_hash disagree")
        actual_hash, hash_error = file_body_hash(path)
        if hash_error:
            errors.append(f"{rel}: cannot compute source hash: {hash_error}")
        else:
            for hash_field, expected_hash in expected_hashes.items():
                if actual_hash != expected_hash:
                    warnings.append(f"{rel}: {hash_field} mismatch")
    return errors, warnings


def validate_eval_cases(root: Path, profiles: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    cases, jsonl_errors = read_jsonl(root / "retrieval-evals.jsonl")
    errors.extend(jsonl_errors)
    seen_ids: set[str] = set()
    for index, case in enumerate(cases, start=1):
        case_id = case.get("id")
        query = case.get("query")
        expected = case.get("expected_pages")
        expect_miss = case.get("expect_miss", False)
        label = case_id or f"line {index}"
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"retrieval-evals.jsonl {label}: id is required")
        elif case_id in seen_ids:
            errors.append(f"retrieval-evals.jsonl {label}: duplicate id")
        else:
            seen_ids.add(case_id)
        if not isinstance(query, str) or not query.strip():
            errors.append(f"retrieval-evals.jsonl {label}: query is required")
        if "expect_miss" in case and not isinstance(expect_miss, bool):
            errors.append(f"retrieval-evals.jsonl {label}: expect_miss must be boolean")
        if expect_miss is True:
            if expected is not None and not isinstance(expected, list):
                errors.append(f"retrieval-evals.jsonl {label}: expected_pages must be a list when present")
            elif expected:
                errors.append(f"retrieval-evals.jsonl {label}: expected_pages must be omitted or empty when expect_miss is true")
        elif not isinstance(expected, list) or not expected:
            errors.append(f"retrieval-evals.jsonl {label}: expected_pages must be a non-empty list")
        profile_id = case.get("profile_id")
        if profile_id is not None and (not isinstance(profile_id, str) or not profile_id):
            warnings.append(f"retrieval-evals.jsonl {label}: profile_id should be a non-empty string")
        elif profile_id and profile_id not in profiles:
            warnings.append(f"retrieval-evals.jsonl {label}: unknown profile_id: {profile_id}")
        for optional in ("forbidden_pages", "tags"):
            if optional in case and not isinstance(case[optional], list):
                warnings.append(f"retrieval-evals.jsonl {label}: {optional} should be a list")
        for optional in ("require_seed_hit", "allow_forbidden_context"):
            if optional in case and not isinstance(case[optional], bool):
                errors.append(f"retrieval-evals.jsonl {label}: {optional} must be boolean")
        if "min_score" in case and not isinstance(case["min_score"], (int, float)):
            errors.append(f"retrieval-evals.jsonl {label}: min_score must be numeric")
    return errors, warnings


def validate_query_log(root: Path, profiles: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
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
        profile_id = entry.get("profile_id")
        if profile_id is not None and (not isinstance(profile_id, str) or not profile_id):
            warnings.append(f"query-log.jsonl line {index}: profile_id should be a non-empty string")
        elif profile_id and profile_id not in profiles:
            warnings.append(f"query-log.jsonl line {index}: unknown profile_id: {profile_id}")
    return errors, warnings


def validate_profile_state(root: Path, profiles: dict[str, dict[str, Any]], profile_errors: list[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    errors.extend(profile_errors)
    if not (root / "profiles").exists():
        warnings.append("profiles/ is missing; normal profile-enabled wikis should include profiles/")
    if not core_direction_complete(root):
        warnings.append("SCHEMA.md lacks a complete Wiki Core Direction")
    for profile_id, profile in profiles.items():
        retrieval = profile.get("retrieval")
        if retrieval is None:
            continue
        if not isinstance(retrieval, dict):
            warnings.append(f"profiles/{profile_id}.json: retrieval must be an object when present")
            continue
        for field in ("min_seed_score", "min_recall_at_k", "min_mrr_at_k"):
            if field in retrieval and not isinstance(retrieval[field], (int, float)):
                warnings.append(f"profiles/{profile_id}.json: retrieval.{field} must be numeric")
        if isinstance(retrieval.get("min_seed_score"), (int, float)) and float(retrieval["min_seed_score"]) < 0:
            warnings.append(f"profiles/{profile_id}.json: retrieval.min_seed_score must be non-negative")
        for field in ("min_recall_at_k", "min_mrr_at_k"):
            if isinstance(retrieval.get(field), (int, float)) and not 0 <= float(retrieval[field]) <= 1:
                warnings.append(f"profiles/{profile_id}.json: retrieval.{field} must be between 0 and 1")
        if "allow_glossary_expansion" in retrieval and not isinstance(retrieval["allow_glossary_expansion"], bool):
            warnings.append(f"profiles/{profile_id}.json: retrieval.allow_glossary_expansion must be boolean")
    return errors, warnings


def validate_glossary(root: Path) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    _, entry_errors = iter_glossary_entries(root)
    _, glossary_errors = load_glossary(root)
    seen: set[str] = set()
    for error in [*entry_errors, *glossary_errors]:
        if error not in seen:
            warnings.append(error)
            seen.add(error)
    return [], warnings


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
        try:
            expected_index, expected_graph = build_memory_artifacts(root)
        except ValueError as exc:
            errors.append(str(exc))
            return errors, warnings
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


def validate_delivery_contract(root: Path) -> tuple[list[str], list[str]]:
    path = root / "delivery-contract.json"
    if not path.exists():
        return [], ["delivery-contract.json is missing; confirm the final publication form before release"]
    data, error = load_json(path, {})
    if error:
        return [f"delivery-contract.json invalid JSON: {error}"], []
    return [f"delivery-contract.json: {item}" for item in validate_delivery_contract_data(data)], []


def validate_wiki(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    profiles, profile_errors = load_profiles(root)
    profile_enabled = is_profile_enabled(root)

    for rel in REQUIRED_FILES:
        if not (root / rel).exists():
            errors.append(f"missing required file: {rel}")
    for rel in REQUIRED_DIRS:
        if not (root / rel).exists():
            errors.append(f"missing required directory: {rel}/")

    try:
        page_paths = iter_wiki_pages(root)
    except ValueError as exc:
        errors.append(str(exc))
        page_paths = []
    for page in page_paths:
        page_errors, page_warnings = validate_page(page, root, profiles, profile_enabled)
        errors.extend(page_errors)
        warnings.extend(page_warnings)

    if (root / "index.md").exists():
        index_text = (root / "index.md").read_text(encoding="utf-8")
        for page in page_paths:
            page_rel = relpath(page, root)
            if page_rel not in index_text and page.name not in index_text:
                warnings.append(f"index.md does not mention {page_rel}")

    json_errors, json_warnings = validate_json_artifacts(root)
    profile_state_errors, profile_state_warnings = validate_profile_state(root, profiles, profile_errors)
    eval_errors, eval_warnings = validate_eval_cases(root, profiles)
    query_errors, query_warnings = validate_query_log(root, profiles)
    provenance_errors, provenance_warnings = validate_source_provenance(root)
    glossary_errors, glossary_warnings = validate_glossary(root)
    delivery_errors, delivery_warnings = validate_delivery_contract(root)
    errors.extend(
        json_errors
        + profile_state_errors
        + eval_errors
        + query_errors
        + provenance_errors
        + glossary_errors
        + delivery_errors
    )
    warnings.extend(
        json_warnings
        + profile_state_warnings
        + eval_warnings
        + query_warnings
        + provenance_warnings
        + glossary_warnings
        + delivery_warnings
    )

    return {
        "root": root.as_posix(),
        "pages": len(page_paths),
        "profiles": sorted(profiles),
        "profile_enabled": profile_enabled,
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
