#!/usr/bin/env python3
"""Initialize a file-first Markdown LLM wiki."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

from wiki_lib import (
    PROFILE_DIR,
    append_log,
    build_memory_artifacts,
    confined_output_path,
    core_direction_complete,
    default_delivery_contract,
    extract_markdown_section,
    load_json,
    profile_filename,
    render_core_direction,
    today,
    utc_now,
    validate_core_direction_data,
    validate_delivery_contract_data,
    validate_profile_data,
    write_json,
)


TEMPLATES = {
    "SCHEMA.md": "schema.md.tmpl",
    "index.md": "index.md.tmpl",
    "log.md": "log.md.tmpl",
}

BASELINE_DIRS = [
    "raw/articles",
    "raw/papers",
    "raw/transcripts",
    "raw/snippets",
    PROFILE_DIR,
    "wiki/concepts",
    "wiki/entities",
    "wiki/comparisons",
    "wiki/queries",
    "reports/validation",
    "reports/health",
    "reports/optimization",
    "reports/retrieval",
    "reports/context-packs",
    "reports/publish/html",
    "reports/publish/mcp",
]

BASELINE_FILES = [
    "SCHEMA.md",
    "delivery-contract.json",
    "index.md",
    "log.md",
    "memory-index.json",
    "link-graph.json",
    "query-log.jsonl",
    "retrieval-evals.jsonl",
]


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
    if resolved == temp_root or temp_root not in resolved.parents:
        raise SystemExit("--fresh may only remove a strict child of the system temp directory")
    shutil.rmtree(root)


def write_missing(path: Path, text: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def read_core_direction(path: Path | None) -> tuple[dict[str, object] | None, list[str]]:
    if path is None:
        return None, []
    data, error = load_json(path, {})
    if error:
        return None, [f"{path}: invalid JSON: {error}"]
    errors = validate_core_direction_data(data)
    return (data if isinstance(data, dict) else None), [f"{path}: {item}" for item in errors]


def read_profile(path: Path) -> tuple[dict[str, object] | None, list[str]]:
    data, error = load_json(path, {})
    if error:
        return None, [f"{path}: invalid JSON: {error}"]
    errors = validate_profile_data(data)
    return (data if isinstance(data, dict) else None), [f"{path}: {item}" for item in errors]


def read_delivery_contract(path: Path | None) -> tuple[dict[str, object] | None, list[str]]:
    if path is None:
        return None, []
    data, error = load_json(path, {})
    if error:
        return None, [f"{path}: invalid JSON: {error}"]
    errors = validate_delivery_contract_data(data)
    return (data if isinstance(data, dict) else None), [f"{path}: {item}" for item in errors]


def schema_created_value(text: str) -> str:
    match = re.search(r"^Created:\s*(\S+)\s*$", text, flags=re.MULTILINE)
    return match.group(1) if match else today()


def known_generated_draft_schema(text: str) -> bool:
    values = {
        "created": schema_created_value(text),
        "timestamp": "",
        "core_direction": render_core_direction(None, draft=True),
    }
    return text == render_template("schema.md.tmpl", values)


def init_wiki(
    root: Path,
    fresh: bool = False,
    core_direction: dict[str, object] | None = None,
    profiles: list[dict[str, object]] | None = None,
    delivery_contract: dict[str, object] | None = None,
    draft: bool = True,
) -> dict[str, list[str]]:
    created: list[str] = []
    kept: list[str] = []
    upgraded: list[str] = []
    profiles = profiles or []
    contract_was_supplied = delivery_contract is not None
    requested_contract = delivery_contract or default_delivery_contract()

    if not draft:
        core_errors = validate_core_direction_data(core_direction)
        profile_errors: list[str] = []
        if not profiles:
            profile_errors.append("normal initialization requires at least one profile")
        seen_profile_ids: set[str] = set()
        for profile in profiles:
            profile_errors.extend(validate_profile_data(profile))
            profile_id = str(profile.get("profile_id") or "").strip()
            if profile_id in seen_profile_ids:
                profile_errors.append(f"duplicate profile_id {profile_id}")
            seen_profile_ids.add(profile_id)
        contract_errors = validate_delivery_contract_data(requested_contract)
        if core_errors or profile_errors or contract_errors:
            raise SystemExit("\n".join(f"error: {item}" for item in core_errors + profile_errors + contract_errors))

    if fresh:
        safe_fresh_remove(root)

    output_paths = [root / rel for rel in [*BASELINE_DIRS, *BASELINE_FILES]]
    output_paths.extend(
        root / PROFILE_DIR / profile_filename(str(profile.get("profile_id") or "").strip()) for profile in profiles
    )
    for path in output_paths:
        confined_output_path(root, path, scope="wiki root")

    schema_upgrade_created: str | None = None
    schema_path = root / "SCHEMA.md"
    if schema_path.exists() and not draft and not core_direction_complete(root):
        current = schema_path.read_text(encoding="utf-8")
        if not known_generated_draft_schema(current):
            raise SystemExit("error: existing SCHEMA.md is incomplete but differs from the generated draft; resolve it explicitly")
        schema_upgrade_created = schema_created_value(current)
    elif schema_path.exists() and not draft:
        current_direction = extract_markdown_section(schema_path.read_text(encoding="utf-8"), "Wiki Core Direction")
        expected_direction = render_core_direction(core_direction, draft=False)
        current_lines = [line.strip() for line in current_direction.strip().splitlines() if line.strip()]
        expected_lines = [line.strip() for line in expected_direction.strip().splitlines() if line.strip()]
        if current_lines[: len(expected_lines)] != expected_lines:
            raise SystemExit("error: existing SCHEMA.md conflicts with the confirmed Wiki Core Direction")

    contract_path = root / "delivery-contract.json"
    contract_exists = contract_path.exists()
    if contract_exists:
        current_contract, contract_error = load_json(contract_path, {})
        contract_errors = ([f"invalid JSON: {contract_error}"] if contract_error else validate_delivery_contract_data(current_contract))
        if contract_errors:
            raise SystemExit("\n".join(f"error: delivery-contract.json: {item}" for item in contract_errors))
        if contract_was_supplied and current_contract != requested_contract:
            raise SystemExit("error: existing delivery-contract.json conflicts with the requested Delivery Contract")

    if not draft:
        for profile in profiles:
            profile_id = str(profile.get("profile_id") or "").strip()
            profile_path = root / PROFILE_DIR / profile_filename(profile_id)
            if not profile_path.exists():
                continue
            current_profile, profile_error = load_json(profile_path, {})
            if profile_error:
                raise SystemExit(f"error: existing profile {profile_id} is invalid JSON: {profile_error}")
            existing_errors = validate_profile_data(current_profile)
            if existing_errors:
                raise SystemExit(
                    "\n".join(f"error: existing profile {profile_id}: {item}" for item in existing_errors)
                )
            if current_profile != profile:
                raise SystemExit(f"error: existing profile {profile_id} conflicts with the confirmed extraction profile")

    root.mkdir(parents=True, exist_ok=True)

    for rel in BASELINE_DIRS:
        path = root / rel
        if path.exists():
            kept.append(rel + "/")
        else:
            path.mkdir(parents=True, exist_ok=True)
            created.append(rel + "/")

    values = {
        "created": today(),
        "timestamp": utc_now(),
        "core_direction": render_core_direction(core_direction, draft=draft),
    }
    for rel, template_name in TEMPLATES.items():
        path = root / rel
        if rel == "SCHEMA.md" and schema_upgrade_created is not None:
            values["created"] = schema_upgrade_created
            path.write_text(render_template(template_name, values), encoding="utf-8")
            upgraded.append(rel)
            continue
        if write_missing(path, render_template(template_name, values)):
            created.append(rel)
        else:
            kept.append(rel)

    if contract_exists:
        kept.append("delivery-contract.json")
    else:
        write_json(contract_path, requested_contract)
        created.append("delivery-contract.json")

    for profile in profiles:
        profile_id = str(profile.get("profile_id") or "").strip()
        path = root / PROFILE_DIR / profile_filename(profile_id)
        if path.exists():
            kept.append(path.relative_to(root).as_posix())
        else:
            write_json(path, profile)
            created.append(path.relative_to(root).as_posix())

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

    for rel in BASELINE_FILES:
        if not (root / rel).exists():
            raise SystemExit(f"failed to create required file: {rel}")

    if draft:
        append_log(root, "initialized wiki in draft mode; complete Wiki Core Direction before strict validation.")
    elif upgraded:
        append_log(root, "upgraded generated draft Wiki Core Direction to confirmed normal initialization.")

    return {"created": created, "kept": kept, "upgraded": upgraded}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", help="Target wiki directory")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Remove and recreate the target only when it is under the system temp directory",
    )
    parser.add_argument("--core-direction-json", help="Confirmed Wiki Core Direction JSON for normal initialization")
    parser.add_argument(
        "--delivery-contract-json",
        help="Optional Delivery Contract JSON; defaults to executable read-only stdio MCP snapshot plus a thin Skill",
    )
    parser.add_argument(
        "--profile-json",
        action="append",
        default=[],
        help="Confirmed extraction profile JSON; repeat to install multiple profiles",
    )
    parser.add_argument("--draft", action="store_true", help="Allow initialization without confirmed purpose/profile data")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.draft and not args.core_direction_json:
        print("error: normal initialization requires --core-direction-json or explicit --draft", file=sys.stderr)
        return 2
    if not args.draft and not args.profile_json:
        print("error: normal initialization requires at least one --profile-json or explicit --draft", file=sys.stderr)
        return 2
    core_direction, core_errors = read_core_direction(Path(args.core_direction_json) if args.core_direction_json else None)
    delivery_contract, delivery_errors = read_delivery_contract(
        Path(args.delivery_contract_json) if args.delivery_contract_json else None
    )
    profiles: list[dict[str, object]] = []
    profile_errors: list[str] = []
    seen_profiles: set[str] = set()
    for profile_path in args.profile_json:
        profile, errors = read_profile(Path(profile_path))
        profile_errors.extend(errors)
        if profile is None:
            continue
        profile_id = str(profile.get("profile_id") or "").strip()
        if profile_id in seen_profiles:
            profile_errors.append(f"{profile_path}: duplicate profile_id {profile_id}")
        seen_profiles.add(profile_id)
        profiles.append(profile)
    if core_errors or profile_errors or delivery_errors:
        for error in core_errors + profile_errors + delivery_errors:
            print(f"error: {error}", file=sys.stderr)
        return 2

    try:
        result = init_wiki(
            Path(args.wiki_root),
            fresh=args.fresh,
            core_direction=core_direction,
            profiles=profiles,
            delivery_contract=delivery_contract,
            draft=args.draft,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"initialized wiki: {args.wiki_root}")
    print(f"created: {len(result['created'])}")
    print(f"kept: {len(result['kept'])}")
    for rel in result["created"]:
        print(f"  + {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
