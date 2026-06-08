#!/usr/bin/env python3
"""Evaluate deterministic retrieval against retrieval-evals.jsonl."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from wiki_lib import load_profiles, page_matches_identifier, read_jsonl, retrieve, write_report


def first_matching_rank(hits: list[dict[str, Any]], identifier: str) -> int | None:
    for index, hit in enumerate(hits, start=1):
        if page_matches_identifier(hit, identifier):
            return index
    return None


def discounted_gain(rank: int) -> float:
    return 1.0 / math.log2(rank + 1)


def evaluate_case(root: Path, case: dict[str, Any], limit: int) -> dict[str, Any]:
    profile_id = case.get("profile_id")
    hits = retrieve(root, case["query"], limit=limit, expand_links=True, profile=profile_id)
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

    ranked_expected = {expected: first_matching_rank(hits, expected) for expected in expected_pages}
    expected_ranks = [rank for rank in ranked_expected.values() if rank is not None]
    first_expected_rank = min(expected_ranks) if expected_ranks else None
    relevant_hits = len(expected_ranks)
    ideal_relevant = min(len(expected_pages), limit)
    dcg = sum(discounted_gain(rank) for rank in expected_ranks)
    ideal_dcg = sum(discounted_gain(rank) for rank in range(1, ideal_relevant + 1))
    metrics = {
        "recall_at_k": (relevant_hits / len(expected_pages)) if expected_pages else 0.0,
        "precision_at_k": relevant_hits / limit if limit else 0.0,
        "mrr_at_k": (1.0 / first_expected_rank) if first_expected_rank else 0.0,
        "ndcg_at_k": (dcg / ideal_dcg) if ideal_dcg else 0.0,
    }
    missing_expected = [item for item in expected_pages if item not in matched_expected]
    unexpected_top_hit = None
    if hits and expected_pages and not any(page_matches_identifier(hits[0], expected) for expected in expected_pages):
        unexpected_top_hit = hits[0]["path"]

    passed = not missing_expected and not forbidden_hits
    return {
        "id": case["id"],
        "query": case["query"],
        "profile_id": profile_id,
        "passed": passed,
        "hits": hits,
        "expected_pages": expected_pages,
        "matched_expected": matched_expected,
        "missing_expected": missing_expected,
        "forbidden_hits": forbidden_hits,
        "ranked_expected": ranked_expected,
        "first_expected_rank": first_expected_rank,
        "metrics": metrics,
        "unexpected_top_hit": unexpected_top_hit,
    }


def average_metric(results: list[dict[str, Any]], name: str) -> float:
    if not results:
        return 0.0
    return sum(float(result.get("metrics", {}).get(name, 0.0)) for result in results) / len(results)


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
    profiles, profile_errors = load_profiles(root)
    if profile_errors:
        for error in profile_errors:
            print(f"error: {error}")
        return 1
    for index, case in enumerate(cases, start=1):
        if not isinstance(case.get("id"), str) or not isinstance(case.get("query"), str) or not isinstance(case.get("expected_pages"), list):
            invalid.append(f"case {index}: requires id, query, and expected_pages")
        elif not case["expected_pages"]:
            invalid.append(f"case {case['id']}: expected_pages must not be empty")
        elif "profile_id" in case and (not isinstance(case.get("profile_id"), str) or not case.get("profile_id")):
            invalid.append(f"case {case['id']}: profile_id must be a non-empty string when present")
        elif case.get("profile_id") and case.get("profile_id") not in profiles:
            invalid.append(f"case {case['id']}: unknown profile_id {case.get('profile_id')}")
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
        "profiles": sorted({str(result.get("profile_id")) for result in results if result.get("profile_id")}),
        "metrics": {
            "recall_at_k": average_metric(results, "recall_at_k"),
            "precision_at_k": average_metric(results, "precision_at_k"),
            "mrr_at_k": average_metric(results, "mrr_at_k"),
            "ndcg_at_k": average_metric(results, "ndcg_at_k"),
            "k": args.limit,
        },
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
            f"- Profiles: {', '.join(report['profiles']) if report['profiles'] else 'none'}",
            f"- Recall@{args.limit}: {report['metrics']['recall_at_k']:.3f}",
            f"- Precision@{args.limit}: {report['metrics']['precision_at_k']:.3f}",
            f"- MRR@{args.limit}: {report['metrics']['mrr_at_k']:.3f}",
            f"- nDCG@{args.limit}: {report['metrics']['ndcg_at_k']:.3f}",
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
        print(f"recall_at_{args.limit}: {report['metrics']['recall_at_k']:.3f}")
        print(f"precision_at_{args.limit}: {report['metrics']['precision_at_k']:.3f}")
        print(f"mrr_at_{args.limit}: {report['metrics']['mrr_at_k']:.3f}")
        print(f"ndcg_at_{args.limit}: {report['metrics']['ndcg_at_k']:.3f}")
        print(f"missing_expected: {len(missing_expected)}")
        print(f"unexpected_top_hits: {len(unexpected_top_hits)}")
    return 0 if not missing_expected and not forbidden_hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
