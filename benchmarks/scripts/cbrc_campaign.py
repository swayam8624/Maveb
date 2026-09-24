#!/usr/bin/env python3
"""Execute and gate a reproducible multi-revision CBRC evidence campaign."""
from __future__ import annotations

import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import json
import subprocess
import sys
import statistics
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import cbrc_storage


PROGRESS_ENABLED = True
CASE_EXECUTION_SCHEMA = 1


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def progress_bar(
    done: int,
    total: int,
    *,
    label: str,
    started: float,
    reused: int = 0,
) -> None:
    if not PROGRESS_ENABLED:
        return
    total = max(total, 1)
    ratio = min(max(done / total, 0.0), 1.0)
    width = 30
    filled = int(round(width * ratio))
    bar = "█" * filled + "░" * (width - filled)
    elapsed = time.monotonic() - started
    eta = None
    executed = max(done - reused, 0)
    if executed > 0 and done < total and elapsed > 0:
        eta = elapsed / executed * (total - done)
    eta_text = f" | ETA {format_duration(eta)}" if eta is not None else ""
    reuse_text = f" | reused {reused}" if reused else ""
    print(
        f"  [{bar}] {done:>3}/{total:<3} {ratio * 100:6.2f}%"
        f" | elapsed {format_duration(elapsed)}{eta_text}{reuse_text} | {label}",
        flush=True,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def run(command: list[str], *, label: str | None = None) -> None:
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    captured: dict[str, str] = {}

    def collect() -> None:
        stdout, stderr = process.communicate()
        captured["stdout"] = stdout
        captured["stderr"] = stderr

    worker = threading.Thread(target=collect, daemon=True)
    worker.start()
    started = time.monotonic()
    while worker.is_alive():
        worker.join(timeout=15.0)
        if worker.is_alive() and PROGRESS_ENABLED:
            name = label or Path(command[0]).name
            print(
                f"      ↳ {name} still running "
                f"({format_duration(time.monotonic() - started)})",
                flush=True,
            )
    if process.returncode != 0:
        stdout = captured.get("stdout", "")
        stderr = captured.get("stderr", "")
        raise RuntimeError(
            f"campaign command failed ({process.returncode}): {' '.join(command)}\n"
            f"{stdout[-3000:]}\n{stderr[-3000:]}"
        )


def execution_signature(
    *,
    campaign_path: Path,
    oracle: Path,
    revision_tool: Path | None,
    git_sha: str,
    freeze_provenance: Path | None,
) -> str:
    digest = hashlib.sha256()
    payload = {
        "caseExecutionSchema": CASE_EXECUTION_SCHEMA,
        "campaignSha256": sha256(campaign_path),
        "oracleSha256": sha256(oracle),
        "revisionToolSha256": None if revision_tool is None else sha256(revision_tool),
        "gitSha": git_sha,
        "freezeProvenanceSha256": (
            None if freeze_provenance is None else sha256(freeze_provenance)
        ),
    }
    for path in (
        Path(__file__).resolve(),
        Path(__file__).resolve().with_name("cbrc_storage.py"),
        Path(__file__).resolve().with_name("cbrc_evidence_bundle.py"),
        Path(__file__).resolve().with_name("cbrc_bind_live_revision.py"),
        Path(__file__).resolve().with_name("cbrc_replay.py"),
        Path(__file__).resolve().with_name("cbrc_evaluate.py"),
        Path(__file__).resolve().parents[2] / "research/experiments/cbrc_baseline_suite.py",
        Path(__file__).resolve().parents[2] / "research/cbrc/core.py",
        Path(__file__).resolve().parents[2] / "research/cbrc/edges.py",
    ):
        payload[str(path.relative_to(Path(__file__).resolve().parents[2]))] = sha256(path)
    digest.update(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return digest.hexdigest()


def frozen_inputs_by_case(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text())
    return {
        str(item["case_id"]): item
        for item in payload.get("frozen_inputs", [])
        if isinstance(item, dict) and item.get("case_id")
    }


def restore_case_input(
    case: dict[str, Any],
    frozen: dict[str, Any] | None,
) -> None:
    revision = case.get("revision")
    if not isinstance(revision, dict) or frozen is None:
        return
    source = Path(str(frozen["source_archive"])).resolve()
    destination = Path(str(revision["archive"])).resolve()
    source_revision = int(frozen["source_revision"])
    if not source.is_file():
        raise FileNotFoundError(f"frozen source archive is missing: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    for stale in destination.parent.glob(destination.name + ".*"):
        if stale.is_file() or stale.is_symlink():
            stale.unlink()

    require_clone = (
        sys.platform == "darwin"
        and os.environ.get("MAVEB_REQUIRE_COW", "1").lower()
        not in {"0", "false", "no", "off"}
    )
    cbrc_storage.copy_storage_efficient(
        source,
        destination,
        require_clone=require_clone,
    )
    for suffix in (
        f".gaussians.r{source_revision}.bin",
        f".ownership.r{source_revision}.bin",
    ):
        source_sidecar = Path(str(source) + suffix)
        if not source_sidecar.is_file():
            raise FileNotFoundError(f"frozen source sidecar is missing: {source_sidecar}")
        cbrc_storage.copy_storage_efficient(
            source_sidecar,
            Path(str(destination) + suffix),
            require_clone=require_clone,
        )


def compact_case_input(case: dict[str, Any]) -> int:
    revision = case.get("revision")
    if not isinstance(revision, dict):
        return 0
    archive = Path(str(revision["archive"]))
    return cbrc_storage.remove_materialized_world(archive)


def reusable_case(
    case_dir: Path,
    *,
    case_id: str,
    signature: str,
    git_sha: str,
    adopt_existing: bool,
) -> dict[str, Any] | None:
    marker = case_dir / "CASE_COMPLETE.json"
    required = (
        case_dir / "replay-manifest.json",
        case_dir / "revision-row.json",
        case_dir / "baselines.json",
    )
    if not all(path.is_file() for path in required):
        return None

    if marker.is_file():
        try:
            payload = json.loads(marker.read_text())
        except (OSError, ValueError, json.JSONDecodeError):
            payload = {}
        if (
            payload.get("caseId") == case_id
            and payload.get("executionSignature") == signature
        ):
            return payload

    if not adopt_existing:
        return None

    try:
        manifest = json.loads((case_dir / "replay-manifest.json").read_text())
        row = json.loads((case_dir / "revision-row.json").read_text())
        baseline = json.loads((case_dir / "baselines.json").read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if str(manifest.get("git_sha", "")) != git_sha:
        return None
    if str(row.get("case_id", case_id)) != case_id:
        return None
    if str(baseline.get("case_id", case_id)) != case_id:
        return None
    return {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-case-adopted",
        "caseId": case_id,
        "executionSignature": signature,
        "timing": None,
        "adoptedExisting": True,
    }


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
    camera = revision.get("camera", {})
    if not isinstance(camera, dict):
        raise ValueError(f"case {case['id']} revision.camera must be an object")

    edit = revision.get("edit")
    if edit is None:
        edit_kind = "translation"
        edit = {"kind": "translation", "target": revision.get("target")}
    if not isinstance(edit, dict):
        raise ValueError(f"case {case['id']} revision.edit must be an object")
    edit_kind = str(edit.get("kind", "translation"))

    capture_dir = case_dir / "capture"
    command = [
        str(revision_tool),
        "--archive", str(archive),
        "--entity", str(int(revision["entity"])),
        "--edit-kind", edit_kind,
        "--timestamp", str(int(revision["timestamp"])),
        "--output-dir", str(capture_dir),
        "--epsilon", str(float(case["epsilon"])),
    ]
    if edit_kind == "translation":
        target = edit.get("target", revision.get("target"))
        if not isinstance(target, list) or len(target) != 3:
            raise ValueError(f"case {case['id']} translation target must contain 3 values")
        command.extend(["--target", ",".join(str(float(v)) for v in target)])
    elif edit_kind == "rotation":
        axis = edit.get("axis")
        if not isinstance(axis, list) or len(axis) != 3:
            raise ValueError(f"case {case['id']} rotation axis must contain 3 values")
        radians = float(edit["radians"])
        command.extend(
            [
                "--rotation-axis", ",".join(str(float(v)) for v in axis),
                "--rotation-radians", str(radians),
            ]
        )
    elif edit_kind == "uniform-scale":
        command.extend(["--uniform-scale", str(float(edit["factor"]))])
    elif edit_kind == "opacity":
        command.extend(["--opacity-logit-delta", str(float(edit["logit_delta"]))])
    else:
        raise ValueError(f"case {case['id']} has unsupported edit kind {edit_kind!r}")
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



def finalize_completed_cases(
    campaign: dict[str, Any],
    *,
    root: Path,
) -> int:
    """Aggregate independently executed case directories into the canonical campaign outputs."""
    all_rows: list[dict[str, Any]] = []
    all_baselines: list[dict[str, Any]] = []
    parity_results: list[dict[str, Any]] = []
    timing_results: list[dict[str, Any]] = []
    spatial_for_figure: Path | None = None

    for case in campaign["cases"]:
        case_id = str(case["id"])
        case_dir = root / "cases" / case_id
        required = (
            case_dir / "replay-manifest.json",
            case_dir / "revision-row.json",
            case_dir / "baselines.json",
            case_dir / "CASE_COMPLETE.json",
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(
                f"cannot finalize campaign; case {case_id} is incomplete: {missing}"
            )

        manifest_payload = json.loads((case_dir / "replay-manifest.json").read_text())
        baseline_result = json.loads((case_dir / "baselines.json").read_text())
        row = json.loads((case_dir / "revision-row.json").read_text())
        marker = json.loads((case_dir / "CASE_COMPLETE.json").read_text())

        baseline_result["case_id"] = case_id
        baseline_result["scene_id"] = str(case["scene_id"])
        baseline_result["coupling_regime"] = str(case.get("coupling_regime", "unknown"))
        row["case_id"] = case_id
        row["coupling_regime"] = str(case.get("coupling_regime", "unknown"))
        row["edit_class"] = str(case.get("edit_class", row.get("edit_class", "gaussian")))
        for key in ("dataset_id", "source_scene_id", "representation", "edit_family"):
            if key in case:
                baseline_result[key] = case[key]
                row[key] = case[key]

        parity = verify_native_python_planner_parity(manifest_payload, baseline_result)
        parity["case_id"] = case_id
        timing = marker.get("timing")
        if not isinstance(timing, dict):
            raise RuntimeError(f"case {case_id} is missing timing evidence")

        all_baselines.append(baseline_result)
        parity_results.append(parity)
        all_rows.append(row)
        timing_results.append(dict(timing))
        spatial = case_dir / "spatial-evidence.csv"
        if spatial_for_figure is None and spatial.is_file():
            spatial_for_figure = spatial

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
    write_json(root / "baseline-summary.json", baseline_summary(all_baselines))
    write_json(root / "planner-parity.json", parity_results)

    gates = gate_rows(all_rows, campaign)
    gates["gates"]["nativePythonPlannerParity"] = all(
        item["pass"] for item in parity_results
    )
    gates["pass"] = all(gates["gates"].values())
    write_json(root / "campaign-gates.json", gates)

    evaluator = Path(__file__).resolve().with_name("cbrc_evaluate.py")
    evaluation = root / "campaign-evaluation.json"
    run(
        [
            sys.executable,
            str(evaluator),
            "--input", str(rows_path),
            "--output", str(evaluation),
        ],
        label="campaign evaluation",
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
    run(command, label="paper artifact synthesis")
    print(json.dumps(gates, indent=2, sort_keys=True))
    return 0 if gates["pass"] else 5


def main() -> int:
    global PROGRESS_ENABLED

    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--revision-tool", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("MAVEB_CASE_WORKERS", "1")),
        help="Execute independent campaign cases concurrently. The broad runner defaults this to 4.",
    )
    parser.add_argument(
        "--worker-case",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse cases with matching CASE_COMPLETE markers and restore incomplete frozen inputs.",
    )
    parser.add_argument(
        "--freeze-provenance",
        type=Path,
        help="BROAD_CAMPAIGN_FREEZE.json used to restore pristine per-case inputs on resume.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bars and heartbeat messages.",
    )
    parser.add_argument(
        "--adopt-existing",
        action="store_true",
        help=(
            "Explicitly adopt complete pre-marker case outputs whose replay git_sha matches "
            "--git-sha. Intended only for one-time migration into the resume cache."
        ),
    )
    parser.add_argument(
        "--keep-case-inputs",
        action="store_true",
        help=(
            "Keep mutable per-case world archives after evidence is captured. "
            "Default behavior compacts them immediately to bound disk usage."
        ),
    )
    args = parser.parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be >= 1")
    PROGRESS_ENABLED = not args.no_progress

    campaign_path = args.campaign.resolve()
    oracle_path = args.oracle.resolve()
    revision_tool = args.revision_tool.resolve() if args.revision_tool else None
    freeze_provenance = (
        args.freeze_provenance.resolve() if args.freeze_provenance else None
    )
    campaign = load_campaign(campaign_path)
    if args.worker_case is not None:
        selected_cases = [case for case in campaign["cases"] if str(case["id"]) == args.worker_case]
        if len(selected_cases) != 1:
            raise SystemExit(f"--worker-case did not resolve exactly one case: {args.worker_case}")
        campaign = dict(campaign)
        campaign["cases"] = selected_cases
        campaign["minimum_revisions"] = 1
        campaign["minimum_scenes"] = 1
        campaign["require_local_case"] = False
        campaign["require_full_fallback"] = False
        campaign["require_high_coupling"] = False
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)

    signature = execution_signature(
        campaign_path=campaign_path,
        oracle=oracle_path,
        revision_tool=revision_tool,
        git_sha=args.git_sha,
        freeze_provenance=freeze_provenance,
    )
    state_path = root / ("CAMPAIGN_RESUME_STATE.json" if args.worker_case is None else f".worker-state-{args.worker_case}.json")
    if args.resume and state_path.is_file():
        previous_state = json.loads(state_path.read_text())
        if previous_state.get("executionSignature") != signature:
            raise SystemExit(
                "existing Step-6 resume state does not match this campaign/toolchain; "
                "clear the campaign directory or run through the broad runner so it can invalidate safely"
            )
    write_json(
        state_path,
        {
            "schemaVersion": 1,
            "artifact": "maveb-cbrc-campaign-resume-state",
            "executionSignature": signature,
            "gitSha": args.git_sha,
            "campaign": str(campaign_path),
            "campaignSha256": sha256(campaign_path),
            "freezeProvenance": (
                None if freeze_provenance is None else str(freeze_provenance)
            ),
        },
    )

    frozen_by_case = frozen_inputs_by_case(freeze_provenance)
    prior_timing_by_case: dict[str, dict[str, Any]] = {}
    prior_timings_path = root / "campaign-timings.jsonl"
    if args.adopt_existing and prior_timings_path.is_file():
        for line in prior_timings_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            case_id = str(item.get("case_id", "")).strip()
            if case_id:
                prior_timing_by_case[case_id] = item

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

    total = len(campaign["cases"])
    campaign_started = time.monotonic()
    reused_count = 0

    if args.workers > 1 and args.worker_case is None:
        worker_count = min(args.workers, total)
        if PROGRESS_ENABLED:
            print(
                f"  ↻ executing {total} independent case(s) with {worker_count} worker(s)",
                flush=True,
            )

        def worker_command(case: dict[str, Any]) -> list[str]:
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--campaign", str(campaign_path),
                "--oracle", str(oracle_path),
                "--git-sha", args.git_sha,
                "--output-dir", str(root),
                "--workers", "1",
                "--worker-case", str(case["id"]),
                "--resume",
                "--no-progress",
            ]
            if revision_tool is not None:
                command.extend(["--revision-tool", str(revision_tool)])
            if freeze_provenance is not None:
                command.extend(["--freeze-provenance", str(freeze_provenance)])
            if args.adopt_existing:
                command.append("--adopt-existing")
            if args.keep_case_inputs:
                command.append("--keep-case-inputs")
            return command

        completed = 0
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="maveb-case") as pool:
            futures = {
                pool.submit(run, worker_command(case), label=f"case worker {case['id']}"): case
                for case in campaign["cases"]
            }
            for future in as_completed(futures):
                case = futures[future]
                future.result()
                completed += 1
                progress_bar(
                    completed,
                    total,
                    label=(
                        f"{case.get('dataset_id', 'dataset')}/"
                        f"{case.get('source_scene_id', case.get('scene_id', 'scene'))} "
                        f"{case.get('edit_family', case.get('edit_class', 'edit'))}"
                    ),
                    started=campaign_started,
                )
        return finalize_completed_cases(campaign, root=root)

    for index, case in enumerate(campaign["cases"], start=1):
        case_id = str(case["id"])
        case_dir = root / "cases" / case_id
        marker = (
            reusable_case(
                case_dir,
                case_id=case_id,
                signature=signature,
                git_sha=args.git_sha,
                adopt_existing=args.adopt_existing,
            )
            if args.resume
            else None
        )

        if marker is not None:
            reused_count += 1
            manifest_payload = json.loads((case_dir / "replay-manifest.json").read_text())
            baseline_path = case_dir / "baselines.json"
            baseline_result = json.loads(baseline_path.read_text())
            baseline_result["case_id"] = case_id
            baseline_result["scene_id"] = str(case["scene_id"])
            baseline_result["coupling_regime"] = str(
                case.get("coupling_regime", "unknown")
            )
            for key in ("dataset_id", "source_scene_id", "representation", "edit_family"):
                if key in case:
                    baseline_result[key] = case[key]
            baseline_path.write_text(
                json.dumps(baseline_result, indent=2, sort_keys=True) + "\n"
            )

            row = json.loads((case_dir / "revision-row.json").read_text())
            row["case_id"] = case_id
            row["coupling_regime"] = str(case.get("coupling_regime", "unknown"))
            row["edit_class"] = str(
                case.get("edit_class", row.get("edit_class", "gaussian"))
            )
            for key in ("dataset_id", "source_scene_id", "representation", "edit_family"):
                if key in case:
                    row[key] = case[key]
            if "reviewer_repair_omit_fraction" in case:
                row["reviewer_repair_omit_fraction"] = float(
                    case["reviewer_repair_omit_fraction"]
                )
            (case_dir / "revision-row.json").write_text(
                json.dumps(row, indent=2, sort_keys=True) + "\n"
            )

            parity = verify_native_python_planner_parity(
                manifest_payload, baseline_result
            )
            parity["case_id"] = case_id
            timing = marker.get("timing")
            if not isinstance(timing, dict):
                timing = prior_timing_by_case.get(case_id)
            if not isinstance(timing, dict):
                timing = {
                    "case_id": case_id,
                    "scene_id": str(case["scene_id"]),
                    "dataset_id": case.get("dataset_id"),
                    "source_scene_id": case.get("source_scene_id"),
                    "representation": case.get("representation"),
                    "edit_family": case.get("edit_family"),
                    "fallback_full": bool(row.get("fallback_full", False)),
                    "capture_wall_ms": 0.0,
                    "evidence_wall_ms": 0.0,
                    "baseline_wall_ms": 0.0,
                    "case_wall_ms": 0.0,
                    "work_ratio_full": (
                        float(row["planner_work"]) / float(row["full_work"])
                        if float(row["full_work"]) > 0.0
                        else None
                    ),
                }
            timing = dict(timing)
            timing["resumed"] = True
            timing["adoptedExisting"] = bool(marker.get("adoptedExisting"))
            if marker.get("adoptedExisting"):
                if not parity["pass"]:
                    raise RuntimeError(
                        f"cannot adopt existing case {case_id}: planner parity failed"
                    )
                write_json(
                    case_dir / "CASE_COMPLETE.json",
                    {
                        "schemaVersion": 1,
                        "artifact": "maveb-cbrc-case-complete",
                        "caseId": case_id,
                        "executionSignature": signature,
                        "timing": timing,
                        "adoptedExisting": True,
                    },
                )
        else:
            if PROGRESS_ENABLED:
                print(
                    f"      → case {index}/{total}: {case_id}",
                    flush=True,
                )
            restore_case_input(case, frozen_by_case.get(case_id))
            case_dir.mkdir(parents=True, exist_ok=True)

            capture_start = time.perf_counter()
            if isinstance(case.get("revision"), dict):
                if revision_tool is None:
                    raise ValueError(
                        f"case {case_id} requests headless capture but --revision-tool is missing"
                    )
                translation, certificate, native_planner = capture_case(
                    case,
                    revision_tool=revision_tool,
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
                "--oracle", str(oracle_path),
                "--scene-id", str(case["scene_id"]),
                "--git-sha", args.git_sha,
                "--epsilon", str(float(case["epsilon"])),
                "--output-dir", str(case_dir),
            ]
            if case.get("work_cost_model"):
                command.extend(["--work-cost-model", str(Path(case["work_cost_model"]))])
            repair_omit_fraction = float(case.get("reviewer_repair_omit_fraction", 0.0))
            if repair_omit_fraction > 0.0:
                command.extend(
                    ["--repair-omit-fraction", str(repair_omit_fraction)]
                )
            if native_planner is not None:
                command.extend(
                    ["--native-planner-certificate", str(native_planner)]
                )
            evidence_start = time.perf_counter()
            run(command, label=f"oracle/evidence {case_id}")
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
                ],
                label=f"baselines/ablations {case_id}",
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
            baseline_path.write_text(
                json.dumps(baseline_result, indent=2, sort_keys=True) + "\n"
            )

            parity = verify_native_python_planner_parity(
                manifest_payload, baseline_result
            )
            parity["case_id"] = case_id

            row = json.loads((case_dir / "revision-row.json").read_text())
            row["case_id"] = case_id
            row["coupling_regime"] = str(case.get("coupling_regime", "unknown"))
            row["edit_class"] = str(
                case.get("edit_class", row.get("edit_class", "gaussian"))
            )
            for key in ("dataset_id", "source_scene_id", "representation", "edit_family"):
                if key in case:
                    row[key] = case[key]
            (case_dir / "revision-row.json").write_text(
                json.dumps(row, indent=2, sort_keys=True) + "\n"
            )
            timing = {
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
                "resumed": False,
            }
            write_json(
                case_dir / "CASE_COMPLETE.json",
                {
                    "schemaVersion": 1,
                    "artifact": "maveb-cbrc-case-complete",
                    "caseId": case_id,
                    "executionSignature": signature,
                    "timing": timing,
                },
            )

        all_baselines.append(baseline_result)
        parity_results.append(parity)
        all_rows.append(row)
        timing_results.append(timing)

        if not args.keep_case_inputs:
            removed = compact_case_input(case)
            if removed and PROGRESS_ENABLED:
                print(
                    f"      ↳ compacted mutable case input ({removed} file(s)); "
                    "evidence retained",
                    flush=True,
                )
        spatial = case_dir / "spatial-evidence.csv"
        if spatial_for_figure is None and spatial.is_file():
            spatial_for_figure = spatial

        label = (
            f"{case.get('dataset_id', 'dataset')}/"
            f"{case.get('source_scene_id', case.get('scene_id', 'scene'))} "
            f"{case.get('edit_family', case.get('edit_class', 'edit'))}"
        )
        progress_bar(
            index,
            total,
            label=label,
            started=campaign_started,
            reused=reused_count,
        )

    if args.worker_case is not None:
        return 0

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
    write_json(root / "baseline-summary.json", summary)
    write_json(root / "planner-parity.json", parity_results)

    gates = gate_rows(all_rows, campaign)
    gates["gates"]["nativePythonPlannerParity"] = all(
        item["pass"] for item in parity_results
    )
    gates["pass"] = all(gates["gates"].values())
    gate_path = root / "campaign-gates.json"
    write_json(gate_path, gates)

    evaluator = Path(__file__).resolve().with_name("cbrc_evaluate.py")
    evaluation = root / "campaign-evaluation.json"
    run(
        [
            sys.executable,
            str(evaluator),
            "--input", str(rows_path),
            "--output", str(evaluation),
        ],
        label="campaign evaluation",
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
    run(command, label="paper artifact synthesis")

    print(json.dumps(gates, indent=2, sort_keys=True))
    return 0 if gates["pass"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
