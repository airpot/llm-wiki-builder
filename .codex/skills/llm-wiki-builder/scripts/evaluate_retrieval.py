#!/usr/bin/env python3
"""Evaluate deterministic retrieval against retrieval-evals.jsonl."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from wiki_lib import page_matches_identifier, read_jsonl, retrieve, write_report


def evaluate_case(root: Path, case: dict[str, Any], limit: int) -> dict[str, Any]:
    hits = retrieve(root, case["query"], limit=limit, expand_links=True)
    expected_pages = [str(item) for item in case.get("expected_pages", [])]
    forbidden_pages = [str(item) for item in case.get("forbidden_pages", [])]
    matched_expected: list[str] = []
    forbidden_hits: list[str] = []

    for expected in expected_pages:
        if any(page_matches_identifier(hit, expected) for hit in hits):
            matched_expected.append(expected)
    for forbidden in forbidden_pages:
        if any(page_matches_identifier(hit, forbidden) for hit in hits):
            forbidden_hits.append(forbidden)

    missing_expected = [item for item in expected_pages if item not in matched_expected]
    unexpected_top_hit = None
    if hits and expected_pages and not any(page_matches_identifier(hits[0], expected) for expected in expected_pages):
        unexpected_top_hit = hits[0]["path"]

    passed = not missing_expected and not forbidden_hits
    return {
        "id": case["id"],
        "query": case["query"],
        "passed": passed,
        "hits": hits,
        "expected_pages": expected_pages,
        "matched_expected": matched_expected,
        "missing_expected": missing_expected,
        "forbidden_hits": forbidden_hits,
        "unexpected_top_hit": unexpected_top_hit,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of hits per eval case")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    parser.add_argument("--no-report", action="store_true", help="Do not write reports/retrieval output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.wiki_root)
    cases, errors = read_jsonl(root / "retrieval-evals.jsonl")
    if errors:
        for error in errors:
            print(f"error: {error}")
        return 1

    invalid: list[str] = []
    valid_cases: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case.get("id"), str) or not isinstance(case.get("query"), str) or not isinstance(case.get("expected_pages"), list):
            invalid.append(f"case {index}: requires id, query, and expected_pages")
        elif not case["expected_pages"]:
            invalid.append(f"case {case['id']}: expected_pages must not be empty")
        else:
            valid_cases.append(case)
    if invalid:
        for item in invalid:
            print(f"error: {item}")
        return 1

    results = [evaluate_case(root, case, args.limit) for case in valid_cases]
    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    hit_rate = (passed / total) if total else 0.0
    missing_expected = {result["id"]: result["missing_expected"] for result in results if result["missing_expected"]}
    unexpected_top_hits = {result["id"]: result["unexpected_top_hit"] for result in results if result["unexpected_top_hit"]}
    forbidden_hits = {result["id"]: result["forbidden_hits"] for result in results if result["forbidden_hits"]}
    report = {
        "cases": total,
        "passed": passed,
        "hit_rate": hit_rate,
        "missing_expected": missing_expected,
        "unexpected_top_hits": unexpected_top_hits,
        "forbidden_hits": forbidden_hits,
        "inputs": "retrieval-evals.jsonl",
        "results": results,
    }

    if not args.no_report:
        markdown = [
            "# Retrieval Evaluation Report",
            "",
            f"- Cases: {total}",
            f"- Passed: {passed}",
            f"- Hit rate: {hit_rate:.3f}",
            "",
            "## Missing Expected Pages",
        ]
        if missing_expected:
            for case_id, missing in missing_expected.items():
                markdown.append(f"- {case_id}: {', '.join(missing)}")
        else:
            markdown.append("- None")
        markdown.append("")
        markdown.append("## Unexpected Top Hits")
        if unexpected_top_hits:
            for case_id, hit in unexpected_top_hits.items():
                markdown.append(f"- {case_id}: {hit}")
        else:
            markdown.append("- None")
        md_path, json_path = write_report(root, "retrieval", "retrieval-eval", "\n".join(markdown), report)
        report["report"] = md_path.as_posix()
        if json_path:
            report["report_json"] = json_path.as_posix()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"cases: {total}")
        print(f"passed: {passed}")
        print(f"hit_rate: {hit_rate:.3f}")
        print(f"missing_expected: {len(missing_expected)}")
        print(f"unexpected_top_hits: {len(unexpected_top_hits)}")
    return 0 if not missing_expected and not forbidden_hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
