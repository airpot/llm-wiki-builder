#!/usr/bin/env python3
"""Publish canonical Markdown wiki pages as clean semantic HTML."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

sys.dont_write_bytecode = True

from wiki_lib import (
    build_memory_artifacts,
    confined_output_path,
    confined_output_tree,
    confined_source_path,
    markdown_to_semantic_html,
    parse_frontmatter,
    relpath,
    safe_html_link_target,
    section_index,
    slugify,
    source_body_hash,
    utc_now,
    write_json,
)


def html_page_name(page_path: str) -> str:
    stem = Path(page_path).with_suffix("").as_posix()
    return f"{slugify(stem)}-{source_body_hash(page_path)[:10]}.html"


def list_items(values: list[str]) -> str:
    if not values:
        return "<li>none</li>"
    return "".join(f"<li>{html.escape(str(value))}</li>" for value in values)


def json_script_payload(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")


def render_page(page: dict[str, Any], body: str, link_rewriter: Callable[[str], str | None] | None = None) -> str:
    sections = section_index(body, str(page.get("path", "")))
    page_metadata = {
        "schema": "llm-wiki-html-page-metadata-v1",
        "path": page.get("path", ""),
        "title": page.get("title", ""),
        "summary": page.get("summary", ""),
        "type": page.get("type", ""),
        "confidence": page.get("confidence", "unknown"),
        "contested": bool(page.get("contested", False)),
        "profiles": page.get("profiles", []),
        "tags": page.get("tags", []),
        "aliases": page.get("aliases", []),
        "sources": page.get("sources", []),
        "content_hash": source_body_hash(body),
        "section_index": sections,
    }
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
        "data-page-path": page.get("path", ""),
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
  <script type="application/json" id="llm-wiki-page-metadata">{json_script_payload(page_metadata)}</script>
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
  <section data-role="body" data-page-path="{html.escape(str(page.get('path', '')), quote=True)}" data-confidence="{html.escape(str(page.get('confidence', 'unknown')), quote=True)}" data-contested="{str(bool(page.get('contested', False))).lower()}">
{markdown_to_semantic_html(body, page_path=str(page.get("path", "")), metadata=page, link_rewriter=link_rewriter)}
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
    root = root.resolve()
    out = root / "reports" / "publish" / "html"
    confined_output_tree(root, out, scope="wiki root")
    if clean and out.exists():
        shutil.rmtree(out)
    pages_dir = out / "pages"
    confined_output_path(root, pages_dir, scope="wiki root")
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    memory_index, _ = build_memory_artifacts(root)
    pages = [page for page in memory_index.get("pages", []) if isinstance(page, dict)]
    page_names = {str(page["path"]): html_page_name(str(page["path"])) for page in pages}
    if len(page_names) != len(set(page_names.values())):
        raise ValueError("semantic HTML page-name collision")

    fragment_maps: dict[str, dict[str, str]] = {}
    for page in pages:
        page_path = str(page["path"])
        source = root / page_path
        confined_source_path(root / "wiki", source, scope="canonical wiki directory")
        _, body = parse_frontmatter(source.read_text(encoding="utf-8"))
        fragment_map: dict[str, str] = {}
        for section in section_index(body, page_path):
            anchor = str(section["section_id"])
            heading = str(section["heading"])
            for key in {anchor, heading, slugify(heading)}:
                normalized = key.strip().lower()
                if normalized and normalized != "untitled":
                    fragment_map.setdefault(normalized, anchor)
        fragment_maps[page_path] = fragment_map

    def rewrite_link(source_page: str, target: str) -> str | None:
        safe_target = safe_html_link_target(target)
        if safe_target is None:
            return None
        if not safe_target.startswith("#") and ":" in safe_target.split("/", 1)[0]:
            return safe_target
        target_path, separator, fragment = safe_target.partition("#")
        if target_path:
            source = root / source_page
            candidate = source.parent / target_path
            try:
                resolved = confined_source_path(root / "wiki", candidate, scope="canonical wiki directory")
                target_rel = resolved.relative_to(root).as_posix()
            except ValueError:
                return None
        else:
            target_rel = source_page
        generated_name = page_names.get(target_rel)
        if not generated_name:
            return None
        if separator:
            decoded = unquote(fragment).strip().lower()
            anchor = fragment_maps.get(target_rel, {}).get(decoded)
            if not anchor:
                slug = slugify(decoded)
                anchor = fragment_maps.get(target_rel, {}).get(slug) if slug != "untitled" else None
            if not anchor:
                return None
            if not target_path:
                return f"#{anchor}"
            return f"{generated_name}#{anchor}"
        return generated_name

    generated_at = utc_now()
    written_pages: list[str] = []
    page_details: list[dict[str, Any]] = []
    for page in pages:
        source = root / str(page["path"])
        confined_source_path(root / "wiki", source, scope="canonical wiki directory")
        metadata, body = parse_frontmatter(source.read_text(encoding="utf-8"))
        merged = {**metadata, **page}
        html_path = pages_dir / page_names[str(page["path"])]
        html_path.write_text(
            render_page(
                merged,
                body,
                link_rewriter=lambda target, source_page=str(page["path"]): rewrite_link(source_page, target),
            ),
            encoding="utf-8",
        )
        written_pages.append(relpath(html_path, root))
        sections = section_index(body, str(page["path"]))
        page_details.append(
            {
                "path": str(page["path"]),
                "html_path": relpath(html_path, root),
                "title": str(merged.get("title") or page["path"]),
                "confidence": str(merged.get("confidence") or "unknown"),
                "contested": bool(merged.get("contested", False)),
                "content_hash": source_body_hash(body),
                "section_count": len(sections),
                "sections": sections,
            }
        )
    index_path = out / "index.html"
    index_path.write_text(render_index(pages, generated_at), encoding="utf-8")
    manifest = {
        "schema": "llm-wiki-semantic-html-manifest-v1",
        "generated_at": generated_at,
        "root": root.as_posix(),
        "source": "wiki/**/*.md",
        "index": relpath(index_path, root),
        "pages": written_pages,
        "page_details": page_details,
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
    try:
        manifest = publish_html(Path(args.wiki_root), clean=args.clean)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(f"published: {manifest['index']}")
        print(f"pages: {manifest['page_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
