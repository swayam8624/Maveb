#!/usr/bin/env python3
"""Regenerate only the reviewer-selected case visuals after compact execution.

The quantitative campaign is already complete at this point. This utility uses
the frozen campaign plus the existing audit to choose the same four reviewer
cases that cbrc_reviewer_visuals.py will render, then reruns only those cases to
restore their reproducible visual files.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = ROOT / "research" / "analysis"
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

import cbrc_reviewer_visuals as reviewer_visuals


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--import-manifest", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--revision-tool", type=Path, required=True)
    parser.add_argument("--freeze-provenance", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--limit", type=int, default=4)
    args = parser.parse_args()

    campaign = args.campaign.resolve()
    campaign_dir = args.campaign_dir.resolve()
    audit = load(args.audit.resolve())
    import_manifest = load(args.import_manifest.resolve())
    scene_map = reviewer_visuals.import_scene_map(import_manifest)
    selected = reviewer_visuals.choose_cases(
        audit,
        limit=max(1, args.limit),
        scene_map=scene_map,
    )
    case_ids = [str(item["caseId"]) for item in selected]
    if not case_ids:
        raise SystemExit("reviewer visual regeneration resolved no cases")

    campaign_script = ROOT / "benchmarks/scripts/cbrc_campaign.py"
    for case_id in case_ids:
        case_dir = campaign_dir / "cases" / case_id
        marker = case_dir / "CASE_COMPLETE.json"
        if marker.exists():
            marker.unlink()
        command = [
            sys.executable,
            str(campaign_script),
            "--campaign",
            str(campaign),
            "--oracle",
            str(args.oracle.resolve()),
            "--git-sha",
            args.git_sha,
            "--output-dir",
            str(campaign_dir),
            "--workers",
            "1",
            "--worker-case",
            case_id,
            "--resume",
            "--no-progress",
            "--revision-tool",
            str(args.revision_tool.resolve()),
            "--freeze-provenance",
            str(args.freeze_provenance.resolve()),
        ]
        subprocess.run(command, check=True)
        visuals = case_dir / "visuals"
        required = (
            visuals / "before.ppm",
            visuals / "selected-repair.ppm",
            visuals / "full-after.ppm",
            visuals / "certified-support.ppm",
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(
                f"visual regeneration for {case_id} is incomplete: {missing}"
            )
        print(f"  ✓ regenerated reviewer visuals for {case_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
