#!/usr/bin/env python3
"""Archive final MAVEB evidence, then reclaim reconstructable local data.

Default mode is a dry run. Destructive execution requires:
  --execute --i-understand-this-deletes-data

By default the script also requires a completed v6 audit with
confirmatoryPass=true. For a deliberately terminated/finalized project whose
v6 result is OPEN, pass --allow-open-v6 together with the destructive flags.

The deletion scope is intentionally allow-listed. It never walks the repository
looking for arbitrary "large" files and it never deletes tracked source files.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

GIB = 1024 ** 3
MIB = 1024 ** 2

V6_RELATIVE = Path("build/reviewer-certificate-v6-breadth")
DEFAULT_ARCHIVE_RELATIVE = Path("final_evidence/maveb-v6")

REPO_DELETE_RELATIVE = (
    Path("build"),
    Path(".aether-deps"),
    Path(".venv-maveb"),
)

HOME_DELETE_RELATIVE = (
    Path("Datasets/MAVEB"),
    Path("Datasets/MavebBench"),
    Path("Datasets/MavebReferenceWorld"),
    Path("Desktop/Programming/MavebData"),
)

HOME_DELETE_FILES = (
    Path("Downloads/rgbd_bonn_dataset.zip"),
)

V6_ARCHIVE_FILES = (
    Path("analysis/REVIEWER_EVIDENCE_AUDIT.json"),
    Path("analysis/REVIEWER_EVIDENCE_AUDIT.md"),
    Path("analysis/V6_BREADTH_AUDIT.json"),
    Path("analysis/V6_BREADTH_AUDIT.md"),
    Path("analysis/V6_SCENE_METRICS.csv"),
    Path("analysis/V6_BASELINE_SCENE_METRICS.csv"),
    Path("analysis/V6_MANUSCRIPT_CLAIMS.json"),
    Path("analysis/V6_MANUSCRIPT_PACKET.md"),
    Path("analysis/V6_MANUSCRIPT_TABLES.tex"),
    Path("analysis/CASE_DECISION_TRACE.json"),
    Path("frozen/reviewer-stress-campaign.json"),
    Path("frozen/REVIEWER_STRESS_FREEZE.json"),
    Path("visuals/REVIEWER_VISUALS.json"),
    Path("visuals/F_REVIEWER_REAL_SCENE_LOCAL_VS_FULL.png"),
    Path("visuals/F_REVIEWER_TOLERANCE_CROSSOVER.png"),
    Path("campaign/campaign-gates.json"),
    Path("campaign/baseline-summary.json"),
    Path("campaign/planner-parity.json"),
)

V6_ARCHIVE_GZIP_FILES = (
    Path("campaign/campaign-rows.jsonl"),
    Path("campaign/campaign-baselines.jsonl"),
    Path("campaign/campaign-timings.jsonl"),
)


def human(value: int) -> str:
    if value >= GIB:
        return f"{value / GIB:.2f} GiB"
    if value >= MIB:
        return f"{value / MIB:.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"


def path_size(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    if path.is_symlink() or path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path, followlinks=False):
        for name in files:
            candidate = Path(root) / name
            try:
                total += candidate.stat().st_size
            except OSError:
                pass
    return total


def git_root(start: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("Run this script from inside the MAVEB git repository.")
    return Path(result.stdout.strip()).resolve()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def audit_state(repo: Path) -> tuple[Path, dict[str, Any]]:
    path = repo / V6_RELATIVE / "analysis/V6_BREADTH_AUDIT.json"
    if not path.is_file():
        raise SystemExit(
            "Final cleanup refused: v6 audit is missing. "
            "Complete v6 first, or preserve the project and run cleanup later."
        )
    return path, load_json(path)


def tracked_under(repo: Path, relative: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--", str(relative)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def verify_repo_delete_targets_untracked(repo: Path) -> None:
    violations: list[str] = []
    for relative in REPO_DELETE_RELATIVE:
        tracked = tracked_under(repo, relative)
        if tracked:
            violations.extend(tracked[:10])
    if violations:
        joined = "\n  ".join(violations)
        raise SystemExit(
            "Final cleanup refused because an allow-listed delete target contains "
            f"tracked files:\n  {joined}"
        )


def archive_v6(repo: Path, archive: Path) -> list[dict[str, Any]]:
    source_root = repo / V6_RELATIVE
    archive.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []

    for relative in V6_ARCHIVE_FILES:
        source = source_root / relative
        if not source.is_file():
            continue
        destination = archive / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(
            {
                "source": str(source),
                "archive": str(destination),
                "bytes": source.stat().st_size,
                "compression": "none",
            }
        )

    for relative in V6_ARCHIVE_GZIP_FILES:
        source = source_root / relative
        if not source.is_file():
            continue
        destination = archive / (str(relative) + ".gz")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as src, gzip.open(destination, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst, length=8 * MIB)
        copied.append(
            {
                "source": str(source),
                "archive": str(destination),
                "bytes": source.stat().st_size,
                "archiveBytes": destination.stat().st_size,
                "compression": "gzip",
            }
        )

    required = {
        "analysis/V6_BREADTH_AUDIT.json",
        "analysis/V6_MANUSCRIPT_CLAIMS.json",
        "frozen/reviewer-stress-campaign.json",
        "frozen/REVIEWER_STRESS_FREEZE.json",
    }
    archived_relatives = {
        str(Path(item["archive"]).resolve().relative_to(archive.resolve()))
        for item in copied
    }
    missing = sorted(required - archived_relatives)
    if missing:
        raise SystemExit(
            "Final cleanup refused because mandatory v6 evidence could not be archived: "
            + ", ".join(missing)
        )
    return copied


def deletion_targets(repo: Path, home: Path, archive: Path) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    archive_resolved = archive.resolve()
    for relative in REPO_DELETE_RELATIVE:
        path = (repo / relative).resolve()
        if archive_resolved == path or archive_resolved.is_relative_to(path):
            raise SystemExit(
                "Archive directory cannot live inside an allow-listed delete target: "
                f"{archive}"
            )
        targets.append(
            {
                "kind": "repo-generated",
                "path": path,
                "bytes": path_size(path),
            }
        )
    for relative in HOME_DELETE_RELATIVE:
        path = (home / relative).resolve()
        targets.append(
            {
                "kind": "maveb-dataset-tree",
                "path": path,
                "bytes": path_size(path),
            }
        )
    for relative in HOME_DELETE_FILES:
        path = (home / relative).resolve()
        targets.append(
            {
                "kind": "maveb-download",
                "path": path,
                "bytes": path_size(path),
            }
        )
    return targets


def delete_target(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="MAVEB repository root; defaults to the current git worktree",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help="Home directory used for MAVEB dataset cleanup",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        help="Evidence archive destination; defaults to <repo>/final_evidence/maveb-v6",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete allow-listed generated data. Without this flag: dry run only.",
    )
    parser.add_argument(
        "--i-understand-this-deletes-data",
        action="store_true",
        help="Second explicit destructive-action acknowledgement.",
    )
    parser.add_argument(
        "--allow-open-v6",
        action="store_true",
        help=(
            "Permit final cleanup after a completed but non-passing v6 audit. "
            "Use only when the project is deliberately finalized/terminated."
        ),
    )
    parser.add_argument(
        "--keep-datasets",
        action="store_true",
        help="Delete generated repository artifacts but keep MAVEB dataset trees/downloads.",
    )
    args = parser.parse_args()

    repo = git_root(args.repo.expanduser().resolve())
    home = args.home.expanduser().resolve()
    archive = (
        args.archive_dir.expanduser().resolve()
        if args.archive_dir
        else (repo / DEFAULT_ARCHIVE_RELATIVE).resolve()
    )

    audit_path, audit = audit_state(repo)
    confirmatory_pass = bool(audit.get("confirmatoryPass", False))
    if not confirmatory_pass and not args.allow_open_v6:
        raise SystemExit(
            "Final cleanup refused: V6_BREADTH_AUDIT.json exists but "
            "confirmatoryPass is not true. If the project is intentionally finished "
            "despite an OPEN result, rerun with --allow-open-v6."
        )

    verify_repo_delete_targets_untracked(repo)
    targets = deletion_targets(repo, home, archive)
    if args.keep_datasets:
        targets = [item for item in targets if item["kind"] == "repo-generated"]

    total = sum(int(item["bytes"]) for item in targets)
    print("MAVEB FINAL CLEANUP")
    print("=" * 72)
    print(f"repo             : {repo}")
    print(f"v6 audit         : {audit_path}")
    print(f"confirmatoryPass : {confirmatory_pass}")
    print(f"archive          : {archive}")
    print(f"mode             : {'EXECUTE' if args.execute else 'DRY RUN'}")
    print()
    print("ALLOW-LISTED DELETION TARGETS")
    print("-" * 72)
    for item in sorted(targets, key=lambda row: int(row["bytes"])):
        print(
            f"{human(int(item['bytes'])):>10}  "
            f"{item['kind']:<20} {item['path']}"
        )
    print("-" * 72)
    print(f"potential reclaim: {human(total)}")

    if not args.execute:
        print()
        print("Dry run only. Nothing was archived, moved, or deleted.")
        print("To execute after reviewing this list:")
        command = (
            "python3 maintenance/final_cleanup.py "
            "--execute --i-understand-this-deletes-data"
        )
        if args.allow_open_v6:
            command += " --allow-open-v6"
        if args.keep_datasets:
            command += " --keep-datasets"
        print(f"  {command}")
        return 0

    if not args.i_understand_this_deletes_data:
        raise SystemExit(
            "Destructive cleanup requires both --execute and "
            "--i-understand-this-deletes-data."
        )

    copied = archive_v6(repo, archive)
    manifest = {
        "schemaVersion": 1,
        "artifact": "maveb-final-cleanup-manifest",
        "v6Audit": str(audit_path),
        "confirmatoryPass": confirmatory_pass,
        "archive": str(archive),
        "archivedEvidence": copied,
        "deletionTargets": [
            {
                "kind": item["kind"],
                "path": str(item["path"]),
                "bytesBeforeDelete": int(item["bytes"]),
            }
            for item in targets
        ],
        "potentialReclaimBytes": total,
    }
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "FINAL_CLEANUP_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print("ARCHIVED FINAL EVIDENCE")
    print("-" * 72)
    for item in copied:
        print(f"{item['archive']}")

    print()
    print("DELETING ALLOW-LISTED MAVEB DATA")
    print("-" * 72)
    for item in targets:
        path = Path(item["path"])
        print(f"delete {human(int(item['bytes'])):>10}  {path}")
        delete_target(path)

    free = shutil.disk_usage(repo).free
    print()
    print(f"cleanup complete; filesystem free space now: {human(free)}")
    print(f"final evidence retained at: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
