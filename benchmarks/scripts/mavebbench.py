#!/usr/bin/env python3
"""MavebBench: reproducible real-data reconstruction benchmark orchestration.

The harness intentionally does not hide unsupported paths. It runs proven native
Maveb tools where an adapter exists and records explicit adapter gaps otherwise.
Dataset bytes live outside the repository and are addressed through MAVEB_DATA.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import glob
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "benchmarks" / "manifests"
RESULTS_ROOT = REPO_ROOT / "benchmarks" / "results"
LOGS_ROOT = REPO_ROOT / "benchmarks" / "logs"


@dataclasses.dataclass(slots=True)
class CommandResult:
    argv: list[str]
    returncode: int
    duration_seconds: float
    stdout: str
    stderr: str

    def to_json(self) -> dict[str, Any]:
        return {
            "argv": self.argv,
            "command": shlex.join(self.argv),
            "returnCode": self.returncode,
            "durationSeconds": round(self.duration_seconds, 6),
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def expand_path(value: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(value))).resolve()


def load_manifest(dataset_id: str) -> dict[str, Any]:
    path = MANIFEST_DIR / f"{dataset_id}.json"
    if not path.is_file():
        raise ValueError(f"Unknown dataset '{dataset_id}'. Run `mavebbench.py list`.")
    manifest = json.loads(path.read_text())
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(f"{path.name}: unsupported schemaVersion")
    if manifest.get("id") != dataset_id:
        raise ValueError(f"{path.name}: id must equal filename stem")
    return manifest


def iter_manifests() -> Iterable[dict[str, Any]]:
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        if path.name == "schema.json":
            continue
        try:
            manifest = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON: {exc}") from exc
        if manifest.get("schemaVersion") != SCHEMA_VERSION:
            raise ValueError(f"{path.name}: unsupported schemaVersion")
        yield manifest


def resolve_tools() -> dict[str, str | None]:
    deps_bin = REPO_ROOT / ".aether-deps" / "bin"
    candidates: dict[str, list[Path]] = {
        "aether-capture": [
            REPO_ROOT / "build/debug/tools/aether-capture/aether-capture",
            REPO_ROOT / "build/ci/tools/aether-capture/aether-capture",
        ],
        "aether-reconstruct": [
            REPO_ROOT / "build/debug/tools/aether-reconstruct/aether-reconstruct",
            REPO_ROOT / "build/ci/tools/aether-reconstruct/aether-reconstruct",
        ],
        "aether-fuse": [
            REPO_ROOT / "build/debug/tools/aether-fuse/aether-fuse",
            REPO_ROOT / "build/ci/tools/aether-fuse/aether-fuse",
        ],
        "colmap": [deps_bin / "colmap"],
        "brush": [deps_bin / "brush"],
        "aether-proxy": [deps_bin / "aether-proxy"],
        "ffmpeg": [],
        "ffprobe": [],
    }
    resolved: dict[str, str | None] = {}
    for name, paths in candidates.items():
        executable = next((str(path) for path in paths if path.is_file() and os.access(path, os.X_OK)), None)
        if executable is None:
            executable = shutil.which(name)
        resolved[name] = executable
    return resolved


def run_command(argv: list[str], *, cwd: Path | None = None) -> CommandResult:
    start = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return CommandResult(
            argv=argv,
            returncode=completed.returncode,
            duration_seconds=time.monotonic() - start,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            argv=argv,
            returncode=127,
            duration_seconds=time.monotonic() - start,
            stdout="",
            stderr=str(exc),
        )


def git_revision() -> str | None:
    result = run_command(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def resolve_glob(root: Path, pattern: str) -> list[Path]:
    return [Path(p).resolve() for p in sorted(glob.glob(str(root / pattern), recursive=True))]


def resolve_input(manifest: dict[str, Any]) -> dict[str, Any]:
    root = expand_path(manifest["root"])
    resolved: dict[str, Any] = {"root": str(root), "exists": root.exists()}
    kind = manifest["kind"]
    if kind == "images":
        images = root / manifest.get("imagesRel", "")
        resolved.update(images=str(images), ready=images.is_dir())
    elif kind == "video":
        videos = resolve_glob(root, manifest["videoGlob"]) if root.exists() else []
        resolved.update(
            videos=[str(path) for path in videos],
            video=str(videos[0]) if videos else None,
            ready=bool(videos),
        )
    elif kind == "arkit-scenes":
        required = {
            key: resolve_glob(root, pattern) if root.exists() else []
            for key, pattern in manifest.get("requiredAssets", {}).items()
        }
        resolved["assets"] = {key: [str(path) for path in values] for key, values in required.items()}
        resolved["ready"] = root.is_dir() and all(required.values())
    elif kind in {"dtu", "reference-only"}:
        checks = {
            key: resolve_glob(root, pattern) if root.exists() else []
            for key, pattern in manifest.get("requiredAssets", {}).items()
        }
        resolved["assets"] = {key: [str(path) for path in values] for key, values in checks.items()}
        resolved["ready"] = root.is_dir() and all(checks.values())
    else:
        raise ValueError(f"{manifest['id']}: unknown kind {kind}")
    return resolved


def ensure_clean_dir(path: Path, force: bool) -> None:
    if path.exists():
        if not force:
            raise ValueError(f"Output already exists: {path}. Use --force or a new --run-id.")
        shutil.rmtree(path)
    path.mkdir(parents=True)


def parse_json_output(result: CommandResult) -> dict[str, Any] | None:
    for candidate in reversed(result.stdout.splitlines()):
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    for candidate in reversed(result.stderr.splitlines()):
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def validate_images(images: Path, tools: dict[str, str | None]) -> tuple[str, dict[str, Any]]:
    tool = tools["aether-capture"]
    if not tool:
        return "blocked", {"reason": "aether-capture-not-found"}
    result = run_command([tool, "validate", str(images), "--json"], cwd=REPO_ROOT)
    payload = parse_json_output(result)
    status = "pass" if result.returncode == 0 and payload and payload.get("valid") else "fail"
    return status, {"command": result.to_json(), "payload": payload}


def reconstruct_images(
    images: Path,
    output: Path,
    tools: dict[str, str | None],
    *,
    steps: int,
    checkpoint_every: int,
    dry_run: bool,
) -> tuple[str, dict[str, Any]]:
    required = ("aether-reconstruct", "colmap", "brush", "aether-proxy")
    missing = [name for name in required if not tools[name]]
    if missing:
        return "blocked", {"reason": "missing-tools", "tools": missing}
    argv = [
        tools["aether-reconstruct"] or "",
        str(images),
        "--output",
        str(output),
        "--colmap",
        tools["colmap"] or "",
        "--brush",
        tools["brush"] or "",
        "--proxy",
        tools["aether-proxy"] or "",
        "--trainer",
        "brush",
        "--seed",
        "42",
        "--steps",
        str(steps),
        "--checkpoint-every",
        str(checkpoint_every),
        "--json",
    ]
    if dry_run:
        argv.append("--dry-run")
    result = run_command(argv, cwd=REPO_ROOT)
    payload = parse_json_output(result)
    status = "pass" if result.returncode == 0 and payload and payload.get("ok") else "fail"
    return status, {"command": result.to_json(), "payload": payload}


def video_metadata(video: Path, tools: dict[str, str | None]) -> dict[str, Any]:
    ffprobe = tools["ffprobe"]
    if not ffprobe:
        return {"status": "blocked", "reason": "ffprobe-not-found"}
    result = run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height,r_frame_rate,codec_name",
            "-of",
            "json",
            str(video),
        ]
    )
    try:
        payload = json.loads(result.stdout) if result.returncode == 0 else None
    except json.JSONDecodeError:
        payload = None
    return {"status": "pass" if payload else "fail", "command": result.to_json(), "payload": payload}


def extract_video_frames(
    video: Path,
    output: Path,
    tools: dict[str, str | None],
    *,
    fps: float,
) -> tuple[str, dict[str, Any]]:
    ffmpeg = tools["ffmpeg"]
    if not ffmpeg:
        return "blocked", {"reason": "ffmpeg-not-found"}
    output.mkdir(parents=True, exist_ok=True)
    pattern = output / "frame_%06d.jpg"
    result = run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"fps={fps:g}",
            "-q:v",
            "2",
            str(pattern),
        ]
    )
    frames = sorted(output.glob("frame_*.jpg"))
    status = "pass" if result.returncode == 0 and len(frames) >= 3 else "fail"
    return status, {
        "command": result.to_json(),
        "frameCount": len(frames),
        "framesDirectory": str(output),
        "samplingFps": fps,
        "note": "Deterministic uniform sampling; adaptive quality/baseline selection remains a reconstruction milestone.",
    }


def inspect_gap(manifest: dict[str, Any], resolved: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not resolved.get("ready"):
        return "fail", {"reason": "dataset-incomplete", "resolved": resolved}
    kind = manifest["kind"]
    if kind == "arkit-scenes":
        return "adapter-required", {
            "reason": "raw-arkitscenes-not-yet-mapped-to-maveb-capture-schema",
            "target": "CapturePacket/schema-v2 -> aether-fuse -> geometry evaluation",
            "resolved": resolved,
        }
    if kind == "dtu":
        return "adapter-required", {
            "reason": "dtu-camera-and-reference-geometry-evaluation-adapter-required",
            "target": "calibrated images/cameras -> reconstruction -> GeometryEvaluation",
            "resolved": resolved,
        }
    return "reference-only", {
        "reason": manifest.get("note", "reference dataset"),
        "resolved": resolved,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def run_dataset(args: argparse.Namespace, manifest: dict[str, Any], tools: dict[str, str | None]) -> dict[str, Any]:
    resolved = resolve_input(manifest)
    run_id = args.run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RESULTS_ROOT / manifest["id"] / run_id
    ensure_clean_dir(run_dir, args.force)
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "dataset": manifest["id"],
        "title": manifest["title"],
        "kind": manifest["kind"],
        "startedAt": utc_now(),
        "gitRevision": git_revision(),
        "resolvedInput": resolved,
        "steps": [],
    }
    if not resolved.get("ready"):
        record["status"] = "fail"
        record["reason"] = "dataset-not-found-or-incomplete"
        record["finishedAt"] = utc_now()
        write_json(run_dir / "run.json", record)
        return record

    kind = manifest["kind"]
    if kind == "images":
        images = Path(resolved["images"])
        status, details = validate_images(images, tools)
        record["steps"].append({"name": "capture-validation", "status": status, **details})
        if status != "pass" or args.validate_only:
            record["status"] = status
        else:
            status, details = reconstruct_images(
                images,
                run_dir / "reconstruction",
                tools,
                steps=args.steps,
                checkpoint_every=args.checkpoint_every,
                dry_run=args.dry_run,
            )
            record["steps"].append({"name": "reconstruction", "status": status, **details})
            record["status"] = status
    elif kind == "video":
        video = Path(resolved["video"])
        metadata = video_metadata(video, tools)
        record["steps"].append({"name": "video-metadata", **metadata})
        frames_dir = run_dir / "frames"
        status, details = extract_video_frames(video, frames_dir, tools, fps=args.video_fps)
        record["steps"].append({"name": "video-frame-extraction", "status": status, **details})
        if status != "pass":
            record["status"] = status
        else:
            status, details = validate_images(frames_dir, tools)
            record["steps"].append({"name": "capture-validation", "status": status, **details})
            if status != "pass" or args.validate_only:
                record["status"] = status
            else:
                status, details = reconstruct_images(
                    frames_dir,
                    run_dir / "reconstruction",
                    tools,
                    steps=args.steps,
                    checkpoint_every=args.checkpoint_every,
                    dry_run=args.dry_run,
                )
                record["steps"].append({"name": "reconstruction", "status": status, **details})
                record["status"] = status
    else:
        status, details = inspect_gap(manifest, resolved)
        record["steps"].append({"name": "adapter-status", "status": status, **details})
        record["status"] = status

    record["finishedAt"] = utc_now()
    write_json(run_dir / "run.json", record)
    return record


def latest_run(dataset_id: str) -> dict[str, Any] | None:
    root = RESULTS_ROOT / dataset_id
    if not root.is_dir():
        return None
    candidates = sorted((p for p in root.iterdir() if (p / "run.json").is_file()), reverse=True)
    if not candidates:
        return None
    return json.loads((candidates[0] / "run.json").read_text())


def report_markdown(records: list[dict[str, Any]]) -> str:
    lines = [
        "# MavebBench report",
        "",
        "| Dataset | Kind | Status | Evidence |",
        "|---|---|---:|---|",
    ]
    for record in records:
        evidence = []
        for step in record.get("steps", []):
            if step["name"] == "capture-validation":
                payload = step.get("payload") or {}
                summary = payload.get("summary") or {}
                if "imageCount" in summary:
                    evidence.append(f"{summary['imageCount']} images")
            if step["name"] == "video-frame-extraction" and "frameCount" in step:
                evidence.append(f"{step['frameCount']} extracted frames")
            if step["name"] == "reconstruction":
                payload = step.get("payload") or {}
                if payload.get("registeredImages") is not None:
                    evidence.append(f"{payload['registeredImages']} registered")
                if payload.get("trackedPoints") is not None:
                    evidence.append(f"{payload['trackedPoints']} tracks")
        lines.append(
            f"| {record.get('title', record['dataset'])} | {record.get('kind','')} | "
            f"**{record.get('status','unknown')}** | {', '.join(evidence) or '—'} |"
        )
    lines += [
        "",
        "Statuses are evidence-based. `adapter-required` is intentionally not converted to PASS.",
        "",
    ]
    return "\n".join(lines)


def doctor() -> int:
    tools = resolve_tools()
    data = os.environ.get("MAVEB_DATA")
    checks = {
        "repoRoot": str(REPO_ROOT),
        "mavebData": data,
        "mavebDataExists": bool(data and Path(data).expanduser().is_dir()),
        "tools": tools,
        "manifests": [m["id"] for m in iter_manifests()],
    }
    print(json.dumps(checks, indent=2))
    required = ("aether-capture", "aether-reconstruct")
    return 0 if checks["mavebDataExists"] and all(tools[name] for name in required) else 2


def list_datasets() -> int:
    for manifest in iter_manifests():
        resolved = resolve_input(manifest)
        state = "READY" if resolved.get("ready") else "MISSING"
        print(f"{manifest['id']:<24} {manifest['kind']:<15} {state:<7} {manifest['title']}")
    return 0


def run_suite(args: argparse.Namespace, tools: dict[str, str | None]) -> int:
    suite_ids = {
        "smoke": ["eth3d-pipes", "uco3d-object", "arkitscenes-47333462", "dtu-sampleset"],
        "rgb": ["eth3d-pipes", "eth3d-meadow", "tnt-barn", "uco3d-object"],
        "all": [m["id"] for m in iter_manifests()],
    }[args.suite]
    records = []
    for dataset_id in suite_ids:
        manifest = load_manifest(dataset_id)
        child = argparse.Namespace(**vars(args))
        child.run_id = f"suite-{args.suite}"
        child.force = True
        records.append(run_dataset(child, manifest, tools))
    print(report_markdown(records))
    return 1 if any(r["status"] == "fail" for r in records) else 0


def write_report(output: Path | None) -> int:
    records = []
    for manifest in iter_manifests():
        run = latest_run(manifest["id"])
        if run:
            records.append(run)
    markdown = report_markdown(records)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown)
    print(markdown)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maveb real-data reconstruction benchmark harness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list dataset manifests and readiness")
    sub.add_parser("doctor", help="check datasets and executable dependencies")

    def add_run_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--steps", type=int, default=2000)
        p.add_argument("--checkpoint-every", type=int, default=1000)
        p.add_argument("--video-fps", type=float, default=2.0)
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--validate-only", action="store_true")
        p.add_argument("--run-id")
        p.add_argument("--force", action="store_true")

    run = sub.add_parser("run", help="run one dataset")
    run.add_argument("dataset")
    add_run_options(run)

    suite = sub.add_parser("suite", help="run a named suite")
    suite.add_argument("suite", choices=("smoke", "rgb", "all"))
    add_run_options(suite)

    report = sub.add_parser("report", help="summarize latest run for every dataset")
    report.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return list_datasets()
        if args.command == "doctor":
            return doctor()
        if args.command == "report":
            return write_report(args.output)
        tools = resolve_tools()
        if args.command == "run":
            record = run_dataset(args, load_manifest(args.dataset), tools)
            print(json.dumps(record, indent=2))
            return 1 if record["status"] == "fail" else 0
        if args.command == "suite":
            return run_suite(args, tools)
    except (ValueError, OSError) as exc:
        print(f"mavebbench: {exc}", file=sys.stderr)
        return 2
    parser.error("unreachable")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
