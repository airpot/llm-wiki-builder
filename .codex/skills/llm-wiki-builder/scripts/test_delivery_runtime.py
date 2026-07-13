#!/usr/bin/env python3
"""Regressions for delivery contracts, runtime output, and remaining audit findings."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from build_context_pack import build_context_pack
from init_wiki import init_wiki
from publish_mcp_bundle import publish_mcp_bundle
from publish_semantic_html import html_page_name, publish_html
from validate_wiki import validate_wiki
from wiki_lib import build_memory_artifacts, markdown_sections


CORE_DIRECTION = {
    "purpose": "Publish deterministic wiki memory to local agents.",
    "primary_users": ["agent", "maintainer"],
    "core_knowledge_targets": ["retrieval behavior"],
    "out_of_scope": ["remote mutation"],
    "landing_granularity": "topic-level",
    "evidence_policy": "source-attributed-claims",
    "conflict_policy": "preserve-contested-claims",
    "success_queries": ["needle runtime"],
}

PROFILE = {
    "schema": "llm-wiki-extraction-profile-v1",
    "profile_id": "core",
    "name": "Core",
    "purpose": "Compile retrieval knowledge.",
    "target_audience": ["agent"],
    "extract_dimensions": ["concepts"],
    "exclude_dimensions": ["off-topic"],
    "page_types": ["concept"],
    "granularity": "topic-level",
    "evidence_policy": "source-attributed-claims",
    "conflict_policy": "preserve-contested-claims",
    "output_roots": ["wiki/concepts"],
    "required_sections_by_type": {},
    "eval_queries": ["needle runtime"],
}


def page(title: str, slug: str, body: str, *, aliases: list[str] | None = None, sources: list[str] | None = None) -> str:
    return f"""---
title: {title}
slug: {slug}
created: 2026-07-12
updated: 2026-07-12
type: concept
summary: {title} fixture.
aliases: {json.dumps(aliases or [], ensure_ascii=False)}
tags: [runtime]
sources: {json.dumps(sources or [], ensure_ascii=False)}
profiles: [core]
confidence: medium
contested: false
---

# {title}

{body}
"""


def normal_wiki(base: Path) -> Path:
    root = base / "wiki-root"
    init_wiki(root, core_direction=CORE_DIRECTION, profiles=[PROFILE], draft=False)
    return root


def all_text(root: Path) -> str:
    values: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            try:
                values.append(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                continue
    return "\n".join(values)


class DeliveryRuntimeTests(unittest.TestCase):
    def test_html_clean_rejects_symlinked_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = normal_wiki(base)
            outside = base / "outside"
            outside.mkdir()
            marker = outside / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            reports = root / "reports"
            shutil.rmtree(reports)
            reports.symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ValueError):
                publish_html(root, clean=True)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_snapshot_privacy_is_transitive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = normal_wiki(Path(temp_dir))
            private_root = (Path(temp_dir) / "private-sources").resolve().as_posix()
            private_source = f"{private_root}/source.pdf"
            secret_query = "私密MixedQuery_NEVER_PUBLISH"
            target = root / "wiki" / "concepts" / "privacy.md"
            target.write_text(
                page("Privacy", "privacy", "Published content.", sources=[private_source]),
                encoding="utf-8",
            )
            (root / "query-log.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-07-12T00:00:00Z",
                        "query": secret_query,
                        "selected_pages": [],
                        "miss": True,
                        "retrieval_mode": "deterministic-file-first",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            publish_mcp_bundle(root, mode="snapshot", clean=True)
            bundle_text = all_text(root / "reports" / "publish" / "mcp")
            self.assertNotIn(secret_query, bundle_text)
            self.assertNotIn(private_root, bundle_text)
            self.assertNotIn(root.resolve().as_posix(), bundle_text)

    def test_context_pack_selects_query_relevant_section(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = normal_wiki(Path(temp_dir))
            body = "# Localized\n\n" + "\n\n".join(
                [
                    "## Introduction\n\nGeneral filler " + ("x" * 300),
                    "## Background\n\nMore generic filler " + ("y" * 300),
                    "## Needle Runtime\n\nNEEDLE_RUNTIME_EXACT appears only in this late section.",
                ]
            )
            (root / "wiki" / "concepts" / "localized.md").write_text(
                page("Localized", "localized", body), encoding="utf-8"
            )
            pack = build_context_pack(
                root,
                "NEEDLE_RUNTIME_EXACT",
                limit=1,
                max_chars_per_page=260,
                max_chunks_per_page=1,
                expand_links=False,
            )
            self.assertFalse(pack["miss"])
            chunks = pack["pages"][0]["chunks"]
            self.assertEqual(len(chunks), 1)
            self.assertIn("NEEDLE_RUNTIME_EXACT", chunks[0]["excerpt"])
            self.assertEqual(chunks[0]["heading"], "Needle Runtime")

    def test_duplicate_identifiers_fail_validation_and_index_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = normal_wiki(Path(temp_dir))
            first = root / "wiki" / "concepts" / "first.md"
            second = root / "wiki" / "concepts" / "second.md"
            first.write_text(page("First", "first", "One.", aliases=["Shared Alias"]), encoding="utf-8")
            second.write_text(page("Second", "second", "Two.", aliases=["shared alias"]), encoding="utf-8")

            validation = validate_wiki(root)
            self.assertEqual(validation["status"], "fail")
            self.assertTrue(any("identifier collision" in item for item in validation["errors"]))
            with self.assertRaises(ValueError):
                build_memory_artifacts(root)

    def test_html_fragment_links_use_generated_heading_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = normal_wiki(Path(temp_dir))
            source = root / "wiki" / "concepts" / "source.md"
            target = root / "wiki" / "concepts" / "target.md"
            source.write_text(page("Source", "source", "[Details](target.md#Details)"), encoding="utf-8")
            target_body = "Target body.\n\n## Details\n\nStable details."
            target.write_text(page("Target", "target", target_body), encoding="utf-8")

            publish_html(root, clean=True)
            target_anchor = next(
                section["section_id"]
                for section in markdown_sections(target.read_text(encoding="utf-8").split("\n---\n", 1)[1], "wiki/concepts/target.md")
                if section["heading"] == "Details"
            )
            rendered = (
                root / "reports" / "publish" / "html" / "pages" / html_page_name("wiki/concepts/source.md")
            ).read_text(encoding="utf-8")
            self.assertIn(f'href="{html_page_name("wiki/concepts/target.md")}#{target_anchor}"', rendered)
            self.assertNotIn("#Details\"", rendered)

    def test_normal_initialization_upgrades_known_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "wiki-root"
            init_wiki(root, draft=True)
            result = init_wiki(root, core_direction=CORE_DIRECTION, profiles=[PROFILE], draft=False)
            schema = (root / "SCHEMA.md").read_text(encoding="utf-8")
            self.assertNotIn("- draft", schema)
            self.assertNotIn("- unspecified", schema)
            self.assertIn("SCHEMA.md", result.get("upgraded", []))
            self.assertTrue((root / "delivery-contract.json").is_file())

    def test_normal_initialization_rejects_conflicting_draft_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "wiki-root"
            init_wiki(root, draft=True)
            schema_path = root / "SCHEMA.md"
            schema_path.write_text(schema_path.read_text(encoding="utf-8") + "\nUser-owned schema note.\n", encoding="utf-8")
            untouched_dir = root / "wiki" / "entities"
            untouched_dir.rmdir()
            with self.assertRaises(SystemExit):
                init_wiki(root, core_direction=CORE_DIRECTION, profiles=[PROFILE], draft=False)
            self.assertFalse(untouched_dir.exists())

    def test_normal_reinitialization_rejects_conflicting_confirmed_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = normal_wiki(Path(temp_dir))
            schema_path = root / "SCHEMA.md"
            profile_path = root / "profiles" / "core.json"
            log_path = root / "log.md"
            original_schema = schema_path.read_text(encoding="utf-8")
            original_profile = profile_path.read_text(encoding="utf-8")
            original_log = log_path.read_text(encoding="utf-8")

            repeated = init_wiki(root, core_direction=CORE_DIRECTION, profiles=[PROFILE], draft=False)
            self.assertIn("SCHEMA.md", repeated["kept"])
            self.assertIn("profiles/core.json", repeated["kept"])

            changed_direction = {**CORE_DIRECTION, "purpose": "A conflicting confirmed purpose."}
            with self.assertRaisesRegex(SystemExit, "SCHEMA.md conflicts"):
                init_wiki(root, core_direction=changed_direction, profiles=[PROFILE], draft=False)
            self.assertEqual(schema_path.read_text(encoding="utf-8"), original_schema)
            self.assertEqual(log_path.read_text(encoding="utf-8"), original_log)

            changed_profile = {**PROFILE, "purpose": "A conflicting confirmed profile."}
            with self.assertRaisesRegex(SystemExit, "profile core conflicts"):
                init_wiki(root, core_direction=CORE_DIRECTION, profiles=[changed_profile], draft=False)
            self.assertEqual(profile_path.read_text(encoding="utf-8"), original_profile)
            self.assertEqual(log_path.read_text(encoding="utf-8"), original_log)

    def test_normal_initialization_rejects_duplicate_direct_profiles_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "wiki-root"
            duplicate = {**PROFILE, "purpose": "Conflicting duplicate."}
            with self.assertRaises(SystemExit):
                init_wiki(root, core_direction=CORE_DIRECTION, profiles=[PROFILE, duplicate], draft=False)
            self.assertFalse(root.exists())

    def test_fresh_validates_confirmed_inputs_before_removing_temp_wiki(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "wiki-root"
            root.mkdir()
            marker = root / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            invalid_direction = {**CORE_DIRECTION, "purpose": ""}
            with self.assertRaises(SystemExit):
                init_wiki(root, fresh=True, core_direction=invalid_direction, profiles=[PROFILE], draft=False)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_initialization_rejects_broken_output_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "wiki-root"
            root.mkdir()
            outside = base / "outside-schema.md"
            (root / "SCHEMA.md").symlink_to(outside)
            with self.assertRaises(ValueError):
                init_wiki(root, draft=True)
            self.assertFalse(outside.exists())

    def test_default_delivery_generates_executable_mcp_and_thin_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = normal_wiki(Path(temp_dir))
            canonical_marker = "CANONICAL_BODY_MUST_NOT_BE_COPIED_TO_SKILL"
            (root / "wiki" / "concepts" / "runtime.md").write_text(
                page("Runtime", "runtime", canonical_marker), encoding="utf-8"
            )
            contract = json.loads((root / "delivery-contract.json").read_text(encoding="utf-8"))
            self.assertEqual(contract["publish_target"], "mcp-skill")
            self.assertEqual(contract["mcp_runtime"], "executable")
            self.assertEqual(contract["transport"], "stdio")
            self.assertEqual(contract["publication_mode"], "snapshot")

            manifest = publish_mcp_bundle(root, clean=True)
            bundle = root / "reports" / "publish" / "mcp"
            self.assertEqual(manifest["mode"], "snapshot")
            skill_root = next((bundle / "skills").iterdir())
            for rel in ("server.py", "requirements.txt"):
                self.assertTrue((bundle / rel).is_file(), rel)
            for rel in ("SKILL.md", "agents/openai.yaml"):
                self.assertTrue((skill_root / rel).is_file(), rel)
            config = json.loads((bundle / "server-config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["status"], "executable")
            self.assertTrue(config["adapter"]["implemented"])
            self.assertTrue(config["policy"]["read_only"])
            self.assertEqual(config["transport"], "stdio")
            self.assertIn("mcp>=1.28,<2", (bundle / "requirements.txt").read_text(encoding="utf-8"))
            skill_text = all_text(skill_root)
            self.assertIn("wiki_search", skill_text)
            self.assertIn("wiki_read", skill_text)
            self.assertIn("cite", skill_text.lower())
            self.assertNotIn(canonical_marker, skill_text)
            self.assertNotIn("llm-wiki-builder/scripts", skill_text)

    def test_generated_server_loads_and_executes_read_only_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = normal_wiki(Path(temp_dir))
            (root / "wiki" / "concepts" / "runtime.md").write_text(
                page("Runtime", "runtime", "## Needle\n\nExecutable runtime needle.\n\n[[Context Page]]"),
                encoding="utf-8",
            )
            (root / "wiki" / "concepts" / "context.md").write_text(
                page("Context Page", "context-page", "Linked supporting context.").replace("tags: [runtime]", "tags: []"),
                encoding="utf-8",
            )
            (root / "glossary.json").write_text(
                json.dumps(
                    {
                        "schema": "llm-wiki-glossary-v1",
                        "terms": [{"canonical": "runtime", "aliases": ["runtime", "运行时"]}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            publish_mcp_bundle(root, clean=True)
            server_path = root / "reports" / "publish" / "mcp" / "server.py"
            compile(server_path.read_text(encoding="utf-8"), str(server_path), "exec")

            class FakeFastMCP:
                def __init__(self, _name: str) -> None:
                    self.transport = None

                def tool(self):
                    return lambda function: function

                def resource(self, _uri: str):
                    return lambda function: function

                def run(self, *, transport: str) -> None:
                    self.transport = transport

            fake_modules = {
                "mcp": types.ModuleType("mcp"),
                "mcp.server": types.ModuleType("mcp.server"),
                "mcp.server.fastmcp": types.ModuleType("mcp.server.fastmcp"),
            }
            fake_modules["mcp.server.fastmcp"].FastMCP = FakeFastMCP
            previous = {name: sys.modules.get(name) for name in fake_modules}
            sys.modules.update(fake_modules)
            try:
                spec = importlib.util.spec_from_file_location("generated_wiki_server", server_path)
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader if spec else None)
                module = importlib.util.module_from_spec(spec)
                assert spec and spec.loader
                spec.loader.exec_module(module)
                hits = module.wiki_search("运行时", k=2)
                self.assertEqual(hits["hits"][0]["path"], "wiki/concepts/runtime.md")
                self.assertEqual(hits["hits"][1]["match_type"], "context")
                self.assertEqual(hits["hits"][1]["path"], "wiki/concepts/context.md")
                read = module.wiki_read("runtime", "markdown")
                self.assertIn("Executable runtime needle", read["content"])
                pack = module.wiki_context_pack(
                    "runtime needle", k=2, excerpt_budget_chars=120, max_chunks_per_page=1
                )
                self.assertFalse(pack["miss"])
                self.assertLessEqual(pack["pages"][0]["excerpt_chars_used"], 120)
                self.assertTrue(pack["pages"][0]["chunks"])
                self.assertTrue(pack["context_pages"])
                self.assertTrue(pack["options"]["expand_links"])
                self.assertTrue(
                    any("runtime needle" in chunk["excerpt"].lower() for chunk in pack["pages"][0]["chunks"])
                )
                self.assertIn(module.wiki_quality_report()["readiness_level"], {"ready", "degraded", "unsafe"})
                with self.assertRaises(ValueError):
                    module.wiki_read("../outside", "markdown")
                (server_path.parent / "snapshot" / "glossary.json").write_text("{broken", encoding="utf-8")
                (server_path.parent / "snapshot" / "glossary.jsonl").write_bytes(b"\xff")
                fallback_hits = module.wiki_search("runtime", k=1)
                self.assertEqual(fallback_hits["hits"][0]["path"], "wiki/concepts/runtime.md")
            finally:
                for name, prior in previous.items():
                    if prior is None:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = prior

    def test_contract_only_readme_does_not_claim_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = normal_wiki(Path(temp_dir))
            contract_path = root / "delivery-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["mcp_runtime"] = "contract-only"
            contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

            publish_mcp_bundle(root, clean=True)
            bundle = root / "reports" / "publish" / "mcp"
            readme = (bundle / "README.md").read_text(encoding="utf-8")
            config = json.loads((bundle / "server-config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["status"], "contract-only")
            self.assertFalse((bundle / "server.py").exists())
            self.assertFalse((bundle / "requirements.txt").exists())
            self.assertIn("contract-only", readme)
            self.assertNotIn("Install `requirements.txt`", readme)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DeliveryRuntimeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
