#!/usr/bin/env python3
"""Shared helpers for llm-wiki-builder scripts."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    "reports/optimization",
    "reports/retrieval",
]

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


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value in (None, ""):
        return []
    return [str(value)]


def iter_wiki_pages(root: Path) -> list[Path]:
    wiki = root / "wiki"
    if not wiki.exists():
        return []
    return sorted(path for path in wiki.rglob("*.md") if path.is_file())


def page_headings(body: str) -> list[str]:
    return [match.group(2).strip() for match in HEADING_RE.finditer(body)]


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


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
        links.append({"target": slugify(match.group(1).split("|", 1)[0]), "kind": "wiki"})
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
    slug_to_path = {page["slug"]: page["path"] for page in pages}

    for page in pages:
        page_links: list[str] = []
        for link in page["links"]:
            target = link["target"]
            if target in slug_to_path:
                target = slug_to_path[target]
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


def load_memory_index(root: Path) -> dict[str, Any]:
    data, error = load_json(root / "memory-index.json", {"pages": []})
    if error or not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        data, _ = build_memory_artifacts(root)
    return data


def load_link_graph(root: Path) -> dict[str, Any]:
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


def retrieve(root: Path, query: str, limit: int = 5, expand_links: bool = True) -> list[dict[str, Any]]:
    memory_index = load_memory_index(root)
    pages = memory_index.get("pages", [])
    query_terms = tokenize(query)
    query_text = " ".join(query_terms)
    scores: dict[str, float] = {}
    reasons: dict[str, Counter[str]] = {}
    by_path = {page["path"]: page for page in pages if isinstance(page, dict) and "path" in page}

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
        score = 0.0

        if query.strip().lower() in {title, slug, *aliases}:
            score += 60
            reasons[page_path]["exact"] += 1
        if query_text and query_text in summary:
            score += 20
            reasons[page_path]["summary_phrase"] += 1
        for term in query_terms:
            if term == slug:
                score += 12
                reasons[page_path]["slug"] += 1
            if term in title:
                score += 10
                reasons[page_path]["title"] += 1
            if term in aliases:
                score += 9
                reasons[page_path]["alias"] += 1
            if term in tags:
                score += 8
                reasons[page_path]["tag"] += 1
            if any(term in heading for heading in headings):
                score += 5
                reasons[page_path]["heading"] += 1
            if term in summary:
                score += 4
                reasons[page_path]["summary"] += 1
            occurrences = search_text.count(term)
            if occurrences:
                score += min(occurrences, 8) * 0.75
                reasons[page_path]["lexical"] += occurrences
        matched_score = score
        if matched_score > 0:
            if page.get("updated"):
                score += 0.1
            scores[page_path] = score

    if expand_links and scores:
        graph = load_link_graph(root)
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
    timestamp = utc_now().replace(":", "").replace("-", "")
    report_dir = root / "reports" / kind
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"{timestamp}-{slugify(name)}.md"
    md_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    json_path = None
    if data is not None:
        json_path = report_dir / f"{timestamp}-{slugify(name)}.json"
        write_json(json_path, data)
    return md_path, json_path
