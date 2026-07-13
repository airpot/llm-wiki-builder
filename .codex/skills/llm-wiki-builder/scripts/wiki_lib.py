#!/usr/bin/env python3
"""Shared helpers for llm-wiki-builder scripts."""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

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
    "reports/context-packs",
    "reports/publish/html",
    "reports/publish/mcp",
]

PROFILE_DIR = "profiles"
PROFILE_SCHEMA = "llm-wiki-extraction-profile-v1"
GLOSSARY_SCHEMA = "llm-wiki-glossary-v1"
DELIVERY_CONTRACT_SCHEMA = "llm-wiki-delivery-contract-v1"
DELIVERY_PUBLISH_TARGETS = {"markdown", "html", "mcp", "mcp-skill"}
DELIVERY_MCP_RUNTIMES = {"executable", "contract-only"}
DELIVERY_PUBLICATION_MODES = {"linked", "snapshot"}
DELIVERY_UPDATE_STRATEGIES = {"rebuild-on-change", "manual"}
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
EXCERPT_TRUNCATION_MARKER = "\n\n[excerpt truncated]"
SAFE_HTML_LINK_SCHEMES = {"http", "https", "mailto"}

DEFAULT_DELIVERY_CONTRACT: dict[str, Any] = {
    "schema": DELIVERY_CONTRACT_SCHEMA,
    "publish_target": "mcp-skill",
    "consumer_hosts": ["codex"],
    "mcp_runtime": "executable",
    "transport": "stdio",
    "publication_mode": "snapshot",
    "privacy": {
        "include_raw_sources": False,
        "include_query_history": False,
        "include_absolute_paths": False,
    },
    "update_strategy": "rebuild-on-change",
    "skill_targets": ["codex"],
}

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


def confined_source_path(root: Path, path: Path, *, scope: str = "wiki root") -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"path escapes {scope}: {path}")
    return resolved


def confined_output_path(root: Path, path: Path, *, scope: str = "wiki root") -> Path:
    """Reject generated paths whose lexical or existing real parents escape root."""
    resolved_root = root.resolve()
    candidate = path if path.is_absolute() else root / path
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"generated path escapes {scope}: {path}") from exc
    current = resolved_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"generated path contains symbolic link: {current}")
        if current.exists():
            resolved = current.resolve()
            if resolved != resolved_root and resolved_root not in resolved.parents:
                raise ValueError(f"generated path escapes {scope}: {path}")
    resolved = candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"generated path escapes {scope}: {path}")
    return resolved


def confined_output_tree(root: Path, path: Path, *, scope: str = "wiki root") -> Path:
    """Reject symbolic links anywhere in an existing generated-output tree."""
    resolved = confined_output_path(root, path, scope=scope)
    if path.exists() and path.is_dir():
        for descendant in sorted(path.rglob("*")):
            confined_output_path(root, descendant, scope=scope)
    return resolved


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
    confined_output_path(root, log_path, scope="wiki root")
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


def short_text_hash(text: str, length: int = 16) -> str:
    return source_body_hash(text)[:length]


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


def default_delivery_contract() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_DELIVERY_CONTRACT))


def validate_delivery_contract_data(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["delivery contract must be a JSON object"]
    errors: list[str] = []
    if data.get("schema") != DELIVERY_CONTRACT_SCHEMA:
        errors.append(f"delivery contract schema must be {DELIVERY_CONTRACT_SCHEMA}")
    if data.get("publish_target") not in DELIVERY_PUBLISH_TARGETS:
        errors.append(f"delivery contract publish_target must be one of {sorted(DELIVERY_PUBLISH_TARGETS)}")
    if data.get("mcp_runtime") not in DELIVERY_MCP_RUNTIMES:
        errors.append(f"delivery contract mcp_runtime must be one of {sorted(DELIVERY_MCP_RUNTIMES)}")
    if data.get("transport") != "stdio":
        errors.append("delivery contract transport must be stdio")
    if data.get("publication_mode") not in DELIVERY_PUBLICATION_MODES:
        errors.append(f"delivery contract publication_mode must be one of {sorted(DELIVERY_PUBLICATION_MODES)}")
    if data.get("update_strategy") not in DELIVERY_UPDATE_STRATEGIES:
        errors.append(f"delivery contract update_strategy must be one of {sorted(DELIVERY_UPDATE_STRATEGIES)}")
    for field in ("consumer_hosts", "skill_targets"):
        value = data.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            errors.append(f"delivery contract {field} must be a string list")
    privacy = data.get("privacy")
    if not isinstance(privacy, dict):
        errors.append("delivery contract privacy must be an object")
    else:
        for field in ("include_raw_sources", "include_query_history", "include_absolute_paths"):
            if not isinstance(privacy.get(field), bool):
                errors.append(f"delivery contract privacy.{field} must be boolean")
        if any(privacy.get(field) is True for field in privacy):
            errors.append("delivery contract default publisher does not support privacy inclusions")
    if data.get("publish_target") == "mcp-skill" and not data.get("skill_targets"):
        errors.append("delivery contract mcp-skill target requires at least one skill target")
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


def iter_glossary_entries(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    json_path = root / "glossary.json"
    if json_path.exists():
        data, error = load_json(json_path, {})
        if error:
            errors.append(f"glossary.json: invalid JSON: {error}")
        elif not isinstance(data, dict):
            errors.append("glossary.json: glossary must be an object")
        elif data.get("schema") not in (None, GLOSSARY_SCHEMA):
            errors.append(f"glossary.json: schema must be {GLOSSARY_SCHEMA}")
        else:
            terms = data.get("terms", [])
            if not isinstance(terms, list):
                errors.append("glossary.json: terms must be a list")
            else:
                for index, term in enumerate(terms, start=1):
                    if isinstance(term, dict):
                        term = dict(term)
                        term["_source"] = f"glossary.json terms[{index}]"
                        entries.append(term)
                    else:
                        errors.append(f"glossary.json terms[{index}]: entry must be an object")

    jsonl_path = root / "glossary.jsonl"
    if jsonl_path.exists():
        jsonl_entries, jsonl_errors = read_jsonl(jsonl_path)
        errors.extend(error.replace(jsonl_path.as_posix(), "glossary.jsonl") for error in jsonl_errors)
        for index, term in enumerate(jsonl_entries, start=1):
            term = dict(term)
            term["_source"] = f"glossary.jsonl line {index}"
            entries.append(term)
    return entries, errors


def validate_glossary_entries(entries: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_canonical: dict[str, str] = {}
    seen_aliases: dict[str, str] = {}
    for index, entry in enumerate(entries, start=1):
        source = str(entry.get("_source") or f"glossary entry {index}")
        canonical = str(entry.get("canonical") or "").strip()
        if not canonical or is_placeholder_value(canonical):
            errors.append(f"{source}: canonical must be a non-empty string")
            continue
        normalized_canonical = canonical.lower()
        if normalized_canonical in seen_canonical:
            errors.append(f"{source}: duplicate canonical term {canonical!r} also declared in {seen_canonical[normalized_canonical]}")
        else:
            seen_canonical[normalized_canonical] = source
        aliases = entry.get("aliases")
        if not isinstance(aliases, list) or is_placeholder_value(aliases):
            errors.append(f"{source}: aliases must be a non-empty list")
            continue
        for alias in aliases:
            if not isinstance(alias, str) or is_placeholder_value(alias):
                errors.append(f"{source}: aliases must contain non-empty strings")
                continue
            normalized_alias = alias.strip().lower()
            if normalized_alias in seen_aliases and seen_aliases[normalized_alias] != normalized_canonical:
                errors.append(
                    f"{source}: alias {alias!r} conflicts with canonical {seen_aliases[normalized_alias]!r}"
                )
            else:
                seen_aliases[normalized_alias] = normalized_canonical
    return errors


def load_glossary(root: Path) -> tuple[dict[str, set[str]], list[str]]:
    entries, errors = iter_glossary_entries(root)
    errors.extend(validate_glossary_entries(entries))
    groups: dict[str, set[str]] = {}
    canonical_by_alias: dict[str, str] = {}
    for entry in entries:
        canonical = str(entry.get("canonical") or "").strip()
        aliases = entry.get("aliases")
        if not canonical or not isinstance(aliases, list):
            continue
        normalized_canonical = canonical.lower()
        if normalized_canonical in groups:
            continue
        terms = {canonical}
        valid = True
        for alias in aliases:
            if not isinstance(alias, str) or is_placeholder_value(alias):
                valid = False
                break
            normalized_alias = alias.strip().lower()
            if normalized_alias in canonical_by_alias and canonical_by_alias[normalized_alias] != normalized_canonical:
                valid = False
                break
            canonical_by_alias[normalized_alias] = normalized_canonical
            terms.add(alias)
        if valid:
            groups[normalized_canonical] = terms
    return groups, errors


def expanded_query_terms(query_terms: list[str], glossary: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    direct = list(dict.fromkeys(query_terms))
    direct_set = set(direct)
    expanded: list[str] = []
    for term in direct:
        for terms in glossary.values():
            tokenized_terms = {token for value in terms for token in tokenize(value)}
            raw_terms = {value.strip().lower() for value in terms if value.strip()}
            if term not in tokenized_terms and term not in raw_terms:
                continue
            for value in terms:
                for token in tokenize(value):
                    if token not in direct_set and token not in expanded:
                        expanded.append(token)
                raw = value.strip().lower()
                if raw and raw not in direct_set and raw not in expanded:
                    expanded.append(raw)
    return direct, expanded


def has_mixed_scripts(text: str) -> bool:
    has_cjk = any(is_cjk_char(char) for char in text)
    has_latin = any("LATIN" in unicodedata.name(char, "") for char in text if char.isalpha())
    return has_cjk and has_latin


def is_profile_enabled(root: Path) -> bool:
    profiles, _ = load_profiles(root)
    return bool(profiles) or core_direction_complete(root)


def iter_wiki_pages(root: Path) -> list[Path]:
    wiki = root / "wiki"
    if not wiki.exists():
        return []
    if wiki.is_symlink():
        raise ValueError(f"canonical wiki directory must not be a symbolic link: {wiki}")
    confined_source_path(root, wiki, scope="wiki root")
    pages: list[Path] = []
    for path in sorted(wiki.rglob("*.md")):
        if not path.is_file():
            continue
        confined_source_path(wiki, path, scope="canonical wiki directory")
        pages.append(path)
    return pages


def read_wiki_page(root: Path, page_path: str) -> tuple[dict[str, Any], str]:
    path = root / page_path
    text = path.read_text(encoding="utf-8")
    return parse_frontmatter(text)


def excerpt_text(text: str, max_chars: int) -> str:
    body = text.strip()
    if max_chars <= 0:
        return ""
    if len(body) <= max_chars:
        return body
    marker = EXCERPT_TRUNCATION_MARKER
    if max_chars <= len(marker):
        return body[:max_chars]
    content_budget = max_chars - len(marker)
    cutoff = body.rfind("\n\n", 0, content_budget + 1)
    if cutoff < content_budget // 2:
        cutoff = body.rfind("\n", 0, content_budget + 1)
    if cutoff < content_budget // 2:
        cutoff = content_budget
    return body[:cutoff].rstrip() + marker


def bounded_excerpt_with_offsets(text: str, start: int, end: int, max_chars: int) -> tuple[str, int]:
    source = text[start:end]
    stripped = source.strip()
    if max_chars <= 0:
        return "", start
    if len(stripped) <= max_chars:
        return stripped, end
    marker = EXCERPT_TRUNCATION_MARKER
    if max_chars <= len(marker):
        excerpt = source[:max_chars]
        return excerpt, start + len(excerpt)
    content_budget = max_chars - len(marker)
    cutoff = source.rfind("\n\n", 0, content_budget + 1)
    if cutoff < content_budget // 2:
        cutoff = source.rfind("\n", 0, content_budget + 1)
    if cutoff < content_budget // 2:
        cutoff = content_budget
    excerpt = source[:cutoff].rstrip()
    return excerpt + marker, start + len(excerpt)


def heading_anchor(page_path: str, heading_path: list[str], title: str, occurrence: int) -> str:
    base = slugify(title) or "section"
    digest = short_text_hash(f"{page_path}\n{'/'.join(heading_path)}\n{occurrence}\n{title}", 8)
    return f"{base}-{digest}"


def markdown_sections(body: str, page_path: str = "") -> list[dict[str, Any]]:
    matches = list(HEADING_RE.finditer(body))
    if not matches:
        stripped = body.strip()
        section_id = heading_anchor(page_path, ["Document"], "Document", 1)
        return [
            {
                "section_id": section_id,
                "heading": "Document",
                "heading_level": 0,
                "heading_path": ["Document"],
                "char_start": 0,
                "char_end": len(body),
                "content_hash": short_text_hash(stripped),
            }
        ]

    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    occurrences: Counter[tuple[str, ...]] = Counter()
    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        heading_path = [item[1] for item in stack]
        occurrence_key = tuple(heading_path)
        occurrences[occurrence_key] += 1
        end = len(body)
        for later in matches[index + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        section_text = body[match.start() : end].strip()
        section_id = heading_anchor(page_path, heading_path, title, occurrences[occurrence_key])
        sections.append(
            {
                "section_id": section_id,
                "heading": title,
                "heading_level": level,
                "heading_path": heading_path,
                "char_start": match.start(),
                "char_end": end,
                "content_hash": short_text_hash(section_text),
            }
        )
    return sections


def section_index(body: str, page_path: str = "") -> list[dict[str, Any]]:
    return [
        {
            "section_id": section["section_id"],
            "heading": section["heading"],
            "heading_level": section["heading_level"],
            "heading_path": section["heading_path"],
            "char_start": section["char_start"],
            "char_end": section["char_end"],
            "content_hash": section["content_hash"],
        }
        for section in markdown_sections(body, page_path)
    ]


def chunk_payloads(
    body: str,
    page_path: str,
    *,
    max_chars: int,
    max_chunks: int = 8,
    metadata: dict[str, Any] | None = None,
    hit: dict[str, Any] | None = None,
    query_terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    metadata = metadata or {}
    hit = hit or {}
    chunks: list[dict[str, Any]] = []
    remaining = max(max_chars, 0)
    sections = markdown_sections(body, page_path)
    terms = [term.lower() for term in (query_terms or []) if term]
    if terms:
        ranked: list[tuple[int, int, int, dict[str, Any]]] = []
        for section in sections:
            start = int(section["char_start"])
            end = int(section["char_end"])
            section_text = body[start:end].lower()
            heading_text = " ".join(section.get("heading_path", [])).lower()
            body_matches = sum(section_text.count(term) for term in terms)
            heading_matches = sum(heading_text.count(term) for term in terms)
            ranked.append((body_matches, heading_matches, -(end - start), section))
        selected = [item[3] for item in sorted(ranked, key=lambda item: item[:3], reverse=True)[: max(max_chunks, 0)]]
        sections = sorted(selected, key=lambda section: int(section["char_start"]))
    else:
        sections = sections[: max(max_chunks, 0)]
    for index, section in enumerate(sections, start=1):
        if remaining <= 0:
            break
        sections_left = len(sections) - index + 1
        chunk_budget = max(1, remaining // sections_left)
        excerpt, excerpt_end = bounded_excerpt_with_offsets(
            body,
            int(section["char_start"]),
            int(section["char_end"]),
            chunk_budget,
        )
        if not excerpt:
            break
        remaining -= len(excerpt)
        chunk_id = f"{section['section_id']}-c{index}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "path": page_path,
                "section_id": section["section_id"],
                "heading": section["heading"],
                "heading_path": section["heading_path"],
                "char_start": section["char_start"],
                "char_end": excerpt_end,
                "excerpt": excerpt,
                "excerpt_hash": short_text_hash(excerpt),
                "content_hash": section["content_hash"],
                "confidence": str(metadata.get("confidence") or hit.get("confidence") or "unknown"),
                "contested": bool(metadata.get("contested", hit.get("contested", False))),
                "sources": normalize_list(metadata.get("sources") or hit.get("sources")),
                "match_type": hit.get("match_type", "seed"),
                "score": hit.get("score", 0),
                "primary_score": hit.get("primary_score", 0),
                "reasons": hit.get("reasons", []),
                "reason_counts": hit.get("reason_counts", {}),
            }
        )
    return chunks


def safe_html_link_target(target: str) -> str | None:
    value = target.strip()
    if not value:
        return None
    if value.startswith("//"):
        return None
    scheme = urlsplit(value).scheme.lower()
    if scheme and scheme not in SAFE_HTML_LINK_SCHEMES:
        return None
    return value


def markdown_to_semantic_html(
    markdown: str,
    page_path: str = "",
    metadata: dict[str, Any] | None = None,
    link_rewriter: Callable[[str], str | None] | None = None,
) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    paragraph: list[str] = []
    list_stack: list[str] = []
    in_code = False
    code_lines: list[str] = []
    in_blockquote = False
    blockquote_lines: list[str] = []
    in_table = False
    table_rows: list[str] = []
    open_section = False
    heading_stack: list[tuple[int, str]] = []
    heading_occurrences: Counter[tuple[str, ...]] = Counter()
    section_lookup = {
        int(section["char_start"]): section
        for section in markdown_sections(markdown, page_path)
        if int(section.get("heading_level", 0)) > 0
    }
    cursor = 0
    metadata = metadata or {}

    def inline(value: str) -> str:
        escaped = html.escape(value)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)

        def replace_link(match: re.Match[str]) -> str:
            label = match.group(1)
            raw_target = html.unescape(match.group(2))
            target = link_rewriter(raw_target) if link_rewriter else safe_html_link_target(raw_target)
            if target is None:
                return f'<span data-unsafe-link="true">{label}</span>'
            return f'<a href="{html.escape(target, quote=True)}">{label}</a>'

        escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, escaped)
        escaped = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"<span data-wikilink=\"\1\">\2</span>", escaped)
        escaped = re.sub(r"\[\[([^\]]+)\]\]", r"<span data-wikilink=\"\1\">\1</span>", escaped)
        return escaped

    def close_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph = []

    def close_lists() -> None:
        nonlocal list_stack
        if list_stack:
            out.append("<ul>")
            out.extend(f"<li>{inline(item)}</li>" for item in list_stack)
            out.append("</ul>")
            list_stack = []

    def close_blockquote() -> None:
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote:
            out.append("<blockquote>")
            out.extend(f"<p>{inline(line)}</p>" for line in blockquote_lines if line.strip())
            out.append("</blockquote>")
            in_blockquote = False
            blockquote_lines = []

    def close_table() -> None:
        nonlocal in_table, table_rows
        if not in_table:
            return
        rows = [row for row in table_rows if row.strip()]
        out.append("<table>")
        parsed_rows = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows]
        has_header = (
            len(parsed_rows) >= 2
            and all(set(cell.replace(":", "").strip()) <= {"-"} and cell.replace(":", "").strip() for cell in parsed_rows[1])
        )
        if has_header:
            out.append("<thead>")
            out.append("<tr>" + "".join(f"<th>{inline(cell)}</th>" for cell in parsed_rows[0]) + "</tr>")
            out.append("</thead>")
            body_rows = parsed_rows[2:]
            if body_rows:
                out.append("<tbody>")
                for cells in body_rows:
                    out.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in cells) + "</tr>")
                out.append("</tbody>")
        else:
            out.append("<tbody>")
            for cells in parsed_rows:
                out.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in cells) + "</tr>")
            out.append("</tbody>")
        out.append("</table>")
        in_table = False
        table_rows = []

    def close_blocks() -> None:
        close_paragraph()
        close_lists()
        close_blockquote()
        close_table()

    def close_section() -> None:
        nonlocal open_section
        if open_section:
            close_blocks()
            out.append("</section>")
            open_section = False

    def open_heading_section(section: dict[str, Any]) -> None:
        nonlocal open_section
        if open_section:
            out.append("</section>")
        attrs = {
            "id": f"section-{section['section_id']}",
            "data-section-id": section["section_id"],
            "data-heading-path": " > ".join(section["heading_path"]),
            "data-page-path": page_path,
            "data-confidence": metadata.get("confidence", "unknown"),
            "data-contested": str(bool(metadata.get("contested", False))).lower(),
        }
        attr_text = " ".join(f'{key}="{html.escape(str(value), quote=True)}"' for key, value in attrs.items())
        out.append(f"<section {attr_text}>")
        open_section = True

    for raw in lines:
        line_start = cursor
        cursor += len(raw) + 1
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                in_code = False
                code_lines = []
            else:
                close_blocks()
                in_code = True
                code_lines = []
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.startswith("|") and line.endswith("|"):
            close_paragraph()
            close_lists()
            close_blockquote()
            in_table = True
            table_rows.append(line)
            continue
        elif in_table:
            close_table()
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            close_blocks()
            level = len(heading.group(1))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            title = heading.group(2).strip()
            heading_stack.append((level, title))
            occurrence_key = tuple(item[1] for item in heading_stack)
            heading_occurrences[occurrence_key] += 1
            section = section_lookup.get(line_start)
            if section:
                open_heading_section(section)
                heading_id = str(section["section_id"])
            else:
                heading_id = heading_anchor(
                    page_path,
                    [item[1] for item in heading_stack],
                    title,
                    heading_occurrences[occurrence_key],
                )
            out.append(f'<h{level} id="{html.escape(heading_id, quote=True)}">{inline(title)}</h{level}>')
            continue
        if line.startswith(">"):
            close_paragraph()
            close_lists()
            close_table()
            in_blockquote = True
            blockquote_lines.append(line.lstrip("> ").strip())
            continue
        if re.match(r"^\s*[-*]\s+", line):
            close_paragraph()
            close_blockquote()
            close_table()
            list_stack.append(re.sub(r"^\s*[-*]\s+", "", line))
            continue
        if not line.strip():
            close_blocks()
            continue
        close_lists()
        close_blockquote()
        paragraph.append(line.strip())

    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    close_blocks()
    close_section()
    return "\n".join(out)


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
    owners: dict[str, str] = {}
    for page in pages:
        path = str(page.get("path", ""))
        if not path:
            continue
        keys: list[tuple[str, bool]] = [
            (path, False),
            (Path(path).stem, False),
            (str(page.get("slug", "")), True),
            (str(page.get("title", "")), True),
        ]
        for alias in normalize_list(page.get("aliases")):
            keys.append((alias, True))
        for key, add_slug_variant in keys:
            normalized = key.strip().lower()
            if normalized:
                variants = {normalized}
                if add_slug_variant:
                    slug = slugify(normalized)
                    if slug != "untitled" or normalized == "untitled":
                        variants.add(slug)
                for variant in variants:
                    owner = owners.get(variant)
                    if owner and owner != path:
                        raise ValueError(f"identifier collision {variant!r}: {owner} and {path}")
                    owners[variant] = path
                    lookup[variant] = path
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


def profile_retrieval_config(profiles: dict[str, dict[str, Any]], profile: str | None) -> dict[str, Any]:
    if not profile:
        return {}
    retrieval = profiles.get(profile, {}).get("retrieval")
    return retrieval if isinstance(retrieval, dict) else {}


def retrieve(
    root: Path,
    query: str,
    limit: int = 5,
    expand_links: bool = True,
    profile: str | None = None,
    include_unprofiled: bool = False,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be a positive integer")
    profiles: dict[str, dict[str, Any]] = {}
    if profile:
        profiles, profile_errors = load_profiles(root)
        if profile_errors:
            raise ValueError("; ".join(profile_errors))
        if profile not in profiles:
            raise ValueError(f"unknown profile: {profile}")
    retrieval_config = profile_retrieval_config(profiles, profile)
    memory_index, graph = load_retrieval_artifacts(root)
    glossary, _ = load_glossary(root)
    pages = memory_index.get("pages", [])
    allow_glossary = retrieval_config.get("allow_glossary_expansion", True) is not False
    query_terms, glossary_terms = expanded_query_terms(tokenize(query), glossary if allow_glossary else {})
    query_text = " ".join(query_terms)
    query_raw = query.strip().lower()
    scores: dict[str, float] = {}
    primary_scores: dict[str, float] = {}
    reasons: dict[str, Counter[str]] = {}
    match_types: dict[str, str] = {}
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
        path_stem = Path(str(page_path)).stem.lower()
        aliases = [item.lower() for item in normalize_list(page.get("aliases"))]
        tags = [item.lower() for item in normalize_list(page.get("tags"))]
        headings = [item.lower() for item in normalize_list(page.get("headings"))]
        summary = str(page.get("summary", "")).lower()
        search_text = str(page.get("search_text", "")).lower()
        title_tokens = set(tokenize(title))
        path_stem_tokens = set(tokenize(path_stem))
        heading_tokens = set(token for heading in headings for token in tokenize(heading))
        summary_tokens = set(tokenize(summary))
        alias_tokens = set(token for alias in aliases for token in tokenize(alias))
        tag_tokens = set(token for tag in tags for token in tokenize(tag))
        search_counts = Counter(tokenize(search_text))
        glossary_counts = Counter(glossary_terms)
        score = 0.0
        primary_score = 0.0

        if query.strip().lower() in {title, slug, *aliases}:
            score += 60
            primary_score += 60
            reasons[page_path]["exact"] += 1
        normalized_page_path = str(page_path).lower()
        normalized_page_path_no_ext = str(Path(str(page_path)).with_suffix("")).lower()
        if query_raw and query_raw in {normalized_page_path, normalized_page_path_no_ext}:
            score += 30
            primary_score += 30
            reasons[page_path]["path"] += 1
        if query_raw and query_raw == path_stem:
            score += 30
            primary_score += 30
            reasons[page_path]["path_stem"] += 1
        if (query_text and query_text in summary) or (query_raw and query_raw in summary):
            score += 20
            primary_score += 20
            reasons[page_path]["summary_phrase"] += 1
        for term in query_terms:
            if term == slug:
                score += 12
                primary_score += 12
                reasons[page_path]["slug"] += 1
            if term == path_stem or term in path_stem_tokens:
                score += 7
                primary_score += 7
                reasons[page_path]["path_stem"] += 1
            if term in title_tokens:
                score += 10
                primary_score += 10
                reasons[page_path]["title"] += 1
            if term in aliases or term in alias_tokens:
                score += 9
                primary_score += 9
                reasons[page_path]["alias"] += 1
                if has_mixed_scripts(" ".join([query, " ".join(aliases)])):
                    reasons[page_path]["cross_lingual_alias"] += 1
            if term in tags or term in tag_tokens:
                score += 8
                primary_score += 8
                reasons[page_path]["tag"] += 1
            if term in heading_tokens:
                score += 5
                primary_score += 5
                reasons[page_path]["heading"] += 1
            if term in summary_tokens:
                score += 4
                primary_score += 4
                reasons[page_path]["summary"] += 1
            occurrences = search_counts.get(term, 0)
            if occurrences:
                score += min(occurrences, 8) * 0.75
                primary_score += min(occurrences, 8) * 0.75
                reasons[page_path]["lexical"] += occurrences
        for term, count in glossary_counts.items():
            if term in title_tokens or term in alias_tokens or term in tag_tokens or term in heading_tokens or term in summary_tokens:
                increment = min(count, 4) * 2.5
                score += increment
                primary_score += increment
                reasons[page_path]["glossary"] += count
            occurrences = search_counts.get(term, 0)
            if occurrences:
                increment = min(occurrences, 4) * 0.35
                score += increment
                primary_score += increment
                reasons[page_path]["glossary"] += occurrences
        if primary_score > 0:
            page_profiles = normalize_list(page.get("profiles"))
            if profile and profile in page_profiles:
                score += 3
                reasons[page_path]["profile"] += 1
            elif profile and not page_profiles and include_unprofiled:
                score = max(score - 1, 0.1)
                reasons[page_path]["unprofiled"] += 1
            if page.get("updated"):
                score += 0.1
                reasons[page_path]["freshness"] += 1
            scores[page_path] = score
            primary_scores[page_path] = primary_score
            match_types[page_path] = "seed"

    if expand_links and scores:
        outgoing = graph.get("outgoing", {}) if isinstance(graph.get("outgoing"), dict) else {}
        incoming = graph.get("incoming", {}) if isinstance(graph.get("incoming"), dict) else {}
        seed_paths = sorted(scores, key=lambda path: scores[path], reverse=True)[: max(limit, 3)]
        for seed in seed_paths:
            for neighbor in set(outgoing.get(seed, []) + incoming.get(seed, [])):
                if neighbor in by_path and neighbor not in scores:
                    scores[neighbor] = max(scores[seed] * 0.25, 1.0)
                    primary_scores[neighbor] = 0.0
                    match_types[neighbor] = "context"
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
                "primary_score": round(primary_scores.get(path, 0.0), 3),
                "match_type": match_types.get(path, "seed"),
                "seed": match_types.get(path, "seed") == "seed",
                "summary": page.get("summary", ""),
                "profiles": normalize_list(page.get("profiles")),
                "confidence": page.get("confidence", "unknown"),
                "contested": bool(page.get("contested", False)),
                "reasons": sorted(reasons.get(path, Counter()).keys()),
                "reason_counts": dict(sorted(reasons.get(path, Counter()).items())),
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
    confined_output_path(root, report_dir, scope="wiki root")
    report_dir.mkdir(parents=True, exist_ok=True)
    base_stem = f"{timestamp}-{slugify(name)}"
    stem = base_stem
    suffix = 1
    while (report_dir / f"{stem}.md").exists() or (data is not None and (report_dir / f"{stem}.json").exists()):
        suffix += 1
        stem = f"{base_stem}-{suffix}"
    md_path = report_dir / f"{stem}.md"
    confined_output_path(root, md_path, scope="wiki root")
    md_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    json_path = None
    if data is not None:
        json_path = report_dir / f"{stem}.json"
        confined_output_path(root, json_path, scope="wiki root")
        write_json(json_path, data)
    return md_path, json_path
