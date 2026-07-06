#!/usr/bin/env python3
"""Build an agent-ready context pack from deterministic wiki retrieval."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from wiki_lib import (
    RETRIEVAL_MODE,
    excerpt_text,
    read_wiki_page,
    retrieve,
    slugify,
    utc_now,
    write_report,
)


def page_payload(root: Path, hit: dict[str, Any], max_chars: int) -> dict[str, Any]:
    metadata, body = read_wiki_page(root, str(hit["path"]))
    return {
        "path": hit["path"],
        "title": hit.get("title", hit["path"]),
        "summary": hit.get("summary", ""),
        "confidence": hit.get("confidence", "unknown"),
        "contested": bool(hit.get("contested", False)),
        "profiles": hit.get("profiles", []),
        "sources": metadata.get("sources", []),
        "score": hit.get("score", 0),
        "primary_score": hit.get("primary_score", 0),
        "match_type": hit.get("match_type", "seed"),
        "seed": bool(hit.get("seed", False)),
        "reasons": hit.get("reasons", []),
        "reason_counts": hit.get("reason_counts", {}),
        "excerpt": excerpt_text(body, max_chars),
    }


def build_context_pack(
    root: Path,
    query: str,
    *,
    limit: int = 5,
    max_chars_per_page: int = 1800,
    expand_links: bool = True,
    profile: str | None = None,
    include_unprofiled: bool = False,
) -> dict[str, Any]:
    hits = retrieve(
        root,
        query,
        limit=limit,
        expand_links=expand_links,
        profile=profile,
        include_unprofiled=include_unprofiled,
    )
    pages = [page_payload(root, hit, max_chars_per_page) for hit in hits]
    return {
        "schema": "llm-wiki-context-pack-v1",
        "generated_at": utc_now(),
        "root": root.as_posix(),
        "query": query,
        "retrieval_mode": RETRIEVAL_MODE,
        "options": {
            "limit": limit,
            "max_chars_per_page": max_chars_per_page,
            "expand_links": expand_links,
            "profile_id": profile,
            "include_unprofiled": include_unprofiled,
        },
        "miss": not pages,
        "seed_pages": [page["path"] for page in pages if page["match_type"] == "seed"],
        "context_pages": [page["path"] for page in pages if page["match_type"] == "context"],
        "pages": pages,
    }


def markdown_context_pack(pack: dict[str, Any]) -> str:
    lines = [
        "# LLM Wiki Context Pack",
        "",
        f"- Query: {pack['query']}",
        f"- Retrieval Mode: {pack['retrieval_mode']}",
        f"- Generated At: {pack['generated_at']}",
        f"- Miss: {str(pack['miss']).lower()}",
        f"- Seed Pages: {len(pack['seed_pages'])}",
        f"- Context Pages: {len(pack['context_pages'])}",
        "",
    ]
    if pack["miss"]:
        lines.extend(
            [
                "## Miss",
                "",
                "The wiki lacks sufficient deterministic memory for this query.",
                "",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    lines.append("## Pages")
    for page in pack["pages"]:
        flags = []
        if page["match_type"] == "context":
            flags.append("context=one-hop")
        if page["confidence"] in {"low", "unknown"}:
            flags.append(f"confidence={page['confidence']}")
        if page["contested"]:
            flags.append("contested=true")
        flag_text = f" ({', '.join(flags)})" if flags else ""
        lines.extend(
            [
                "",
                f"### {page['title']}{flag_text}",
                "",
                f"- Path: `{page['path']}`",
                f"- Match Type: `{page['match_type']}`",
                f"- Score: `{page['score']}`",
                f"- Primary Score: `{page['primary_score']}`",
                f"- Confidence: `{page['confidence']}`",
                f"- Contested: `{str(page['contested']).lower()}`",
                f"- Profiles: {', '.join(page['profiles']) if page['profiles'] else 'none'}",
                f"- Sources: {', '.join(f'`{source}`' for source in page['sources']) if page['sources'] else 'none'}",
                f"- Reasons: {', '.join(page['reasons']) if page['reasons'] else 'none'}",
                "",
                "#### Summary",
                "",
                page["summary"] or "(no summary)",
                "",
                "#### Excerpt",
                "",
                "```markdown",
                page["excerpt"],
                "```",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument("query", help="Query or task text")
    parser.add_argument("--limit", type=int, default=5, help="Maximum retrieval hits")
    parser.add_argument("--max-chars-per-page", type=int, default=1800, help="Excerpt budget per page")
    parser.add_argument("--no-expand", action="store_true", help="Disable one-hop link expansion")
    parser.add_argument("--profile", help="Filter retrieval to pages declaring this extraction profile")
    parser.add_argument(
        "--include-unprofiled",
        action="store_true",
        help="Include unprofiled pages during profile-filtered retrieval",
    )
    parser.add_argument("--json", action="store_true", help="Print the generated JSON context pack")
    parser.add_argument("--no-write", action="store_true", help="Do not write reports/context-packs files")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.wiki_root)
    try:
        pack = build_context_pack(
            root,
            args.query,
            limit=args.limit,
            max_chars_per_page=args.max_chars_per_page,
            expand_links=not args.no_expand,
            profile=args.profile,
            include_unprofiled=args.include_unprofiled,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    markdown = markdown_context_pack(pack)
    if not args.no_write:
        name = f"context-pack-{slugify(args.query) or 'query'}"
        md_path, json_path = write_report(root, "context-packs", name, markdown, pack)
        pack["report"] = md_path.as_posix()
        if json_path:
            pack["report_json"] = json_path.as_posix()
    if args.json:
        print(json.dumps(pack, ensure_ascii=False, indent=2))
    else:
        print(markdown.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
