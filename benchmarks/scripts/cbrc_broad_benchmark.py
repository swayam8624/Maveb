#!/usr/bin/env python3
"""Discover and normalize MAVEB's broad multi-dataset CBRC benchmark inputs.

This layer is intentionally evidence-first:
- downloaded dataset bytes remain outside Git;
- restricted/token-gated datasets are never fetched implicitly;
- every discovered scene/pair is frozen into a normalized JSON record before execution;
- missing assets are reported as blocked, never as a synthetic/pass substitute.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "research/config/cbrc_broad_benchmark_suite.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def configured_root(dataset: dict[str, Any]) -> Path | None:
    env_name = str(dataset.get("rootEnv", "")).strip()
    if env_name:
        value = os.environ.get(env_name)
        if value:
            return Path(os.path.expanduser(os.path.expandvars(value))).resolve()
    if dataset["id"] == "existing-public-v2":
        return Path(
            os.environ.get(
                "MAVEB_PUBLIC_V2_RESULTS_DIR",
                str(ROOT / "build/public-real-v2"),
            )
        ).expanduser().resolve()
    return None


def status_record(dataset: dict[str, Any], root: Path | None) -> dict[str, Any]:
    return {
        "datasetId": dataset["id"],
        "kind": dataset["kind"],
        "role": dataset.get("role"),
        "rootEnv": dataset.get("rootEnv"),
        "root": None if root is None else str(root),
        "officialUrl": dataset.get("officialUrl"),
        "redistribute": bool(dataset.get("redistribute", False)),
        "scientificRole": dataset.get("scientificRole"),
        "status": "blocked",
        "scenes": [],
        "issues": [],
    }


def find_latest_ply(scene_root: Path) -> Path | None:
    candidates = list(scene_root.glob("point_cloud/iteration_*/point_cloud.ply"))
    if not candidates:
        candidates = list(scene_root.glob("**/point_cloud/iteration_*/point_cloud.ply"))
    if not candidates:
        return None

    def iteration(path: Path) -> int:
        match = re.search(r"iteration_(\d+)", path.as_posix())
        return int(match.group(1)) if match else -1

    return max(candidates, key=lambda p: (iteration(p), p.as_posix()))


def graphdeco(dataset: dict[str, Any], root: Path | None) -> dict[str, Any]:
    result = status_record(dataset, root)
    if root is None or not root.is_dir():
        result["issues"].append("Set MAVEB_GRAPHDECO_PRETRAINED to the extracted official models.zip root.")
        return result

    for scene in dataset["selection"]["scenes"]:
        roots = [
            root / scene,
            root / "output" / scene,
            root / "pretrained" / scene,
            root / "models" / scene,
        ]
        scene_root = next((candidate for candidate in roots if candidate.is_dir()), None)
        if scene_root is None:
            result["scenes"].append(
                {"sceneId": scene, "status": "blocked", "reason": "scene-directory-missing"}
            )
            continue
        ply = find_latest_ply(scene_root)
        if ply is None:
            result["scenes"].append(
                {
                    "sceneId": scene,
                    "status": "blocked",
                    "root": str(scene_root),
                    "reason": "trained-point-cloud-missing",
                }
            )
            continue
        cameras = scene_root / "cameras.json"
        result["scenes"].append(
            {
                "sceneId": scene,
                "status": "ready",
                "root": str(scene_root),
                "representation": "trained-3dgs",
                "pointCloud": str(ply.resolve()),
                "pointCloudBytes": ply.stat().st_size,
                "pointCloudSha256": sha256(ply),
                "cameras": str(cameras.resolve()) if cameras.is_file() else None,
            }
        )

    ready = sum(scene["status"] == "ready" for scene in result["scenes"])
    expected = len(dataset["selection"]["scenes"])
    result["readyScenes"] = ready
    result["expectedScenes"] = expected
    result["status"] = "ready" if ready == expected else ("partial" if ready else "blocked")
    return result


def scan_ready(root: Path, scan_id: str, required: Iterable[str], sequence_any: Iterable[str]) -> tuple[bool, list[str]]:
    scan = root / scan_id
    missing = [name for name in required if not (scan / name).exists()]
    if not any((scan / name).exists() for name in sequence_any):
        missing.append("sequence-or-sequence.zip")
    return not missing, missing


def three_r_scan(dataset: dict[str, Any], root: Path | None) -> dict[str, Any]:
    result = status_record(dataset, root)
    if root is None or not root.is_dir():
        result["issues"].append("Set MAVEB_3RSCAN to the 3RScan dataset root containing 3RScan.json.")
        return result
    metadata_path = root / dataset.get("metadata", "3RScan.json")
    if not metadata_path.is_file():
        result["issues"].append(f"Missing metadata: {metadata_path}")
        return result

    payload = load_json(metadata_path)
    preferred = str(dataset["selection"].get("preferredSplit", "")).lower()
    target = int(dataset["selection"].get("targetPairs", 40))
    minimum_changes = int(dataset["selection"].get("minimumRigidOrRemovedChanges", 1))
    candidates: list[dict[str, Any]] = []
    for scene in payload:
        split = str(scene.get("type", "")).lower()
        if preferred and preferred not in split and not (
            preferred == "val" and "validation" in split
        ):
            continue
        reference = str(scene.get("reference", ""))
        if not reference:
            continue
        ref_ok, ref_missing = scan_ready(
            root, reference, dataset["scanRequired"], dataset["sequenceAny"]
        )
        for rescan in scene.get("scans", []):
            rescan_id = str(rescan.get("reference", ""))
            if not rescan_id:
                continue
            rigid = list(rescan.get("rigid", []) or [])
            removed = list(rescan.get("removed", []) or [])
            nonrigid = list(rescan.get("nonrigid", []) or [])
            change_count = len(rigid) + len(removed) + len(nonrigid)
            if change_count < minimum_changes:
                continue
            scan_ok, scan_missing = scan_ready(
                root, rescan_id, dataset["scanRequired"], dataset["sequenceAny"]
            )
            candidates.append(
                {
                    "sceneId": reference,
                    "pairId": f"{reference}__{rescan_id}",
                    "referenceScan": reference,
                    "rescan": rescan_id,
                    "status": "ready" if ref_ok and scan_ok else "blocked",
                    "referenceRoot": str((root / reference).resolve()),
                    "rescanRoot": str((root / rescan_id).resolve()),
                    "referenceMissing": ref_missing,
                    "rescanMissing": scan_missing,
                    "sceneToReferenceTransform": rescan.get("transform"),
                    "rigidChanges": rigid,
                    "removedInstances": removed,
                    "nonrigidInstances": nonrigid,
                    "changeCount": change_count,
                    "split": split,
                }
            )

    candidates.sort(key=lambda item: (-item["changeCount"], item["pairId"]))
    selected = candidates[:target]
    result["scenes"] = selected
    result["availableChangedPairs"] = len(candidates)
    result["selectedPairs"] = len(selected)
    ready = sum(item["status"] == "ready" for item in selected)
    result["readyScenes"] = ready
    result["status"] = "ready" if ready == len(selected) and ready else ("partial" if ready else "blocked")
    if not selected:
        result["issues"].append("No changed reference/rescan pairs matched the frozen selection rule.")
    return result


def split_file(root: Path, split: str) -> Path | None:
    for parent in ("split", "splits"):
        candidate = root / parent / f"{split}.txt"
        if candidate.is_file():
            return candidate
    return None


def scannetpp(dataset: dict[str, Any], root: Path | None) -> dict[str, Any]:
    result = status_record(dataset, root)
    if root is None or not root.is_dir():
        result["issues"].append("Set MAVEB_SCANNETPP after your ScanNet++ access application is approved.")
        return result
    split = str(dataset["selection"]["split"])
    split_path = split_file(root, split)
    if split_path is None:
        result["issues"].append(f"Missing ScanNet++ split file for {split}.")
        return result

    ids = [line.strip() for line in split_path.read_text().splitlines() if line.strip()]
    ids = ids[: int(dataset["selection"].get("targetScenes", 20))]
    data_root = root / "data" if (root / "data").is_dir() else root
    for scene_id in ids:
        scene = data_root / scene_id
        missing = [relative for relative in dataset["required"] if not (scene / relative).exists()]
        dslr_colmap = scene / "dslr/colmap"
        iphone_colmap = scene / "iphone/colmap"
        result["scenes"].append(
            {
                "sceneId": scene_id,
                "status": "ready" if not missing else "blocked",
                "root": str(scene.resolve()),
                "missing": missing,
                "laserMesh": str((scene / "scans/mesh_aligned_0.05.ply").resolve())
                if (scene / "scans/mesh_aligned_0.05.ply").is_file()
                else None,
                "dslrColmap": str(dslr_colmap.resolve()) if dslr_colmap.is_dir() else None,
                "iphoneColmap": str(iphone_colmap.resolve()) if iphone_colmap.is_dir() else None,
                "dslrSplit": str((scene / "dslr/train_test_lists.json").resolve())
                if (scene / "dslr/train_test_lists.json").is_file()
                else None,
            }
        )
    ready = sum(scene["status"] == "ready" for scene in result["scenes"])
    result["readyScenes"] = ready
    result["expectedScenes"] = len(ids)
    result["status"] = "ready" if ready == len(ids) and ready else ("partial" if ready else "blocked")
    return result


def arkit(dataset: dict[str, Any], root: Path | None) -> dict[str, Any]:
    result = status_record(dataset, root)
    if root is None or not root.is_dir():
        result["issues"].append("Set MAVEB_ARKITSCENES to downloaded ARKitScenes raw data.")
        return result

    video_roots = sorted({path.parent for path in root.rglob("lowres_wide.traj")})
    target = int(dataset["selection"].get("targetVideos", 20))
    selected = video_roots[:target]
    required = list(dataset["requiredAny"])
    for video in selected:
        missing = [name for name in required if not (video / name).exists()]
        result["scenes"].append(
            {
                "sceneId": video.name,
                "status": "ready" if not missing else "blocked",
                "root": str(video.resolve()),
                "missing": missing,
                "representation": "mobile-rgbd",
            }
        )
    ready = sum(scene["status"] == "ready" for scene in result["scenes"])
    result["availableVideos"] = len(video_roots)
    result["readyScenes"] = ready
    result["expectedScenes"] = len(selected)
    result["status"] = "ready" if ready == len(selected) and ready else ("partial" if ready else "blocked")
    if not selected:
        result["issues"].append("No ARKitScenes lowres_wide.traj sequences discovered.")
    return result


def bonn(dataset: dict[str, Any], root: Path | None) -> dict[str, Any]:
    result = status_record(dataset, root)
    if root is None or not root.is_dir():
        result["issues"].append("Set MAVEB_BONN_RGBD to the extracted Bonn RGB-D Dynamic sequences.")
        return result
    required = list(dataset["required"])
    candidates = sorted(
        {
            path.parent
            for name in required
            for path in root.rglob(name)
            if path.parent.is_dir()
        }
    )
    complete = [path for path in candidates if all((path / name).is_file() for name in required)]
    target = int(dataset["selection"].get("targetSequences", 12))
    selected = complete[:target]
    for sequence in selected:
        def rows(name: str) -> int:
            return sum(
                1
                for line in (sequence / name).read_text(errors="replace").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            )
        result["scenes"].append(
            {
                "sceneId": sequence.name,
                "status": "ready",
                "root": str(sequence.resolve()),
                "rgbRows": rows("rgb.txt"),
                "depthRows": rows("depth.txt"),
                "groundTruthRows": rows("groundtruth.txt"),
                "camera": dataset["camera"],
                "representation": "dynamic-rgbd",
            }
        )
    result["availableSequences"] = len(complete)
    result["readyScenes"] = len(selected)
    result["expectedScenes"] = len(selected)
    result["status"] = "ready" if selected else "blocked"
    if not selected:
        result["issues"].append("No complete TUM-format Bonn sequences found.")
    return result


def existing(dataset: dict[str, Any], root: Path | None) -> dict[str, Any]:
    result = status_record(dataset, root)
    if root is None or not root.is_dir():
        result["issues"].append("Existing public-v2 campaign directory is not present.")
        return result
    candidates = [
        root / "campaign/campaign-rows.jsonl",
        root / "campaign-rows.jsonl",
    ]
    rows = next((path for path in candidates if path.is_file()), None)
    if rows is None:
        result["issues"].append("campaign-rows.jsonl not found.")
        return result
    count = sum(1 for line in rows.read_text().splitlines() if line.strip())
    result["status"] = "ready"
    result["readyScenes"] = 4
    result["scenes"] = [
        {
            "sceneId": "frozen-public-v2",
            "status": "ready",
            "campaignRows": str(rows.resolve()),
            "revisionCases": count,
        }
    ]
    return result


RESOLVERS = {
    "trained-3dgs": graphdeco,
    "longitudinal-rgbd": three_r_scan,
    "scannetpp": scannetpp,
    "arkit-scenes": arkit,
    "tum-rgbd": bonn,
    "existing-campaign": existing,
}


def normalize(config: dict[str, Any]) -> dict[str, Any]:
    datasets = []
    for dataset in config["datasets"]:
        resolver = RESOLVERS[dataset["kind"]]
        datasets.append(resolver(dataset, configured_root(dataset)))
    return {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-broad-benchmark-import",
        "campaignId": config["campaignId"],
        "freezePolicy": config["freezePolicy"],
        "editFamilies": config["editFamilies"],
        "datasets": datasets,
        "readyDatasets": sum(item["status"] == "ready" for item in datasets),
        "partialDatasets": sum(item["status"] == "partial" for item in datasets),
        "blockedDatasets": sum(item["status"] == "blocked" for item in datasets),
    }


def download_plan(config: dict[str, Any]) -> dict[str, Any]:
    datasets = {item["id"]: item for item in config["datasets"]}
    return {
        "graphdeco-pretrained-3dgs": {
            "automatic": True,
            "commands": [
                "mkdir -p \"$MAVEB_DATA/graphdeco-pretrained\"",
                "curl -L --fail --retry 3 -o \"$MAVEB_DATA/graphdeco-pretrained/models.zip\" "
                + datasets["graphdeco-pretrained-3dgs"]["officialUrl"],
                "unzip -q \"$MAVEB_DATA/graphdeco-pretrained/models.zip\" -d \"$MAVEB_DATA/graphdeco-pretrained/models\"",
                "export MAVEB_GRAPHDECO_PRETRAINED=\"$MAVEB_DATA/graphdeco-pretrained/models\"",
            ],
            "note": "Official GraphDECO pretrained archive; large (~14 GB).",
        },
        "3rscan": {
            "automatic": False,
            "note": "Use the official 3RScan download tooling/terms, extract selected scan folders and sequence.zip files, then set MAVEB_3RSCAN.",
            "officialUrl": datasets["3rscan"]["officialUrl"],
        },
        "scannetpp": {
            "automatic": False,
            "note": "Requires an approved ScanNet++ account/token. Download only the frozen validation subset and set MAVEB_SCANNETPP.",
            "officialUrl": datasets["scannetpp"]["officialUrl"],
        },
        "arkitscenes": {
            "automatic": False,
            "note": "Use Apple's download_data.py to fetch selected raw video IDs, then set MAVEB_ARKITSCENES.",
            "officialUrl": datasets["arkitscenes"]["officialUrl"],
        },
        "bonn-rgbd-dynamic": {
            "automatic": False,
            "note": "Download the selected official sequences (or the 16.4 GB all-sequences archive), extract them, then set MAVEB_BONN_RGBD.",
            "officialUrl": datasets["bonn-rgbd-dynamic"]["officialUrl"],
        },
    }


def print_table(payload: dict[str, Any]) -> None:
    print(f"{'DATASET':<30} {'STATUS':<9} {'READY':>5}  ROLE")
    for item in payload["datasets"]:
        print(
            f"{item['datasetId']:<30} {item['status']:<9} "
            f"{int(item.get('readyScenes', 0)):>5}  {item.get('role') or ''}"
        )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="MAVEB broad CBRC dataset importer")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    imp = sub.add_parser("import")
    imp.add_argument("--output", type=Path, required=True)
    plan = sub.add_parser("download-plan")
    plan.add_argument("--output", type=Path)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = load_json(args.config.resolve())
    if config.get("schemaVersion") != 1:
        raise SystemExit("unsupported broad benchmark config schema")
    if args.command == "download-plan":
        payload = download_plan(config)
        if args.output:
            write_json(args.output.resolve(), payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    payload = normalize(config)
    if args.command == "import":
        write_json(args.output.resolve(), payload)
        print(args.output.resolve())
    else:
        print_table(payload)
    return 0 if payload["blockedDatasets"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
