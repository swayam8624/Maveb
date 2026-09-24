#!/usr/bin/env python3
"""Run the frozen reviewer-v4 fallback diagnostic with v4 provenance labels.

The classification logic is shared with the earlier read-only diagnostic. This
wrapper changes only report metadata/interpretation; it does not alter cases,
thresholds, planner decisions, or certificate evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import cbrc_reviewer_fallback_diagnostics as base


def analyze(
    rows: list[dict],
    campaign_dir: Path | None,
) -> dict:
    report = base.analyze(rows, campaign_dir)
    report["artifact"] = "maveb-reviewer-v4-locality-fallback-diagnostics"
    report["protocol"] = "post-reviewer-locality-v4"
    report["interpretation"] = (
        "This report diagnoses the already-frozen reviewer-v4 locality execution. "
        "It must not be used to delete, retune, or relabel cases. A "
        "production-full-full-frame-temporal-support result means the native "
        "output-cone planner selected FULL while certified temporal repair "
        "support/cost covered the whole frame. That is evidence about the current "
        "certificate/support model, not permission to modify the frozen v4 matrix."
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = base.load_jsonl(args.rows.resolve())
    campaign_dir = (
        args.campaign_dir.resolve()
        if args.campaign_dir is not None
        else None
    )
    report = analyze(rows, campaign_dir)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
