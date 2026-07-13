#!/usr/bin/env python3
"""Regression checks for destructive, publication, and context-budget boundaries."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import init_wiki as init_module
from build_context_pack import build_context_pack
from init_wiki import init_wiki, safe_fresh_remove
from publish_mcp_bundle import publish_mcp_bundle
from publish_semantic_html import html_page_name, publish_html
from validate_wiki import validate_wiki
from wiki_lib import markdown_sections, write_report


SCRIPT_DIR = Path(__file__).resolve().parent


def page(title: str, slug: str, body: str) -> str:
    return f"""---
title: {title}
slug: {slug}
created: 2026-07-12
updated: 2026-07-12
type: concept
summary: Deterministic publish safety fixture.
aliases: []
tags: []
sources: []
confidence: medium
contested: false
---

# {title}

{body}
"""


def create_wiki(base: Path) -> Path:
    root = base / "wiki-root"
    init_wiki(root, draft=True)
    return root


class PublishSafetyTests(unittest.TestCase):
    def test_fresh_rejects_temp_root_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_temp = Path(temp_dir) / "system-temp"
            fake_temp.mkdir()
            marker = fake_temp / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            original = init_module.tempfile.gettempdir
            init_module.tempfile.gettempdir = lambda: str(fake_temp)
            try:
                with self.assertRaises(SystemExit):
                    safe_fresh_remove(fake_temp)
            finally:
                init_module.tempfile.gettempdir = original
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_snapshot_rejects_page_symlink_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = create_wiki(base)
            outside = base / "outside-secret.md"
            outside.write_text(page("External", "external", "OUTSIDE_SECRET_CONTENT"), encoding="utf-8")
            linked_page = root / "wiki" / "concepts" / "external.md"
            linked_page.symlink_to(outside)

            validation = validate_wiki(root)
            self.assertEqual(validation["status"], "fail")
            self.assertTrue(any("escapes canonical wiki directory" in error for error in validation["errors"]))
            with self.assertRaises(ValueError):
                publish_mcp_bundle(root, mode="snapshot", clean=True)
            copied = root / "reports" / "publish" / "mcp" / "snapshot" / "wiki" / "concepts" / "external.md"
            self.assertFalse(copied.exists())

    def test_snapshot_rejects_allowlisted_file_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = create_wiki(base)
            outside = base / "outside-glossary.json"
            outside.write_text('{"schema":"llm-wiki-glossary-v1","terms":[]}', encoding="utf-8")
            (root / "glossary.json").symlink_to(outside)

            with self.assertRaises(ValueError):
                publish_mcp_bundle(root, mode="snapshot", clean=True)
            copied = root / "reports" / "publish" / "mcp" / "snapshot" / "glossary.json"
            self.assertFalse(copied.exists())

    def test_report_write_rejects_symlinked_reports_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = create_wiki(base)
            outside = base / "outside-reports"
            outside.mkdir()
            marker = outside / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            shutil.rmtree(root / "reports")
            (root / "reports").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ValueError):
                write_report(root, "health", "health", "must not escape")
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertFalse((outside / "health").exists())

    def test_index_and_query_log_writes_reject_external_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = create_wiki(base)
            (root / "wiki" / "concepts" / "many.md").write_text(
                page("Many", "many", "Many searchable details."), encoding="utf-8"
            )

            outside_index = base / "outside-index.json"
            outside_index.write_text("keep-index", encoding="utf-8")
            (root / "memory-index.json").unlink()
            (root / "memory-index.json").symlink_to(outside_index)
            index_result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "build_memory_index.py"), str(root), "--write"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(index_result.returncode, 2, index_result.stderr)
            self.assertEqual(outside_index.read_text(encoding="utf-8"), "keep-index")

            outside_log = base / "outside-query-log.jsonl"
            outside_log.write_text("keep-query\n", encoding="utf-8")
            (root / "query-log.jsonl").unlink()
            (root / "query-log.jsonl").symlink_to(outside_log)
            query_result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "retrieve_wiki.py"), str(root), "Many"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(query_result.returncode, 2, query_result.stderr)
            self.assertEqual(outside_log.read_text(encoding="utf-8"), "keep-query\n")

    def test_snapshot_is_allowlisted_clean_and_portable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = create_wiki(Path(temp_dir))
            private_page = root / "wiki" / "concepts" / "private.md"
            private_page.write_text(page("Private", "private", "Content removed before snapshot."), encoding="utf-8")
            publish_html(root, clean=True)
            stale_name = html_page_name("wiki/concepts/private.md")
            private_page.unlink()

            (root / "query-log.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-07-12T00:00:00Z",
                        "query": "private user query",
                        "selected_pages": [],
                        "miss": True,
                        "retrieval_mode": "deterministic-file-first",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            context_pack = root / "reports" / "context-packs" / "private.md"
            context_pack.parent.mkdir(parents=True, exist_ok=True)
            context_pack.write_text("private context history", encoding="utf-8")
            (root / "log.md").write_text("private operational history\n", encoding="utf-8")

            manifest = publish_mcp_bundle(root, mode="snapshot", clean=True)
            snapshot = root / "reports" / "publish" / "mcp" / "snapshot"
            self.assertFalse((snapshot / "query-log.jsonl").exists())
            self.assertFalse((snapshot / "log.md").exists())
            self.assertFalse((snapshot / "reports" / "context-packs").exists())
            self.assertFalse((snapshot / "reports" / "publish" / "html" / "pages" / stale_name).exists())
            self.assertNotEqual(manifest.get("root"), root.resolve().as_posix())
            snapshot_html_manifest = json.loads(
                (snapshot / "reports" / "publish" / "html" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertNotEqual(snapshot_html_manifest.get("root"), root.resolve().as_posix())

    def test_html_page_names_are_unique_for_colliding_and_cjk_paths(self) -> None:
        paths = ["wiki/a/b.md", "wiki/a-b.md", "wiki/concepts/检索.md", "wiki/concepts/召回.md"]
        names = [html_page_name(path) for path in paths]
        self.assertEqual(len(names), len(set(names)))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = create_wiki(Path(temp_dir))
            for index, rel in enumerate(paths):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(page(f"Page {index}", f"page-{index}", "Unique output content."), encoding="utf-8")
            manifest = publish_html(root, clean=True)
            self.assertEqual(manifest["page_count"], len(paths))
            self.assertEqual(len(manifest["pages"]), len(set(manifest["pages"])))

    def test_publishers_reject_symlinked_existing_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = create_wiki(base)
            outside_html = base / "outside-index.html"
            outside_html.write_text("keep-html", encoding="utf-8")
            html_out = root / "reports" / "publish" / "html"
            (html_out / "index.html").symlink_to(outside_html)
            with self.assertRaises(ValueError):
                publish_html(root)
            self.assertEqual(outside_html.read_text(encoding="utf-8"), "keep-html")

            outside_manifest = base / "outside-manifest.json"
            outside_manifest.write_text("keep-mcp", encoding="utf-8")
            mcp_out = root / "reports" / "publish" / "mcp"
            (mcp_out / "manifest.json").symlink_to(outside_manifest)
            with self.assertRaises(ValueError):
                publish_mcp_bundle(root)
            self.assertEqual(outside_manifest.read_text(encoding="utf-8"), "keep-mcp")

    def test_html_rewrites_local_links_and_blocks_active_schemes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = create_wiki(Path(temp_dir))
            source = root / "wiki" / "concepts" / "source.md"
            target = root / "wiki" / "concepts" / "target.md"
            source.write_text(
                page("Source", "source", "[Target](target.md) and [unsafe](javascript:void%280%29)."),
                encoding="utf-8",
            )
            target.write_text(page("Target", "target", "Target page content."), encoding="utf-8")
            publish_html(root, clean=True)
            source_html = root / "reports" / "publish" / "html" / "pages" / html_page_name("wiki/concepts/source.md")
            rendered = source_html.read_text(encoding="utf-8")
            self.assertIn(f'href="{html_page_name("wiki/concepts/target.md")}"', rendered)
            self.assertNotIn('href="target.md"', rendered)
            self.assertNotIn("href=\"javascript:", rendered.lower())

    def test_heading_ids_ignore_unrelated_preceding_text_changes(self) -> None:
        before = "# Root\n\nIntro.\n\n## Target\n\nStable body.\n"
        after = "# Root\n\nIntro with substantially more preceding text.\n\n## Target\n\nStable body.\n"
        before_target = next(section for section in markdown_sections(before, "wiki/a.md") if section["heading"] == "Target")
        after_target = next(section for section in markdown_sections(after, "wiki/a.md") if section["heading"] == "Target")
        self.assertEqual(before_target["section_id"], after_target["section_id"])

    def test_context_pack_enforces_aggregate_positive_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = create_wiki(Path(temp_dir))
            body = "\n\n".join(f"## Section {index}\n\n" + ("x" * 100) for index in range(30))
            (root / "wiki" / "concepts" / "many.md").write_text(page("Many", "many", body), encoding="utf-8")
            pack = build_context_pack(root, "Many", limit=1, max_chars_per_page=240, expand_links=False)
            payload = pack["pages"][0]
            used = len(payload["excerpt"]) + sum(len(chunk["excerpt"]) for chunk in payload["chunks"])
            self.assertLessEqual(used, 240)
            self.assertEqual(payload["excerpt_budget_chars"], 240)
            self.assertEqual(payload["excerpt_chars_used"], used)
            self.assertTrue(payload["truncated"])

            for script, arguments in [
                ("retrieve_wiki.py", [str(root), "Many", "--limit", "0"]),
                ("build_context_pack.py", [str(root), "Many", "--limit", "0"]),
                ("build_context_pack.py", [str(root), "Many", "--max-chars-per-page", "0"]),
            ]:
                result = subprocess.run(
                    [sys.executable, str(SCRIPT_DIR / script), *arguments],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, msg=f"{script}: {result.stdout}\n{result.stderr}")


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublishSafetyTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
