#!/usr/bin/env python3
"""Fail when Python bytecode cache directories exist under given paths."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def find_pycache(paths: list[Path]) -> list[Path]:
    findings: list[Path] = []
    for root in paths:
        if not root.exists():
            continue
        findings.extend(sorted(path for path in root.rglob("__pycache__") if path.is_dir()))
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Skill source or publish paths to scan")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    findings = find_pycache([Path(path) for path in args.paths])
    if findings:
        print("error: Python bytecode cache directories found")
        for path in findings:
            print(f"  {path.as_posix()}")
        return 1
    print("no Python bytecode cache directories found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
