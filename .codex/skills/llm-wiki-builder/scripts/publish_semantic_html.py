#!/usr/bin/env python3
"""Publish canonical Markdown wiki pages as clean semantic HTML."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from wiki_lib import (
    build_memory_artifacts,
    markdown_to_semantic_html,
    parse_frontmatter,
    relpath,
    slugify,
    utc_now,
    write_json,
)


def html_page_name(page_path: str) -> str:
    return f"{slugify(Path(page_path).with_suffix('').as_posix())}.html"


def list_items(values: list[str]) -> str:
    if not values:
        return "<li>none</li>"
    return "".join(f"<li>{html.escape(str(value))}</li>" for value in values)


def render_page(page: dict[str, Any], body: str) -> str:
    metadata_rows = {
        "Path": page.get("path", ""),
        "Type": page.get("type", ""),
        "Confidence": page.get("confidence", "unknown"),
        "Contested": str(bool(page.get("contested", False))).lower(),
        "Updated": page.get("updated", ""),
    }
    metadata = "\n".join(
        f"<dt>{html.escape(key)}</dt><dd>{html.escape(str(value))}</dd>" for key, value in metadata_rows.items()
    )
    title = html.escape(str(page.get("title") or page.get("path") or "Untitled"))
    summary = html.escape(str(page.get("summary") or ""))
    attrs = {
        "data-path": page.get("path", ""),
        "data-type": page.get("type", ""),
        "data-confidence": page.get("confidence", "unknown"),
        "data-contested": str(bool(page.get("contested", False))).lower(),
    }
    attr_text = " ".join(f'{key}="{html.escape(str(value), quote=True)}"' for key, value in attrs.items())
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
</head>
<body>
<article {attr_text}>
  <header>
    <p><a href="../index.html">Index</a></p>
    <h1>{title}</h1>
    <p>{summary}</p>
    <dl>
{metadata}
    </dl>
    <section aria-label="Tags">
      <h2>Tags</h2>
      <ul>{list_items(page.get("tags", []))}</ul>
    </section>
    <section aria-label="Aliases">
      <h2>Aliases</h2>
      <ul>{list_items(page.get("aliases", []))}</ul>
    </section>
    <section aria-label="Sources">
      <h2>Sources</h2>
      <ul>{list_items(page.get("sources", []))}</ul>
    </section>
  </header>
  <section data-role="body">
{markdown_to_semantic_html(body)}
  </section>
</article>
</body>
</html>
"""


def render_index(pages: list[dict[str, Any]], generated_at: str) -> str:
    rows = []
    for page in pages:
        href = f"pages/{html_page_name(str(page['path']))}"
        rows.append(
            "<li>"
            f"<a href=\"{href}\" data-path=\"{html.escape(str(page['path']), quote=True)}\">"
            f"{html.escape(str(page.get('title') or page['path']))}</a>"
            f" - {html.escape(str(page.get('summary') or ''))}"
            "</li>"
        )
    listing = "\n".join(rows) if rows else "<li>No compiled pages.</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LLM Wiki</title>
</head>
<body>
<main>
  <header>
    <h1>LLM Wiki</h1>
    <p>Generated at {html.escape(generated_at)} from canonical Markdown pages.</p>
  </header>
  <nav aria-label="Wiki pages">
    <h2>Pages</h2>
    <ul>
{listing}
    </ul>
  </nav>
</main>
</body>
</html>
"""


def publish_html(root: Path, *, clean: bool = False) -> dict[str, Any]:
    out = root / "reports" / "publish" / "html"
    if clean and out.exists():
        shutil.rmtree(out)
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    memory_index, _ = build_memory_artifacts(root)
    pages = [page for page in memory_index.get("pages", []) if isinstance(page, dict)]
    generated_at = utc_now()
    written_pages: list[str] = []
    for page in pages:
        source = root / str(page["path"])
        metadata, body = parse_frontmatter(source.read_text(encoding="utf-8"))
        merged = {**metadata, **page}
        html_path = pages_dir / html_page_name(str(page["path"]))
        html_path.write_text(render_page(merged, body), encoding="utf-8")
        written_pages.append(relpath(html_path, root))
    index_path = out / "index.html"
    index_path.write_text(render_index(pages, generated_at), encoding="utf-8")
    manifest = {
        "schema": "llm-wiki-semantic-html-manifest-v1",
        "generated_at": generated_at,
        "root": root.as_posix(),
        "source": "wiki/**/*.md",
        "index": relpath(index_path, root),
        "pages": written_pages,
        "page_count": len(written_pages),
    }
    write_json(out / "manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument("--clean", action="store_true", help="Remove previous generated HTML before publishing")
    parser.add_argument("--json", action="store_true", help="Print manifest JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = publish_html(Path(args.wiki_root), clean=args.clean)
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(f"published: {manifest['index']}")
        print(f"pages: {manifest['page_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
