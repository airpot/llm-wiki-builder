#!/usr/bin/env python3
"""Build memory-index.json and link-graph.json for an LLM wiki."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiki_lib import append_log, build_memory_artifacts, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument("--write", action="store_true", help="Write generated artifacts to the wiki root")
    parser.add_argument("--json", action="store_true", help="Print full generated artifacts as JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.wiki_root)
    memory_index, link_graph = build_memory_artifacts(root)

    if args.write:
        write_json(root / "memory-index.json", memory_index)
        write_json(root / "link-graph.json", link_graph)
        append_log(root, "rebuilt memory-index.json and link-graph.json.")

    if args.json:
        print(json.dumps({"memory_index": memory_index, "link_graph": link_graph}, ensure_ascii=False, indent=2))
    else:
        print(f"pages: {len(memory_index['pages'])}")
        print(f"links: {len(link_graph['links'])}")
        print("written: yes" if args.write else "written: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
