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


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def first_matching_rank(hits: list[dict[str, Any]], identifier: str) -> int | None:
    for index, hit in enumerate(hits, start=1):
        if page_matches_identifier(hit, identifier):
            return index
    return None


def first_matching_hit(hits: list[dict[str, Any]], identifier: str) -> dict[str, Any] | None:
    for hit in hits:
        if page_matches_identifier(hit, identifier):
            return hit
    return None


def discounted_gain(rank: int) -> float:
    return 1.0 / math.log2(rank + 1)


def evaluate_case(root: Path, case: dict[str, Any], limit: int) -> dict[str, Any]:
    profile_id = case.get("profile_id")
    hits = retrieve(root, case["query"], limit=limit, expand_links=True, profile=profile_id)
    expected_pages = [str(item) for item in case.get("expected_pages", [])]
    forbidden_pages = [str(item) for item in case.get("forbidden_pages", [])]
    expect_miss = bool(case.get("expect_miss", False))
    require_seed_hit = bool(case.get("require_seed_hit", False))
    allow_forbidden_context = bool(case.get("allow_forbidden_context", False))
    min_score = case.get("min_score")
    matched_expected: list[str] = []
    forbidden_hits: list[str] = []
    low_score_hits: dict[str, float] = {}
    context_only_expected: list[str] = []

    for expected in expected_pages:
        hit = first_matching_hit(hits, expected)
        if hit:
            matched_expected.append(expected)
            if require_seed_hit and hit.get("match_type") != "seed":
                context_only_expected.append(expected)
            if isinstance(min_score, (int, float)) and float(hit.get("score", 0.0)) < float(min_score):
                low_score_hits[expected] = float(hit.get("score", 0.0))
    for forbidden in forbidden_pages:
        hit = first_matching_hit(hits, forbidden)
        if hit and (hit.get("match_type") == "seed" or not allow_forbidden_context):
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

    expected_miss_failed = expect_miss and bool(hits)
    passed = (
        not missing_expected
        and not forbidden_hits
        and not low_score_hits
        and not context_only_expected
        and not expected_miss_failed
    )
    return {
        "id": case["id"],
        "query": case["query"],
        "profile_id": profile_id,
        "expect_miss": expect_miss,
        "require_seed_hit": require_seed_hit,
        "min_score": min_score,
        "allow_forbidden_context": allow_forbidden_context,
        "tags": case.get("tags", []),
        "passed": passed,
        "hits": hits,
        "expected_pages": expected_pages,
        "matched_expected": matched_expected,
        "missing_expected": missing_expected,
        "forbidden_hits": forbidden_hits,
        "low_score_hits": low_score_hits,
        "context_only_expected": context_only_expected,
        "expected_miss_failed": expected_miss_failed,
        "ranked_expected": ranked_expected,
        "first_expected_rank": first_expected_rank,
        "metrics": metrics,
        "unexpected_top_hit": unexpected_top_hit,
    }


def average_metric(results: list[dict[str, Any]], name: str) -> float:
    if not results:
        return 0.0
    return sum(float(result.get("metrics", {}).get(name, 0.0)) for result in results) / len(results)


def profile_retrieval_config(profiles: dict[str, dict[str, Any]], profile_id: str) -> dict[str, Any]:
    retrieval = profiles.get(profile_id, {}).get("retrieval")
    return retrieval if isinstance(retrieval, dict) else {}


def profile_gate_failures(
    profiles: dict[str, dict[str, Any]],
    positive_results: list[dict[str, Any]],
) -> dict[str, list[str]]:
    failures: dict[str, list[str]] = {}
    results_by_profile: dict[str, list[dict[str, Any]]] = {}
    for result in positive_results:
        profile_id = result.get("profile_id")
        if profile_id:
            results_by_profile.setdefault(str(profile_id), []).append(result)

    for profile_id, results in sorted(results_by_profile.items()):
        config = profile_retrieval_config(profiles, profile_id)
        if not config:
            continue
        profile_failures: list[str] = []
        min_seed_score = config.get("min_seed_score")
        if isinstance(min_seed_score, (int, float)):
            for result in results:
                for expected in result.get("expected_pages", []):
                    hit = first_matching_hit(result.get("hits", []), expected)
                    if not hit:
                        continue
                    if hit.get("match_type") != "seed":
                        profile_failures.append(
                            f"{result['id']}: expected page {expected} was not a seed hit for min_seed_score"
                        )
                        continue
                    primary_score = float(hit.get("primary_score", 0.0))
                    if primary_score < float(min_seed_score):
                        profile_failures.append(
                            f"{result['id']}: expected page {expected} primary_score {primary_score:.3f} below min_seed_score {float(min_seed_score):.3f}"
                        )
        min_recall = config.get("min_recall_at_k")
        if isinstance(min_recall, (int, float)):
            recall = average_metric(results, "recall_at_k")
            if recall < float(min_recall):
                profile_failures.append(
                    f"recall_at_k {recall:.3f} below min_recall_at_k {float(min_recall):.3f}"
                )
        min_mrr = config.get("min_mrr_at_k")
        if isinstance(min_mrr, (int, float)):
            mrr = average_metric(results, "mrr_at_k")
            if mrr < float(min_mrr):
                profile_failures.append(f"mrr_at_k {mrr:.3f} below min_mrr_at_k {float(min_mrr):.3f}")
        if profile_failures:
            failures[profile_id] = profile_failures
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument("--limit", type=positive_int, default=5, help="Maximum number of hits per eval case")
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
        expect_miss = bool(case.get("expect_miss", False))
        if not isinstance(case.get("id"), str) or not isinstance(case.get("query"), str):
            invalid.append(f"case {index}: requires id and query")
        elif "expect_miss" in case and not isinstance(case.get("expect_miss"), bool):
            invalid.append(f"case {case['id']}: expect_miss must be boolean when present")
        elif not expect_miss and not isinstance(case.get("expected_pages"), list):
            invalid.append(f"case {case['id']}: expected_pages is required unless expect_miss is true")
        elif not expect_miss and not case["expected_pages"]:
            invalid.append(f"case {case['id']}: expected_pages must not be empty")
        elif "expected_pages" in case and not isinstance(case.get("expected_pages"), list):
            invalid.append(f"case {case['id']}: expected_pages must be a list")
        elif expect_miss and case.get("expected_pages"):
            invalid.append(f"case {case['id']}: expected_pages must be omitted or empty when expect_miss is true")
        elif "profile_id" in case and (not isinstance(case.get("profile_id"), str) or not case.get("profile_id")):
            invalid.append(f"case {case['id']}: profile_id must be a non-empty string when present")
        elif case.get("profile_id") and case.get("profile_id") not in profiles:
            invalid.append(f"case {case['id']}: unknown profile_id {case.get('profile_id')}")
        elif "require_seed_hit" in case and not isinstance(case.get("require_seed_hit"), bool):
            invalid.append(f"case {case['id']}: require_seed_hit must be boolean when present")
        elif "allow_forbidden_context" in case and not isinstance(case.get("allow_forbidden_context"), bool):
            invalid.append(f"case {case['id']}: allow_forbidden_context must be boolean when present")
        elif "min_score" in case and not isinstance(case.get("min_score"), (int, float)):
            invalid.append(f"case {case['id']}: min_score must be numeric when present")
        elif "forbidden_pages" in case and not isinstance(case.get("forbidden_pages"), list):
            invalid.append(f"case {case['id']}: forbidden_pages must be a list when present")
        elif "tags" in case and not isinstance(case.get("tags"), list):
            invalid.append(f"case {case['id']}: tags must be a list when present")
        else:
            valid_cases.append(case)
    if invalid:
        for item in invalid:
            print(f"error: {item}")
        return 1

    results = [evaluate_case(root, case, args.limit) for case in valid_cases]
    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    positive_results = [result for result in results if not result.get("expect_miss")]
    negative_results = [result for result in results if result.get("expect_miss")]
    positive_passed = sum(1 for result in positive_results if result["passed"])
    negative_passed = sum(1 for result in negative_results if result["passed"])
    hit_rate = (positive_passed / len(positive_results)) if positive_results else 0.0
    miss_accuracy = (negative_passed / len(negative_results)) if negative_results else 0.0
    missing_expected = {result["id"]: result["missing_expected"] for result in results if result["missing_expected"]}
    unexpected_top_hits = {result["id"]: result["unexpected_top_hit"] for result in results if result["unexpected_top_hit"]}
    forbidden_hits = {result["id"]: result["forbidden_hits"] for result in results if result["forbidden_hits"]}
    low_score_hits = {result["id"]: result["low_score_hits"] for result in results if result["low_score_hits"]}
    context_only_expected = {
        result["id"]: result["context_only_expected"] for result in results if result["context_only_expected"]
    }
    expected_miss_failures = {result["id"]: [hit["path"] for hit in result["hits"]] for result in results if result["expected_miss_failed"]}
    tag_counts: dict[str, int] = {}
    tag_passed: dict[str, int] = {}
    for result in results:
        for tag in result.get("tags", []):
            tag = str(tag)
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
            if result["passed"]:
                tag_passed[tag] = tag_passed.get(tag, 0) + 1
    gate_failures = profile_gate_failures(profiles, positive_results)
    report = {
        "cases": total,
        "passed": passed,
        "hit_rate": hit_rate,
        "positive_cases": len(positive_results),
        "negative_cases": len(negative_results),
        "positive_passed": positive_passed,
        "negative_passed": negative_passed,
        "miss_accuracy": miss_accuracy,
        "profiles": sorted({str(result.get("profile_id")) for result in results if result.get("profile_id")}),
        "metrics": {
            "recall_at_k": average_metric(positive_results, "recall_at_k"),
            "precision_at_k": average_metric(positive_results, "precision_at_k"),
            "mrr_at_k": average_metric(positive_results, "mrr_at_k"),
            "ndcg_at_k": average_metric(positive_results, "ndcg_at_k"),
            "k": args.limit,
        },
        "missing_expected": missing_expected,
        "unexpected_top_hits": unexpected_top_hits,
        "forbidden_hits": forbidden_hits,
        "low_score_hits": low_score_hits,
        "context_only_expected": context_only_expected,
        "expected_miss_failures": expected_miss_failures,
        "profile_gate_failures": gate_failures,
        "tag_summary": {
            tag: {"cases": count, "passed": tag_passed.get(tag, 0)}
            for tag, count in sorted(tag_counts.items())
        },
        "inputs": "retrieval-evals.jsonl",
        "results": results,
    }

    if not args.no_report:
        markdown = [
            "# Retrieval Evaluation Report",
            "",
            f"- Cases: {total}",
            f"- Positive cases: {len(positive_results)}",
            f"- Negative cases: {len(negative_results)}",
            f"- Passed: {passed}",
            f"- Hit rate: {hit_rate:.3f}",
            f"- Miss accuracy: {miss_accuracy:.3f}",
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
        markdown.append("")
        markdown.append("## Expected Miss Failures")
        if expected_miss_failures:
            for case_id, hits in expected_miss_failures.items():
                markdown.append(f"- {case_id}: {', '.join(hits)}")
        else:
            markdown.append("- None")
        markdown.append("")
        markdown.append("## Profile Gate Failures")
        if gate_failures:
            for profile_id, failures in gate_failures.items():
                markdown.append(f"- {profile_id}:")
                markdown.extend(f"  - {failure}" for failure in failures)
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
        print(f"positive_cases: {len(positive_results)}")
        print(f"negative_cases: {len(negative_results)}")
        print(f"passed: {passed}")
        print(f"hit_rate: {hit_rate:.3f}")
        print(f"miss_accuracy: {miss_accuracy:.3f}")
        print(f"recall_at_{args.limit}: {report['metrics']['recall_at_k']:.3f}")
        print(f"precision_at_{args.limit}: {report['metrics']['precision_at_k']:.3f}")
        print(f"mrr_at_{args.limit}: {report['metrics']['mrr_at_k']:.3f}")
        print(f"ndcg_at_{args.limit}: {report['metrics']['ndcg_at_k']:.3f}")
        print(f"missing_expected: {len(missing_expected)}")
        print(f"unexpected_top_hits: {len(unexpected_top_hits)}")
        print(f"expected_miss_failures: {len(expected_miss_failures)}")
        print(f"profile_gate_failures: {sum(len(items) for items in gate_failures.values())}")
    return 0 if passed == total and not gate_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
