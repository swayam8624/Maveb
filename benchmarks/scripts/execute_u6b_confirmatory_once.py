#!/usr/bin/env python3
"""Execute U6b once while withholding intermediate confirmatory metrics until the result is sealed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from run_u5a_gaussian_depth import sha256_file


STUDY_ID = "metric-uncertainty-u6b-opacity-visibility-confirmatory-v1"
RESULT_STAGE = "U6b-confirmatory-heldout-faro-depth"
FREEZE_STAGE = "U6b-confirmatory-result-freeze"
TOTAL_RENDERS = 120


def run_hidden_stdout(command: list[str], *, label: str) -> str:
    """Run one stage without exposing stdout, where the runner emits confirmatory metrics."""
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="", flush=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit code {completed.returncode}; stdout was intentionally withheld to avoid partial-outcome exposure"
        )
    return completed.stdout


def require_absent(path: Path, *, label: str) -> None:
    if path.exists():
        raise ValueError(f"{label} already exists; sealed U6b execution will not overwrite it: {path}")


def copy_exact_once(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise FileNotFoundError(source)
    require_absent(destination, label="U6b result evidence")
    payload = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    source_sha = sha256_file(source)
    copied_sha = sha256_file(destination)
    if copied_sha != source_sha:
        raise ValueError("U6b copied result evidence SHA mismatch")
    return source_sha


def validate_sealed_outputs(
    *,
    result_path: Path,
    freeze_path: Path,
    result_evidence_path: Path,
) -> dict:
    result = json.loads(result_path.read_text())
    freeze = json.loads(freeze_path.read_text())
    if result.get("study") != STUDY_ID or result.get("stage") != RESULT_STAGE:
        raise ValueError("U6b sealed executor result identity mismatch")
    if int(result.get("renderCount", -1)) != TOTAL_RENDERS:
        raise ValueError("U6b sealed executor result render count mismatch")
    if freeze.get("study") != STUDY_ID or freeze.get("stage") != FREEZE_STAGE:
        raise ValueError("U6b sealed executor freeze identity mismatch")
    if int(freeze.get("renderCount", -1)) != TOTAL_RENDERS:
        raise ValueError("U6b sealed executor freeze render count mismatch")
    result_sha = sha256_file(result_path)
    if freeze.get("resultSha256") != result_sha:
        raise ValueError("U6b sealed executor freeze does not bind the result SHA")
    if sha256_file(result_evidence_path) != result_sha:
        raise ValueError("U6b sealed executor committed evidence copy does not match result SHA")
    gate = result.get("confirmatoryGate", {})
    passed = gate.get("allGateClausesPassed")
    if type(passed) is not bool:
        raise ValueError("U6b sealed executor result has no boolean gate decision")
    if freeze.get("allGateClausesPassed") is not passed:
        raise ValueError("U6b sealed executor result/freeze gate decision mismatch")
    return {
        "study": STUDY_ID,
        "status": "sealed-confirmatory-result",
        "resultStatus": result["status"],
        "allGateClausesPassed": passed,
        "renderCount": TOTAL_RENDERS,
        "resultSha256": result_sha,
        "freezeSha256": sha256_file(freeze_path),
        "resultEvidenceSha256": sha256_file(result_evidence_path),
        "intermediateMetricStdoutExposed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--render-tool", type=Path, required=True)
    parser.add_argument("--result-evidence-output", type=Path, required=True)
    parser.add_argument("--freeze-evidence-output", type=Path, required=True)
    args = parser.parse_args()

    for path in (args.protocol, args.preparation, args.authorization, args.render_tool):
        if not path.is_file():
            raise FileNotFoundError(path)

    result_path = args.output_root / "result.json"
    require_absent(result_path, label="U6b confirmatory result")
    require_absent(args.result_evidence_output, label="U6b result evidence")
    require_absent(args.freeze_evidence_output, label="U6b freeze evidence")
    existing_renders = list(args.output_root.glob("scenes/*/renders/*/*.f32"))
    if existing_renders:
        raise ValueError("U6b rendered-depth files already exist; sealed one-shot execution refuses a partial/recovery state")

    script_root = Path(__file__).resolve().parent
    runner = script_root / "run_u6b_confirmatory_visibility.py"
    freezer = script_root / "freeze_u6b_confirmatory_result.py"
    if not runner.is_file() or not freezer.is_file():
        raise FileNotFoundError("U6b runner/freezer script is missing")

    runner_stdout = run_hidden_stdout(
        [
            sys.executable,
            str(runner),
            "--protocol",
            str(args.protocol),
            "--preparation",
            str(args.preparation),
            "--authorization",
            str(args.authorization),
            "--output-root",
            str(args.output_root),
            "--render-tool",
            str(args.render_tool),
        ],
        label="U6b confirmatory runner",
    )
    if not result_path.is_file():
        raise RuntimeError("U6b runner returned success without writing result.json")

    # Do not print runner_stdout: it contains per-target confirmatory metrics. The immutable
    # result file is the only outcome source used from this point onward.
    del runner_stdout

    run_hidden_stdout(
        [
            sys.executable,
            str(freezer),
            "--protocol",
            str(args.protocol),
            "--preparation",
            str(args.preparation),
            "--authorization",
            str(args.authorization),
            "--output-root",
            str(args.output_root),
            "--render-tool",
            str(args.render_tool),
            "--evidence-output",
            str(args.freeze_evidence_output),
        ],
        label="U6b result freeze verifier",
    )
    if not args.freeze_evidence_output.is_file():
        raise RuntimeError("U6b freeze verifier returned success without writing evidence")

    copy_exact_once(result_path, args.result_evidence_output)
    summary = validate_sealed_outputs(
        result_path=result_path,
        freeze_path=args.freeze_evidence_output,
        result_evidence_path=args.result_evidence_output,
    )
    summary["resultEvidencePath"] = str(args.result_evidence_output)
    summary["freezeEvidencePath"] = str(args.freeze_evidence_output)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
