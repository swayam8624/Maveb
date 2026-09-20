#!/usr/bin/env python3
"""Execute and gate a reproducible multi-revision CBRC evidence campaign."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def run(command: list[str]) -> None:
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(
            f"campaign command failed ({process.returncode}): {' '.join(command)}\n"
            f"{process.stdout[-3000:]}\n{process.stderr[-3000:]}"
        )


def load_campaign(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("campaign must be a JSON object")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("campaign requires non-empty cases")
    names = [str(case.get("id", "")).strip() for case in cases]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("campaign case ids must be unique non-empty strings")
    return payload


def gate_rows(rows: list[dict[str, Any]], campaign: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        raise ValueError("campaign produced no rows")
    local = [row for row in rows if not bool(row.get("fallback_full", False))]
    full = [row for row in rows if bool(row.get("fallback_full", False))]
    high = [
        row for row in rows
        if str(row.get("coupling_regime", "")).lower() in {"high", "adversarial"}
    ]
    violations = []
    for row in rows:
        for name, qoi in row["qois"].items():
            actual = float(qoi["measured_full_reference_error"])
            bound = float(qoi["certified_bound"])
            if actual > bound + 1e-12:
                violations.append(
                    {
                        "scene": row.get("scene_id"),
                        "revision": row.get("revision_id"),
                        "qoi": name,
                        "actual": actual,
                        "bound": bound,
                    }
                )

    minimum_revisions = int(campaign.get("minimum_revisions", 5))
    require_full = bool(campaign.get("require_full_fallback", True))
    require_local = bool(campaign.get("require_local_success", True))
    require_high = bool(campaign.get("require_high_coupling", True))
    scenes = Counter(str(row.get("scene_id", "")) for row in rows)
    minimum_scenes = int(campaign.get("minimum_scenes", 1))

    gates = {
        "minimumRevisions": len(rows) >= minimum_revisions,
        "minimumScenes": len(scenes) >= minimum_scenes,
        "noCertificateViolations": not violations,
        "hasCertifiedLocalCase": bool(local) if require_local else True,
        "hasAutomaticFullFallback": bool(full) if require_full else True,
        "hasHighCouplingCase": bool(high) if require_high else True,
    }
    return {
        "schemaVersion": 1,
        "experiment": "cbrc-real-campaign-gates-v1",
        "rows": len(rows),
        "scenes": dict(sorted(scenes.items())),
        "localCases": len(local),
        "fullFallbackCases": len(full),
        "highCouplingCases": len(high),
        "certificateViolations": violations,
        "gates": gates,
        "pass": all(gates.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    campaign = load_campaign(args.campaign)
    root = args.output_dir
    root.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    spatial_for_figure: Path | None = None

    bundle_script = Path(__file__).resolve().with_name("cbrc_evidence_bundle.py")
    for case in campaign["cases"]:
        case_id = str(case["id"])
        case_dir = root / "cases" / case_id
        command = [
            sys.executable,
            str(bundle_script),
            "--translation", str(Path(case["translation"])),
            "--certificate", str(Path(case["certificate"])),
            "--oracle", str(args.oracle),
            "--scene-id", str(case["scene_id"]),
            "--git-sha", args.git_sha,
            "--epsilon", str(float(case["epsilon"])),
            "--output-dir", str(case_dir),
        ]
        if case.get("work_cost_model"):
            command.extend(["--work-cost-model", str(Path(case["work_cost_model"]))])
        run(command)

        row = json.loads((case_dir / "revision-row.json").read_text())
        row["coupling_regime"] = str(case.get("coupling_regime", "unknown"))
        row["edit_class"] = str(case.get("edit_class", row.get("edit_class", "gaussian")))
        (case_dir / "revision-row.json").write_text(
            json.dumps(row, indent=2, sort_keys=True) + "\n"
        )
        all_rows.append(row)
        if spatial_for_figure is None:
            spatial_for_figure = case_dir / "spatial-evidence.csv"

    rows_path = root / "campaign-rows.jsonl"
    rows_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in all_rows)
    )

    gates = gate_rows(all_rows, campaign)
    gate_path = root / "campaign-gates.json"
    gate_path.write_text(json.dumps(gates, indent=2, sort_keys=True) + "\n")

    evaluator = Path(__file__).resolve().with_name("cbrc_evaluate.py")
    evaluation = root / "campaign-evaluation.json"
    run(
        [
            sys.executable,
            str(evaluator),
            "--input", str(rows_path),
            "--output", str(evaluation),
        ]
    )

    analysis = (
        Path(__file__).resolve().parents[2]
        / "research"
        / "analysis"
        / "cbrc_paper_artifacts.py"
    )
    analysis_dir = root / "paper-artifacts"
    command = [
        sys.executable,
        str(analysis),
        "--rows", str(rows_path),
        "--output-dir", str(analysis_dir),
    ]
    if spatial_for_figure is not None:
        command.extend(["--spatial", str(spatial_for_figure)])
    run(command)

    print(json.dumps(gates, indent=2, sort_keys=True))
    return 0 if gates["pass"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
