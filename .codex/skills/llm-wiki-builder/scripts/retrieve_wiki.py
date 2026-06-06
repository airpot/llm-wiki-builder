#!/usr/bin/env python3
"""Retrieve candidate pages from a file-first Markdown LLM wiki."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiki_lib import RETRIEVAL_MODE, append_jsonl, retrieve, utc_now


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument("query", help="Query text")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of hits to return")
    parser.add_argument("--no-expand", action="store_true", help="Disable one-hop link expansion")
    parser.add_argument("--no-log", action="store_true", help="Disable query-log.jsonl writes")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.wiki_root)
    hits = retrieve(root, args.query, limit=args.limit, expand_links=not args.no_expand)
    miss = not hits
    log_path = root / "query-log.jsonl"
    if log_path.exists() and not args.no_log:
        append_jsonl(
            log_path,
            {
                "timestamp": utc_now(),
                "query": args.query,
                "selected_pages": [hit["path"] for hit in hits],
                "miss": miss,
                "retrieval_mode": RETRIEVAL_MODE,
                "limit": args.limit,
                "scores": {hit["path"]: hit["score"] for hit in hits},
            },
        )

    result = {
        "query": args.query,
        "miss": miss,
        "retrieval_mode": RETRIEVAL_MODE,
        "hits": hits,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if miss:
        print("The wiki lacks sufficient memory for this query.")
        print("Suggested next step: ingest source material or create a compiled wiki page.")
        return 0

    print(f"query: {args.query}")
    for index, hit in enumerate(hits, start=1):
        flags: list[str] = []
        if hit.get("confidence") in {"low", "unknown"}:
            flags.append(f"confidence={hit.get('confidence')}")
        if hit.get("contested"):
            flags.append("contested=true")
        suffix = f" ({', '.join(flags)})" if flags else ""
        print(f"{index}. {hit['title']} [{hit['path']}] score={hit['score']}{suffix}")
        if hit.get("summary"):
            print(f"   {hit['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
