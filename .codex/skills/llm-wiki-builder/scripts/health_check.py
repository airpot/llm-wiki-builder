#!/usr/bin/env python3
"""Run zero-LLM structural health checks for a Markdown LLM wiki."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from wiki_lib import (
    MARKDOWN_LINK_RE,
    build_memory_artifacts,
    has_mixed_scripts,
    iter_wiki_pages,
    load_glossary,
    load_profiles,
    normalize_list,
    page_headings,
    parse_frontmatter,
    read_jsonl,
    relpath,
    resolve_wiki_link,
    tokenize,
    wiki_link_targets,
    write_report,
)


PAGE_SIZE_WARNING_LINES = 200
STUB_BODY_CHARS = 100


def finding(severity: str, check: str, path: str, message: str) -> dict[str, str]:
    return {"severity": severity, "check": check, "path": path, "message": message}


def markdown_targets(body: str, page_path: Path, root: Path) -> list[tuple[str, Path]]:
    targets: list[tuple[str, Path]] = []
    for match in MARKDOWN_LINK_RE.finditer(body):
        target = match.group(1).split("#", 1)[0].strip()
        if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        targets.append((target, (page_path.parent / target).resolve()))
    return targets


def taxonomy_tags(root: Path) -> set[str] | None:
    schema = root / "SCHEMA.md"
    if not schema.exists():
        return None
    text = schema.read_text(encoding="utf-8")
    match = re.search(r"^##\s+Tag Taxonomy\s*$", text, flags=re.MULTILINE)
    if not match:
        return None
    tail = text[match.end() :]
    next_section = re.search(r"^##\s+", tail, flags=re.MULTILINE)
    section = tail[: next_section.start()] if next_section else tail
    tags: set[str] = set()
    for raw in section.splitlines():
        line = raw.strip()
        if not line or not line.startswith(("-", "*")):
            continue
        line = line.lstrip("-* ").strip()
        if not line:
            continue
        code_tags = re.findall(r"`([^`]+)`", line)
        if code_tags:
            tags.update(tag.strip() for tag in code_tags if tag.strip())
            continue
        head = re.split(r"[:—-]", line, maxsplit=1)[0]
        for part in re.split(r"[,/|]", head):
            tag = part.strip()
            if tag:
                tags.add(tag)
    return tags


def check_health(root: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    pages = [path for path in iter_wiki_pages(root)]
    memory_index, link_graph = build_memory_artifacts(root)
    index_pages = [page for page in memory_index.get("pages", []) if isinstance(page, dict)]
    profiles, profile_errors = load_profiles(root)
    glossary, glossary_errors = load_glossary(root)
    profile_page_counts = {profile_id: 0 for profile_id in profiles}
    eval_profile_counts = {profile_id: 0 for profile_id in profiles}
    tags_allowed = taxonomy_tags(root)
    index_text = (root / "index.md").read_text(encoding="utf-8") if (root / "index.md").exists() else ""
    log_text = (root / "log.md").read_text(encoding="utf-8") if (root / "log.md").exists() else ""

    for error in profile_errors:
        findings.append(finding("error", "profile-validation", "profiles/", error))
    for error in glossary_errors:
        findings.append(finding("warning", "glossary-validation", "glossary", error))

    for page_path in pages:
        page_rel = relpath(page_path, root)
        text = page_path.read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(text)
        page_profiles = normalize_list(metadata.get("profiles"))
        if profiles and not page_profiles:
            findings.append(finding("warning", "profile-coverage", page_rel, "page has no profiles"))
        for profile_id in page_profiles:
            if profile_id in profile_page_counts:
                profile_page_counts[profile_id] += 1

        headings = {heading.strip().lower() for heading in page_headings(body)}
        for profile_id in page_profiles:
            profile = profiles.get(profile_id)
            required = profile.get("required_sections_by_type") if profile else None
            if isinstance(required, dict):
                for section in normalize_list(required.get(str(metadata.get("type") or ""))):
                    if section.strip().lower() not in headings:
                        findings.append(
                            finding("warning", "profile-required-section", page_rel, f"missing section: {section}")
                        )

        body_chars = len(body.strip())
        if body_chars < STUB_BODY_CHARS:
            findings.append(finding("warning", "stub-page", page_rel, "page body is shorter than 100 characters"))
        line_count = len(text.splitlines())
        if line_count > PAGE_SIZE_WARNING_LINES:
            findings.append(
                finding("info", "page-size", page_rel, f"page has {line_count} lines; consider split planning")
            )

        for raw_target, resolved in markdown_targets(body, page_path, root):
            if not resolved.exists():
                findings.append(finding("error", "broken-markdown-link", page_rel, f"broken link: {raw_target}"))

        for target in wiki_link_targets(body):
            if resolve_wiki_link(target, index_pages) is None:
                findings.append(finding("error", "broken-wikilink", page_rel, f"broken wikilink: {target}"))

        if index_text and page_rel not in index_text and page_path.name not in index_text:
            findings.append(finding("warning", "index-completeness", page_rel, "page is not mentioned in index.md"))

        title = str(metadata.get("title", ""))
        if log_text and page_rel not in log_text and title and title not in log_text:
            findings.append(finding("info", "log-coverage", page_rel, "page has no obvious log.md coverage"))

        if tags_allowed:
            for tag in normalize_list(metadata.get("tags")):
                if tag not in tags_allowed:
                    findings.append(finding("warning", "tag-taxonomy", page_rel, f"tag is not in taxonomy: {tag}"))

    for orphan in link_graph.get("orphans", []):
        if len(index_pages) > 1:
            findings.append(finding("warning", "orphan-page", str(orphan), "page has no incoming or outgoing wiki links"))

    eval_cases, eval_errors = read_jsonl(root / "retrieval-evals.jsonl")
    for error in eval_errors:
        findings.append(finding("error", "retrieval-eval-jsonl", "retrieval-evals.jsonl", error))
    for case in eval_cases:
        profile_id = case.get("profile_id")
        if profile_id in eval_profile_counts:
            eval_profile_counts[profile_id] += 1
    mixed_eval_cases = [
        case
        for case in eval_cases
        if has_mixed_scripts(str(case.get("query") or ""))
        or "mixed-language" in {str(tag) for tag in normalize_list(case.get("tags"))}
    ]

    query_entries, query_errors = read_jsonl(root / "query-log.jsonl")
    for error in query_errors:
        findings.append(finding("error", "query-log-jsonl", "query-log.jsonl", error))
    profile_misses: dict[str, int] = {profile_id: 0 for profile_id in profiles}
    for entry in query_entries:
        profile_id = entry.get("profile_id")
        if profile_id in profile_misses and entry.get("miss") is True:
            profile_misses[profile_id] += 1
        if entry.get("miss") is True and has_mixed_scripts(str(entry.get("query") or "")):
            findings.append(
                finding(
                    "info",
                    "mixed-language-query-miss",
                    "query-log.jsonl",
                    f"mixed-language miss may need aliases or glossary terms: {entry.get('query')}",
                )
            )

    for profile_id, count in profile_page_counts.items():
        if count == 0:
            findings.append(finding("warning", "profile-coverage", f"profiles/{profile_id}.json", "profile has no pages"))
    for profile_id, count in eval_profile_counts.items():
        if count == 0:
            findings.append(
                finding("info", "profile-eval-coverage", f"profiles/{profile_id}.json", "profile has no eval cases")
            )
    for profile_id, count in profile_misses.items():
        if count:
            findings.append(
                finding("warning", "profile-query-miss", f"profiles/{profile_id}.json", f"profile has {count} query misses")
            )
    if glossary and not mixed_eval_cases:
        findings.append(
            finding(
                "info",
                "mixed-language-eval-coverage",
                "retrieval-evals.jsonl",
                "glossary exists but no mixed-language retrieval eval cases were found",
            )
        )

    counts: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
    for item in findings:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
    status = "fail" if counts.get("error", 0) else "pass"
    return {
        "schema": "llm-wiki-health-report-v1",
        "root": root.as_posix(),
        "status": status,
        "pages": len(pages),
        "profiles": sorted(profiles),
        "findings": findings,
        "counts": counts,
    }


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Wiki Health Report",
        "",
        f"- Status: {result['status']}",
        f"- Pages: {result['pages']}",
        f"- Errors: {result['counts'].get('error', 0)}",
        f"- Warnings: {result['counts'].get('warning', 0)}",
        f"- Info: {result['counts'].get('info', 0)}",
        "",
        "## Findings",
    ]
    findings = result.get("findings", [])
    if not findings:
        lines.append("- None")
    else:
        for item in findings:
            lines.append(f"- [{item['severity']}] {item['check']} {item['path']}: {item['message']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    parser.add_argument("--report", action="store_true", help="Write a health report under reports/health")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.wiki_root)
    result = check_health(root)
    if args.report:
        md_path, json_path = write_report(root, "health", "health", markdown_report(result), result)
        result["report"] = md_path.as_posix()
        if json_path:
            result["report_json"] = json_path.as_posix()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        print(f"pages: {result['pages']}")
        print(f"errors: {result['counts'].get('error', 0)}")
        print(f"warnings: {result['counts'].get('warning', 0)}")
        print(f"info: {result['counts'].get('info', 0)}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
