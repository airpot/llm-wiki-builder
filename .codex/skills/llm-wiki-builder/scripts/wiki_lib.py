#!/usr/bin/env python3
"""Shared helpers for llm-wiki-builder scripts."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True


REQUIRED_FILES = [
    "SCHEMA.md",
    "index.md",
    "log.md",
    "memory-index.json",
    "link-graph.json",
    "query-log.jsonl",
    "retrieval-evals.jsonl",
]

REQUIRED_DIRS = [
    "raw/articles",
    "raw/papers",
    "raw/transcripts",
    "raw/snippets",
    "wiki/concepts",
    "wiki/entities",
    "wiki/comparisons",
    "wiki/queries",
    "reports/validation",
    "reports/health",
    "reports/optimization",
    "reports/retrieval",
]

PROFILE_DIR = "profiles"
PROFILE_SCHEMA = "llm-wiki-extraction-profile-v1"
CORE_DIRECTION_FIELDS = [
    "purpose",
    "primary_users",
    "core_knowledge_targets",
    "out_of_scope",
    "landing_granularity",
    "evidence_policy",
    "conflict_policy",
    "success_queries",
]
CORE_DIRECTION_LABELS = {
    "purpose": "Purpose",
    "primary_users": "Primary Users",
    "core_knowledge_targets": "Core Knowledge Targets",
    "out_of_scope": "Out Of Scope",
    "landing_granularity": "Landing Granularity",
    "evidence_policy": "Evidence Policy",
    "conflict_policy": "Conflict Policy",
    "success_queries": "Success Queries",
}
PROFILE_REQUIRED_FIELDS = [
    "schema",
    "profile_id",
    "purpose",
    "target_audience",
    "extract_dimensions",
    "exclude_dimensions",
    "page_types",
    "granularity",
    "evidence_policy",
    "conflict_policy",
    "output_roots",
]
PROFILE_LIST_FIELDS = {
    "target_audience",
    "extract_dimensions",
    "exclude_dimensions",
    "page_types",
    "output_roots",
}
PLACEHOLDER_VALUES = {
    "",
    "...",
    "fill in",
    "n/a",
    "placeholder",
    "tbd",
    "to be decided",
    "to be filled",
    "todo",
    "unspecified",
}

REQUIRED_FRONTMATTER = [
    "title",
    "slug",
    "created",
    "updated",
    "type",
    "summary",
    "aliases",
    "tags",
    "sources",
    "confidence",
    "contested",
]

PAGE_TYPES = {"concept", "entity", "comparison", "query", "note", "source-summary"}
CONFIDENCE_VALUES = {"high", "medium", "low", "unknown"}
RETRIEVAL_MODE = "deterministic-file-first"

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
CJK_RANGES = (
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xAC00, 0xD7AF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF),
    (0x30000, 0x3134F),
    (0x31350, 0x323AF),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "untitled"


def relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def load_json(path: Path, default: Any) -> tuple[Any, str | None]:
    if not path.exists():
        return default, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return default, str(exc)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")


def stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def append_log(root: Path, message: str) -> None:
    log_path = root / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "" if log_path.exists() and log_path.read_text(encoding="utf-8").endswith("\n") else "\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{prefix}- {utc_now()} {message}\n")


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value == "[]":
        return []
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value.replace("'", '"'))
            return parsed if isinstance(parsed, list) else value
        except json.JSONDecodeError:
            inner = value[1:-1].strip()
            return [part.strip().strip("\"'") for part in inner.split(",") if part.strip()]
    return value.strip("\"'")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    metadata: dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.strip() or line.startswith(" "):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = parse_scalar(value)
    return metadata, body


def source_body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_body_hash(path: Path) -> tuple[str | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, str(exc)
    _, body = parse_frontmatter(text)
    return source_body_hash(body), None


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value in (None, ""):
        return []
    return [str(value)]


def is_placeholder_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in PLACEHOLDER_VALUES
    if isinstance(value, list):
        return not value or any(is_placeholder_value(item) for item in value)
    return value in (None, "")


def safe_profile_id(value: Any) -> str:
    return str(value or "").strip()


def profile_filename(profile_id: str) -> str:
    return f"{profile_id}.json"


def validate_core_direction_data(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["core direction must be a JSON object"]
    for field in CORE_DIRECTION_FIELDS:
        value = data.get(field)
        if field in {"purpose", "landing_granularity", "evidence_policy", "conflict_policy"}:
            if not isinstance(value, str) or is_placeholder_value(value):
                errors.append(f"core direction {field} must be a non-empty string")
        else:
            if not isinstance(value, list) or is_placeholder_value(value):
                errors.append(f"core direction {field} must be a non-empty list")
    return errors


def render_core_direction(data: dict[str, Any] | None, draft: bool = False) -> str:
    if draft or not data:
        return "\n".join(
            [
                "Status:",
                "- draft",
                "",
                "Purpose:",
                "- unspecified",
                "",
                "Primary Users:",
                "- unspecified",
                "",
                "Core Knowledge Targets:",
                "- unspecified",
                "",
                "Out Of Scope:",
                "- unspecified",
                "",
                "Landing Granularity:",
                "- unspecified",
                "",
                "Evidence Policy:",
                "- unspecified",
                "",
                "Conflict Policy:",
                "- unspecified",
                "",
                "Success Queries:",
                "- unspecified",
            ]
        )

    lines: list[str] = []
    for field in CORE_DIRECTION_FIELDS:
        if lines:
            lines.append("")
        lines.append(f"{CORE_DIRECTION_LABELS[field]}:")
        value = data.get(field)
        items = normalize_list(value)
        for item in items:
            lines.append(f"- {item}")
    return "\n".join(lines)


def extract_markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", flags=re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    tail = text[match.end() :]
    next_section = re.search(r"^##\s+", tail, flags=re.MULTILINE)
    return tail[: next_section.start()] if next_section else tail


def core_direction_complete(root: Path) -> bool:
    schema = root / "SCHEMA.md"
    if not schema.exists():
        return False
    section = extract_markdown_section(schema.read_text(encoding="utf-8"), "Wiki Core Direction")
    if not section.strip():
        return False
    lowered = section.lower()
    if "status:" in lowered and "draft" in lowered:
        return False
    required_labels = [CORE_DIRECTION_LABELS[field] + ":" for field in CORE_DIRECTION_FIELDS]
    for label in required_labels:
        label_match = re.search(rf"^{re.escape(label)}\s*$", section, flags=re.MULTILINE)
        if not label_match:
            return False
        tail = section[label_match.end() :]
        next_label = re.search(r"^[A-Z][A-Za-z ]+:\s*$", tail, flags=re.MULTILINE)
        block = tail[: next_label.start()] if next_label else tail
        bullets = [line.strip()[1:].strip() for line in block.splitlines() if line.strip().startswith("-")]
        if not bullets or any(is_placeholder_value(item) or item.lower() == "unspecified" for item in bullets):
            return False
    return True


def iter_profile_files(root: Path) -> list[Path]:
    profiles = root / PROFILE_DIR
    if not profiles.exists():
        return []
    return sorted(path for path in profiles.glob("*.json") if path.is_file())


def validate_profile_data(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["profile must be a JSON object"]
    for field in PROFILE_REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing required profile field {field}")
            continue
        value = data.get(field)
        if field in PROFILE_LIST_FIELDS:
            if not isinstance(value, list) or is_placeholder_value(value):
                errors.append(f"profile field {field} must be a non-empty list")
        elif not isinstance(value, str) or is_placeholder_value(value):
            errors.append(f"profile field {field} must be a non-empty string")
    if data.get("schema") and data.get("schema") != PROFILE_SCHEMA:
        errors.append(f"profile schema must be {PROFILE_SCHEMA}")
    profile_id = safe_profile_id(data.get("profile_id"))
    if profile_id and not PROFILE_ID_RE.match(profile_id):
        errors.append("profile_id must use letters, numbers, underscores, or hyphens and start with a letter or number")
    for page_type in normalize_list(data.get("page_types")):
        if page_type not in PAGE_TYPES:
            errors.append(f"invalid profile page type {page_type!r}")
    for output_root in normalize_list(data.get("output_roots")):
        candidate = Path(output_root)
        if candidate.is_absolute() or ".." in candidate.parts or output_root == "wiki" or not output_root.startswith("wiki/"):
            errors.append(f"output root must stay under wiki/: {output_root}")
    sections = data.get("required_sections_by_type")
    if sections is not None:
        if not isinstance(sections, dict):
            errors.append("required_sections_by_type must be an object when present")
        else:
            for page_type, section_names in sections.items():
                if page_type not in PAGE_TYPES:
                    errors.append(f"required_sections_by_type has invalid page type {page_type!r}")
                if not isinstance(section_names, list):
                    errors.append(f"required_sections_by_type[{page_type}] must be a list")
    return errors


def load_profiles(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    profiles: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in iter_profile_files(root):
        rel = relpath(path, root)
        data, error = load_json(path, {})
        if error:
            errors.append(f"{rel}: invalid JSON: {error}")
            continue
        profile_errors = validate_profile_data(data)
        if profile_errors:
            errors.extend(f"{rel}: {item}" for item in profile_errors)
            continue
        profile_id = safe_profile_id(data.get("profile_id"))
        if profile_id in profiles:
            errors.append(f"{rel}: duplicate profile_id {profile_id}")
            continue
        profiles[profile_id] = data
    return profiles, errors


def is_profile_enabled(root: Path) -> bool:
    profiles, _ = load_profiles(root)
    return bool(profiles) or core_direction_complete(root)


def iter_wiki_pages(root: Path) -> list[Path]:
    wiki = root / "wiki"
    if not wiki.exists():
        return []
    return sorted(path for path in wiki.rglob("*.md") if path.is_file())


def page_headings(body: str) -> list[str]:
    return [match.group(2).strip() for match in HEADING_RE.finditer(body)]


def is_cjk_char(value: str) -> bool:
    codepoint = ord(value)
    return any(start <= codepoint <= end for start, end in CJK_RANGES)


def is_word_char(value: str) -> bool:
    return value == "_" or unicodedata.category(value)[0] in {"L", "N"}


def cjk_tokens(run: str) -> list[str]:
    run = run.lower()
    if len(run) <= 1:
        return [run] if run else []
    return [run[index : index + 2] for index in range(len(run) - 1)]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    word_run: list[str] = []
    cjk_run: list[str] = []

    def flush_word() -> None:
        if word_run:
            tokens.append("".join(word_run).lower())
            word_run.clear()

    def flush_cjk() -> None:
        if cjk_run:
            tokens.extend(cjk_tokens("".join(cjk_run)))
            cjk_run.clear()

    for char in text:
        if is_cjk_char(char):
            flush_word()
            cjk_run.append(char)
        elif is_word_char(char):
            flush_cjk()
            word_run.append(char)
        else:
            flush_word()
            flush_cjk()
    flush_word()
    flush_cjk()
    return tokens


def is_external_target(value: str) -> bool:
    return bool(URL_RE.match(value.strip()))


def is_local_reference(value: str) -> bool:
    value = value.strip()
    if not value or is_external_target(value) or value.startswith("#"):
        return False
    return value.startswith(("raw/", "wiki/", "reports/")) or "/" in value or Path(value).suffix != ""


def wiki_link_targets(body: str) -> list[str]:
    targets: list[str] = []
    for match in WIKI_LINK_RE.finditer(body):
        target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            targets.append(target)
    return targets


def extract_links(body: str, page_path: Path, root: Path) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for match in MARKDOWN_LINK_RE.finditer(body):
        target = match.group(1).split("#", 1)[0].strip()
        if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        resolved = (page_path.parent / target).resolve()
        try:
            target_rel = resolved.relative_to(root.resolve()).as_posix()
        except ValueError:
            target_rel = target
        links.append({"target": target_rel, "kind": "markdown"})
    for match in WIKI_LINK_RE.finditer(body):
        target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            links.append({"target": target, "kind": "wiki"})
    return links


def page_record(path: Path, root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(text)
    headings = page_headings(body)
    page_rel = relpath(path, root)
    title = str(metadata.get("title") or path.stem.replace("-", " ").title())
    slug = str(metadata.get("slug") or slugify(title))
    aliases = normalize_list(metadata.get("aliases"))
    tags = normalize_list(metadata.get("tags"))
    sources = normalize_list(metadata.get("sources"))
    profiles = normalize_list(metadata.get("profiles"))
    summary = str(metadata.get("summary") or "")
    search_parts = [title, slug, summary, " ".join(aliases), " ".join(tags), " ".join(headings), body]
    links = extract_links(body, path, root)
    return {
        "path": page_rel,
        "title": title,
        "slug": slug,
        "type": str(metadata.get("type") or "note"),
        "summary": summary,
        "aliases": aliases,
        "tags": tags,
        "sources": sources,
        "profiles": profiles,
        "extraction_goal": str(metadata.get("extraction_goal") or ""),
        "confidence": str(metadata.get("confidence") or "unknown"),
        "contested": bool(metadata.get("contested", False)),
        "created": str(metadata.get("created") or ""),
        "updated": str(metadata.get("updated") or ""),
        "headings": headings,
        "links": links,
        "word_count": len(tokenize(body)),
        "search_text": " ".join(search_parts),
    }


def build_memory_artifacts(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    pages = [page_record(path, root) for path in iter_wiki_pages(root)]
    now = utc_now()
    index_pages = []
    links = []
    path_set = {page["path"] for page in pages}
    outgoing: dict[str, list[str]] = {}
    incoming: dict[str, list[str]] = {page["path"]: [] for page in pages}
    link_lookup = page_lookup(pages)

    for page in pages:
        page_links: list[str] = []
        for link in page["links"]:
            target = link["target"]
            if link["kind"] == "wiki":
                resolved_target = link_lookup.get(target.strip().lower()) or link_lookup.get(slugify(target))
                if resolved_target:
                    target = resolved_target
            if target in path_set:
                page_links.append(target)
                incoming.setdefault(target, []).append(page["path"])
                links.append({"source": page["path"], "target": target, "kind": link["kind"]})
        outgoing[page["path"]] = sorted(set(page_links))

        index_pages.append(
            {
                key: page[key]
                for key in [
                    "path",
                    "title",
                    "slug",
                    "type",
                    "summary",
                    "aliases",
                    "tags",
                    "sources",
                    "profiles",
                    "extraction_goal",
                    "confidence",
                    "contested",
                    "created",
                    "updated",
                    "headings",
                    "word_count",
                    "search_text",
                ]
            }
        )

    graph = {
        "schema": "llm-wiki-link-graph-v1",
        "generated_at": now,
        "nodes": sorted(path_set),
        "links": sorted(links, key=lambda item: (item["source"], item["target"], item["kind"])),
        "outgoing": {path: outgoing.get(path, []) for path in sorted(path_set)},
        "incoming": {path: sorted(set(incoming.get(path, []))) for path in sorted(path_set)},
        "orphans": sorted(path for path in path_set if not incoming.get(path) and not outgoing.get(path)),
    }
    index = {
        "schema": "llm-wiki-memory-index-v1",
        "generated_at": now,
        "pages": sorted(index_pages, key=lambda page: page["path"]),
    }
    return index, graph


def canonical_artifact(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: canonical_artifact(value) for key, value in sorted(data.items()) if key != "generated_at"}
    if isinstance(data, list):
        return [canonical_artifact(item) for item in data]
    return data


def artifact_matches(current: Any, expected: Any) -> bool:
    return stable_json(canonical_artifact(current)) == stable_json(canonical_artifact(expected))


def page_lookup(pages: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for page in pages:
        path = str(page.get("path", ""))
        if not path:
            continue
        keys = {
            path,
            Path(path).stem,
            str(page.get("slug", "")),
            str(page.get("title", "")),
        }
        for alias in normalize_list(page.get("aliases")):
            keys.add(alias)
        for key in keys:
            normalized = key.strip().lower()
            if normalized:
                lookup[normalized] = path
                lookup[slugify(normalized)] = path
    return lookup


def resolve_wiki_link(target: str, pages: list[dict[str, Any]]) -> str | None:
    lookup = page_lookup(pages)
    normalized = target.strip().lower()
    if not normalized:
        return None
    return lookup.get(normalized) or lookup.get(slugify(normalized))


def is_memory_index(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("pages"), list)


def is_link_graph(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("links"), list)


def load_retrieval_artifacts(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_index, expected_graph = build_memory_artifacts(root)

    memory_index, memory_error = load_json(root / "memory-index.json", {})
    if memory_error or not is_memory_index(memory_index) or not artifact_matches(memory_index, expected_index):
        memory_index = expected_index

    link_graph, graph_error = load_json(root / "link-graph.json", {})
    if graph_error or not is_link_graph(link_graph) or not artifact_matches(link_graph, expected_graph):
        link_graph = expected_graph

    return memory_index, link_graph


def load_memory_index(root: Path) -> dict[str, Any]:
    data, _ = load_retrieval_artifacts(root)
    return data


def load_link_graph(root: Path) -> dict[str, Any]:
    _, data = load_retrieval_artifacts(root)
    return data


def load_memory_index_legacy(root: Path) -> dict[str, Any]:
    data, error = load_json(root / "memory-index.json", {"pages": []})
    if error or not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        data, _ = build_memory_artifacts(root)
    return data


def load_link_graph_legacy(root: Path) -> dict[str, Any]:
    data, error = load_json(root / "link-graph.json", {"links": [], "outgoing": {}, "incoming": {}})
    if error or not isinstance(data, dict):
        _, data = build_memory_artifacts(root)
    return data


def page_matches_identifier(page: dict[str, Any], identifier: str) -> bool:
    normalized = identifier.strip().lower()
    return normalized in {
        str(page.get("path", "")).lower(),
        str(page.get("slug", "")).lower(),
        str(page.get("title", "")).lower(),
    }


def page_profile_eligible(page: dict[str, Any], profile: str | None, include_unprofiled: bool) -> bool:
    if not profile:
        return True
    page_profiles = normalize_list(page.get("profiles"))
    if profile in page_profiles:
        return True
    return include_unprofiled and not page_profiles


def retrieve(
    root: Path,
    query: str,
    limit: int = 5,
    expand_links: bool = True,
    profile: str | None = None,
    include_unprofiled: bool = False,
) -> list[dict[str, Any]]:
    if profile:
        profiles, profile_errors = load_profiles(root)
        if profile_errors:
            raise ValueError("; ".join(profile_errors))
        if profile not in profiles:
            raise ValueError(f"unknown profile: {profile}")
    memory_index, graph = load_retrieval_artifacts(root)
    pages = memory_index.get("pages", [])
    query_terms = tokenize(query)
    query_text = " ".join(query_terms)
    query_raw = query.strip().lower()
    scores: dict[str, float] = {}
    reasons: dict[str, Counter[str]] = {}
    by_path = {
        page["path"]: page
        for page in pages
        if isinstance(page, dict) and "path" in page and page_profile_eligible(page, profile, include_unprofiled)
    }

    for page in by_path.values():
        page_path = page["path"]
        reasons[page_path] = Counter()
        title = str(page.get("title", "")).lower()
        slug = str(page.get("slug", "")).lower()
        aliases = [item.lower() for item in normalize_list(page.get("aliases"))]
        tags = [item.lower() for item in normalize_list(page.get("tags"))]
        headings = [item.lower() for item in normalize_list(page.get("headings"))]
        summary = str(page.get("summary", "")).lower()
        search_text = str(page.get("search_text", "")).lower()
        title_tokens = set(tokenize(title))
        heading_tokens = set(token for heading in headings for token in tokenize(heading))
        summary_tokens = set(tokenize(summary))
        alias_tokens = set(token for alias in aliases for token in tokenize(alias))
        tag_tokens = set(token for tag in tags for token in tokenize(tag))
        search_counts = Counter(tokenize(search_text))
        score = 0.0

        if query.strip().lower() in {title, slug, *aliases}:
            score += 60
            reasons[page_path]["exact"] += 1
        if (query_text and query_text in summary) or (query_raw and query_raw in summary):
            score += 20
            reasons[page_path]["summary_phrase"] += 1
        for term in query_terms:
            if term == slug:
                score += 12
                reasons[page_path]["slug"] += 1
            if term in title_tokens:
                score += 10
                reasons[page_path]["title"] += 1
            if term in aliases or term in alias_tokens:
                score += 9
                reasons[page_path]["alias"] += 1
            if term in tags or term in tag_tokens:
                score += 8
                reasons[page_path]["tag"] += 1
            if term in heading_tokens:
                score += 5
                reasons[page_path]["heading"] += 1
            if term in summary_tokens:
                score += 4
                reasons[page_path]["summary"] += 1
            occurrences = search_counts.get(term, 0)
            if occurrences:
                score += min(occurrences, 8) * 0.75
                reasons[page_path]["lexical"] += occurrences
        matched_score = score
        if matched_score > 0:
            page_profiles = normalize_list(page.get("profiles"))
            if profile and profile in page_profiles:
                score += 3
                reasons[page_path]["profile"] += 1
            elif profile and not page_profiles and include_unprofiled:
                score = max(score - 1, 0.1)
                reasons[page_path]["unprofiled"] += 1
            if page.get("updated"):
                score += 0.1
            scores[page_path] = score

    if expand_links and scores:
        outgoing = graph.get("outgoing", {}) if isinstance(graph.get("outgoing"), dict) else {}
        incoming = graph.get("incoming", {}) if isinstance(graph.get("incoming"), dict) else {}
        seed_paths = sorted(scores, key=lambda path: scores[path], reverse=True)[: max(limit, 3)]
        for seed in seed_paths:
            for neighbor in set(outgoing.get(seed, []) + incoming.get(seed, [])):
                if neighbor in by_path and neighbor not in scores:
                    scores[neighbor] = max(scores[seed] * 0.25, 1.0)
                    reasons.setdefault(neighbor, Counter())["one_hop"] += 1

    ranked = sorted(scores, key=lambda path: (-scores[path], by_path[path].get("title", ""), path))
    hits: list[dict[str, Any]] = []
    for path in ranked[:limit]:
        page = by_path[path]
        hits.append(
            {
                "path": path,
                "title": page.get("title", path),
                "slug": page.get("slug", ""),
                "score": round(scores[path], 3),
                "summary": page.get("summary", ""),
                "profiles": normalize_list(page.get("profiles")),
                "confidence": page.get("confidence", "unknown"),
                "contested": bool(page.get("contested", False)),
                "reasons": sorted(reasons.get(path, Counter()).keys()),
            }
        )
    return hits


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    if not path.exists():
        return entries, errors
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{line_no}: invalid JSON: {exc}")
            continue
        if not isinstance(item, dict):
            errors.append(f"{path}:{line_no}: entry must be an object")
            continue
        entries.append(item)
    return entries, errors


def write_report(root: Path, kind: str, name: str, markdown: str, data: dict[str, Any] | None = None) -> tuple[Path, Path | None]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_dir = root / "reports" / kind
    report_dir.mkdir(parents=True, exist_ok=True)
    base_stem = f"{timestamp}-{slugify(name)}"
    stem = base_stem
    suffix = 1
    while (report_dir / f"{stem}.md").exists() or (data is not None and (report_dir / f"{stem}.json").exists()):
        suffix += 1
        stem = f"{base_stem}-{suffix}"
    md_path = report_dir / f"{stem}.md"
    md_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    json_path = None
    if data is not None:
        json_path = report_dir / f"{stem}.json"
        write_json(json_path, data)
    return md_path, json_path
