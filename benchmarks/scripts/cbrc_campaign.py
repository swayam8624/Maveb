#!/usr/bin/env python3
"""Execute and gate a reproducible multi-revision CBRC evidence campaign."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import statistics
import time
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


def capture_case(
    case: dict[str, Any],
    *,
    revision_tool: Path,
    case_dir: Path,
) -> tuple[Path, Path, Path | None]:
    revision = case.get("revision")
    if not isinstance(revision, dict):
        native = case.get("native_planner_certificate")
        return (
            Path(case["translation"]),
            Path(case["certificate"]),
            None if native is None else Path(native),
        )

    archive = Path(revision["archive"])
    target = revision.get("target")
    camera = revision.get("camera", {})
    if not isinstance(target, list) or len(target) != 3:
        raise ValueError(f"case {case['id']} revision.target must contain 3 values")
    if not isinstance(camera, dict):
        raise ValueError(f"case {case['id']} revision.camera must be an object")

    capture_dir = case_dir / "capture"
    command = [
        str(revision_tool),
        "--archive", str(archive),
        "--entity", str(int(revision["entity"])),
        "--target", ",".join(str(float(v)) for v in target),
        "--timestamp", str(int(revision["timestamp"])),
        "--output-dir", str(capture_dir),
        "--epsilon", str(float(case["epsilon"])),
    ]
    scalar_camera = {
        "width": "--width",
        "height": "--height",
        "focal_x": "--focal-x",
        "focal_y": "--focal-y",
        "center_x": "--center-x",
        "center_y": "--center-y",
        "near": "--near",
        "far": "--far",
    }
    for key, flag in scalar_camera.items():
        if key in camera:
            command.extend([flag, str(camera[key])])
    if "camera_world_position" in camera:
        values = camera["camera_world_position"]
        if not isinstance(values, list) or len(values) != 3:
            raise ValueError("camera_world_position must contain 3 values")
        command.extend(
            ["--camera-world-position", ",".join(str(float(v)) for v in values)]
        )
    if "world_to_camera" in camera:
        values = camera["world_to_camera"]
        if not isinstance(values, list) or len(values) != 16:
            raise ValueError("world_to_camera must contain 16 values")
        command.extend(
            ["--world-to-camera", ",".join(str(float(v)) for v in values)]
        )
    if "history_weight" in revision:
        command.extend(["--history-weight", str(float(revision["history_weight"]))])
    if not bool(revision.get("history_stable", True)):
        command.append("--history-unstable")

    run(command)
    translation = capture_dir / "translation.json"
    certificate = capture_dir / "certificate.json"
    native_planner = capture_dir / "native-planner-certificate.json"
    if (
        not translation.exists()
        or not certificate.exists()
        or not native_planner.exists()
    ):
        raise RuntimeError(
            f"case {case['id']} did not produce complete capture evidence"
        )
    return translation, certificate, native_planner


def baseline_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        for family in ("baselines", "ablations"):
            for method, result in record[family].items():
                grouped.setdefault((family, method), []).append(result)

    summary: dict[str, Any] = {"baselines": {}, "ablations": {}}
    for (family, method), values in sorted(grouped.items()):
        ratios = [
            float(value["workRatioFull"])
            for value in values
            if value.get("workRatioFull") is not None
        ]
        summary[family][method] = {
            "cases": len(values),
            "passRate": sum(bool(value["passes"]) for value in values) / len(values),
            "fullRebuildRate": (
                sum(bool(value["usedFullRebuild"]) for value in values) / len(values)
            ),
            "medianWorkRatioFull": (
                statistics.median(ratios) if ratios else None
            ),
        }
    return summary


def verify_native_python_planner_parity(
    manifest: dict[str, Any],
    baseline_result: dict[str, Any],
    *,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    production = manifest["production_certificate"]["outputConePlanner"]
    python_cbrc = baseline_result["baselines"]["CBRC"]
    work_delta = abs(float(production["plannerWork"]) - float(python_cbrc["work"]))
    pass_match = bool(production["passes"]) == bool(python_cbrc["passes"])
    fallback_match = bool(production["fullRepair"]) == bool(
        python_cbrc["usedFullRebuild"]
    )
    return {
        "workDelta": work_delta,
        "passMatch": pass_match,
        "fallbackMatch": fallback_match,
        "pass": work_delta <= tolerance and pass_match and fallback_match,
    }


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
    parser.add_argument("--revision-tool", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    campaign = load_campaign(args.campaign)
    root = args.output_dir
    root.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    all_baselines: list[dict[str, Any]] = []
    parity_results: list[dict[str, Any]] = []
    timing_results: list[dict[str, Any]] = []
    spatial_for_figure: Path | None = None

    bundle_script = Path(__file__).resolve().with_name("cbrc_evidence_bundle.py")
    baseline_script = (
        Path(__file__).resolve().parents[2]
        / "research"
        / "experiments"
        / "cbrc_baseline_suite.py"
    )
    for case in campaign["cases"]:
        case_id = str(case["id"])
        case_dir = root / "cases" / case_id
        capture_start = time.perf_counter()
        if isinstance(case.get("revision"), dict):
            if args.revision_tool is None:
                raise ValueError(
                    f"case {case_id} requests headless capture but --revision-tool is missing"
                )
            translation, certificate, native_planner = capture_case(
                case,
                revision_tool=args.revision_tool,
                case_dir=case_dir,
            )
        else:
            native_value = case.get("native_planner_certificate")
            translation = Path(case["translation"])
            certificate = Path(case["certificate"])
            native_planner = (
                None if native_value is None else Path(native_value)
            )
        capture_wall_ms = (time.perf_counter() - capture_start) * 1000.0

        command = [
            sys.executable,
            str(bundle_script),
            "--translation", str(translation),
            "--certificate", str(certificate),
            "--oracle", str(args.oracle),
            "--scene-id", str(case["scene_id"]),
            "--git-sha", args.git_sha,
            "--epsilon", str(float(case["epsilon"])),
            "--output-dir", str(case_dir),
        ]
        if case.get("work_cost_model"):
            command.extend(["--work-cost-model", str(Path(case["work_cost_model"]))])
        if native_planner is not None:
            command.extend(
                ["--native-planner-certificate", str(native_planner)]
            )
        evidence_start = time.perf_counter()
        run(command)
        evidence_wall_ms = (time.perf_counter() - evidence_start) * 1000.0

        manifest_payload = json.loads((case_dir / "replay-manifest.json").read_text())
        planner_graph = manifest_payload.get("output_planner_graph")
        if not isinstance(planner_graph, dict):
            raise RuntimeError(
                f"case {case_id} is missing output_planner_graph evidence"
            )
        planner_graph_path = case_dir / "output-planner-graph.json"
        planner_graph_path.write_text(
            json.dumps(planner_graph, indent=2, sort_keys=True) + "\n"
        )
        baseline_path = case_dir / "baselines.json"
        baseline_start = time.perf_counter()
        run(
            [
                sys.executable,
                str(baseline_script),
                "--input",
                str(planner_graph_path),
                "--output",
                str(baseline_path),
            ]
        )
        baseline_wall_ms = (time.perf_counter() - baseline_start) * 1000.0
        baseline_result = json.loads(baseline_path.read_text())
        baseline_result["case_id"] = case_id
        baseline_result["scene_id"] = str(case["scene_id"])
        baseline_result["coupling_regime"] = str(
            case.get("coupling_regime", "unknown")
        )
        for key in ("dataset_id", "source_scene_id", "representation", "edit_family"):
            if key in case:
                baseline_result[key] = case[key]
        all_baselines.append(baseline_result)

        parity = verify_native_python_planner_parity(
            manifest_payload, baseline_result
        )
        parity["case_id"] = case_id
        parity_results.append(parity)

        row = json.loads((case_dir / "revision-row.json").read_text())
        row["case_id"] = case_id
        row["coupling_regime"] = str(case.get("coupling_regime", "unknown"))
        row["edit_class"] = str(case.get("edit_class", row.get("edit_class", "gaussian")))
        for key in ("dataset_id", "source_scene_id", "representation", "edit_family"):
            if key in case:
                row[key] = case[key]
        (case_dir / "revision-row.json").write_text(
            json.dumps(row, indent=2, sort_keys=True) + "\n"
        )
        all_rows.append(row)
        timing_results.append(
            {
                "case_id": case_id,
                "scene_id": str(case["scene_id"]),
                "dataset_id": case.get("dataset_id"),
                "source_scene_id": case.get("source_scene_id"),
                "representation": case.get("representation"),
                "edit_family": case.get("edit_family"),
                "fallback_full": bool(row.get("fallback_full", False)),
                "capture_wall_ms": capture_wall_ms,
                "evidence_wall_ms": evidence_wall_ms,
                "baseline_wall_ms": baseline_wall_ms,
                "case_wall_ms": capture_wall_ms + evidence_wall_ms + baseline_wall_ms,
                "work_ratio_full": (
                    float(row["planner_work"]) / float(row["full_work"])
                    if float(row["full_work"]) > 0.0
                    else None
                ),
            }
        )
        if spatial_for_figure is None:
            spatial_for_figure = case_dir / "spatial-evidence.csv"

    rows_path = root / "campaign-rows.jsonl"
    rows_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in all_rows)
    )
    timings_path = root / "campaign-timings.jsonl"
    timings_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in timing_results)
    )
    baselines_path = root / "campaign-baselines.jsonl"
    baselines_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in all_baselines)
    )
    summary = baseline_summary(all_baselines)
    (root / "baseline-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    (root / "planner-parity.json").write_text(
        json.dumps(parity_results, indent=2, sort_keys=True) + "\n"
    )

    gates = gate_rows(all_rows, campaign)
    gates["gates"]["nativePythonPlannerParity"] = all(
        item["pass"] for item in parity_results
    )
    gates["pass"] = all(gates["gates"].values())
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
        "--baselines", str(baselines_path),
        "--output-dir", str(analysis_dir),
    ]
    if spatial_for_figure is not None:
        command.extend(["--spatial", str(spatial_for_figure)])
    run(command)

    print(json.dumps(gates, indent=2, sort_keys=True))
    return 0 if gates["pass"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
