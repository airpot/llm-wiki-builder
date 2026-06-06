#!/usr/bin/env python3
"""Initialize a file-first Markdown LLM wiki."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from wiki_lib import REQUIRED_DIRS, REQUIRED_FILES, build_memory_artifacts, today, utc_now, write_json


TEMPLATES = {
    "SCHEMA.md": "schema.md.tmpl",
    "index.md": "index.md.tmpl",
    "log.md": "log.md.tmpl",
}


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def render_template(name: str, values: dict[str, str]) -> str:
    template = skill_root() / "assets" / "templates" / name
    text = template.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def safe_fresh_remove(root: Path) -> None:
    if not root.exists():
        return
    temp_root = Path(tempfile.gettempdir()).resolve()
    resolved = root.resolve()
    if temp_root not in resolved.parents and resolved != temp_root:
        raise SystemExit("--fresh may only remove targets under the system temp directory")
    shutil.rmtree(root)


def write_missing(path: Path, text: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def init_wiki(root: Path, fresh: bool = False) -> dict[str, list[str]]:
    if fresh:
        safe_fresh_remove(root)
    root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    kept: list[str] = []

    for rel in REQUIRED_DIRS:
        path = root / rel
        if path.exists():
            kept.append(rel + "/")
        else:
            path.mkdir(parents=True, exist_ok=True)
            created.append(rel + "/")

    values = {
        "created": today(),
        "timestamp": utc_now(),
    }
    for rel, template_name in TEMPLATES.items():
        path = root / rel
        if write_missing(path, render_template(template_name, values)):
            created.append(rel)
        else:
            kept.append(rel)

    memory_index, link_graph = build_memory_artifacts(root)
    json_defaults = {
        "memory-index.json": memory_index,
        "link-graph.json": link_graph,
    }
    for rel, data in json_defaults.items():
        path = root / rel
        if path.exists():
            kept.append(rel)
        else:
            write_json(path, data)
            created.append(rel)

    for rel in ("query-log.jsonl", "retrieval-evals.jsonl"):
        path = root / rel
        if write_missing(path, ""):
            created.append(rel)
        else:
            kept.append(rel)

    for rel in REQUIRED_FILES:
        if not (root / rel).exists():
            raise SystemExit(f"failed to create required file: {rel}")

    return {"created": created, "kept": kept}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Remove and recreate the target only when it is under the system temp directory",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = init_wiki(Path(args.wiki_root), fresh=args.fresh)
    print(f"initialized wiki: {args.wiki_root}")
    print(f"created: {len(result['created'])}")
    print(f"kept: {len(result['kept'])}")
    for rel in result["created"]:
        print(f"  + {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
