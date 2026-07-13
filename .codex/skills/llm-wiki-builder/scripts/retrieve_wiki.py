#!/usr/bin/env python3
"""Retrieve candidate pages from a file-first Markdown LLM wiki."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from wiki_lib import RETRIEVAL_MODE, append_jsonl, confined_output_path, retrieve, utc_now


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument("query", help="Query text")
    parser.add_argument("--limit", type=positive_int, default=5, help="Maximum number of hits to return")
    parser.add_argument("--no-expand", action="store_true", help="Disable one-hop link expansion")
    parser.add_argument("--no-log", action="store_true", help="Disable query-log.jsonl writes")
    parser.add_argument("--profile", help="Filter retrieval to pages declaring this extraction profile")
    parser.add_argument(
        "--include-unprofiled",
        action="store_true",
        help="Include unprofiled pages during profile-filtered retrieval, ranked below profile matches",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.wiki_root)
    try:
        hits = retrieve(
            root,
            args.query,
            limit=args.limit,
            expand_links=not args.no_expand,
            profile=args.profile,
            include_unprofiled=args.include_unprofiled,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    miss = not hits
    log_path = root / "query-log.jsonl"
    if log_path.exists() and not args.no_log:
        try:
            confined_output_path(root, log_path, scope="wiki root")
            seed_pages = [hit["path"] for hit in hits if hit.get("match_type") == "seed"]
            context_pages = [hit["path"] for hit in hits if hit.get("match_type") == "context"]
            append_jsonl(
                log_path,
                {
                    "timestamp": utc_now(),
                    "query": args.query,
                    "selected_pages": [hit["path"] for hit in hits],
                    "seed_pages": seed_pages,
                    "context_pages": context_pages,
                    "miss": miss,
                    "retrieval_mode": RETRIEVAL_MODE,
                    "limit": args.limit,
                    "scores": {hit["path"]: hit["score"] for hit in hits},
                    "primary_scores": {hit["path"]: hit.get("primary_score", 0.0) for hit in hits},
                    "reason_counts": {hit["path"]: hit.get("reason_counts", {}) for hit in hits},
                    **({"profile_id": args.profile} if args.profile else {}),
                },
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    result = {
        "query": args.query,
        "miss": miss,
        "retrieval_mode": RETRIEVAL_MODE,
        "profile_id": args.profile,
        "include_unprofiled": args.include_unprofiled,
        "hits": hits,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if miss:
        print("The wiki lacks sufficient memory for this query.")
        print("Suggested next step: ingest source material or create a compiled wiki page.")
        return 0

    profile_suffix = f" profile={args.profile}" if args.profile else ""
    print(f"query: {args.query}{profile_suffix}")
    for index, hit in enumerate(hits, start=1):
        flags: list[str] = []
        if hit.get("match_type") == "context":
            flags.append("context=one-hop")
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
