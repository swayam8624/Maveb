#!/usr/bin/env python3
"""Prepare normalized dataset scenes as immutable MAVEB Gaussian worlds.

Supported preparation paths:
- official pretrained GraphDECO 3DGS PLY -> trained-3DGS world seeder;
- ScanNet++ DSLR COLMAP model -> deterministic SfM-seeded Gaussian world;
- 3RScan / ARKitScenes / Bonn RGB-D -> deterministic RGB staging -> COLMAP sparse model
  -> SfM-seeded Gaussian world.

The RGB-D fallback deliberately uses RGB/SfM for the CBRC output-side world. Metric depth/pose
assets remain in the imported provenance and are not relabeled as part of the Gaussian seeding.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
COLMAP_SEEDER = ROOT / "benchmarks/scripts/cbrc_seed_colmap_world.py"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def executable(candidates: Iterable[Path | str]) -> str | None:
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        found = shutil.which(str(candidate))
        if found:
            return found
    return None


def run(argv: list[str], log: Path, cwd: Path | None = None) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log.write_text(process.stdout, encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(
            f"command failed ({process.returncode}): {' '.join(argv)}\n"
            f"{process.stdout[-4000:]}"
        )


def stable_sample(paths: list[Path], maximum: int) -> list[Path]:
    paths = sorted(paths)
    if maximum <= 0 or len(paths) <= maximum:
        return paths
    if maximum == 1:
        return [paths[len(paths) // 2]]
    chosen = []
    for index in range(maximum):
        source = round(index * (len(paths) - 1) / (maximum - 1))
        chosen.append(paths[source])
    return list(dict.fromkeys(chosen))


def stage_images(paths: list[Path], output: Path, maximum: int) -> int:
    selected = stable_sample([p for p in paths if p.is_file()], maximum)
    if len(selected) < 8:
        raise ValueError(f"need at least 8 RGB frames for COLMAP, found {len(selected)}")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for index, source in enumerate(selected):
        suffix = source.suffix.lower() if source.suffix else ".jpg"
        target = output / f"{index:06d}{suffix}"
        try:
            target.symlink_to(source.resolve())
        except OSError:
            shutil.copy2(source, target)
    return len(selected)


def three_r_scan_images(scene: dict[str, Any], cache: Path, maximum: int) -> list[Path]:
    root = Path(scene["referenceRoot"])
    sequence = root / "sequence"
    if sequence.is_dir():
        return stable_sample(list(sequence.glob("frame-*.color.jpg")), maximum)
    archive = root / "sequence.zip"
    if not archive.is_file():
        return []
    target = cache / "3rscan" / scene["referenceScan"]
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        members = sorted(
            name
            for name in zf.namelist()
            if name.endswith(".color.jpg") and "frame-" in Path(name).name
        )
        selected = stable_sample([Path(name) for name in members], maximum)
        result = []
        for member_path in selected:
            destination = target / member_path.name
            if not destination.is_file():
                with zf.open(member_path.as_posix()) as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            result.append(destination)
        return result


def arkit_images(scene: dict[str, Any], maximum: int) -> list[Path]:
    root = Path(scene["root"])
    images = list((root / "lowres_wide").glob("*.png"))
    images += list((root / "lowres_wide").glob("*.jpg"))
    return stable_sample(images, maximum)


def bonn_images(scene: dict[str, Any], maximum: int) -> list[Path]:
    root = Path(scene["root"])
    rows = []
    for line in (root / "rgb.txt").read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) >= 2:
            path = root / fields[1]
            if path.is_file():
                rows.append(path)
    return stable_sample(rows, maximum)


def find_model(root: Path) -> Path | None:
    direct = [root / "points3D.bin", root / "points3D.txt"]
    if any(path.is_file() for path in direct):
        return root
    candidates = []
    for name in ("points3D.bin", "points3D.txt"):
        candidates.extend(path.parent for path in root.rglob(name))
    return sorted(set(candidates), key=lambda p: (len(p.parts), p.as_posix()))[0] if candidates else None


def reconstruct_colmap(
    images: list[Path],
    workspace: Path,
    *,
    colmap: str,
    maximum_images: int,
    sequential: bool,
) -> tuple[Path, int]:
    staged = workspace / "images"
    count = stage_images(images, staged, maximum_images)
    database = workspace / "database.db"
    sparse = workspace / "sparse"
    if database.exists():
        database.unlink()
    if sparse.exists():
        shutil.rmtree(sparse)
    sparse.mkdir(parents=True)

    run(
        [
            colmap,
            "feature_extractor",
            "--database_path",
            str(database),
            "--image_path",
            str(staged),
            "--ImageReader.single_camera",
            "1",
        ],
        workspace / "feature_extractor.log",
    )
    matcher = "sequential_matcher" if sequential else "exhaustive_matcher"
    run(
        [colmap, matcher, "--database_path", str(database)],
        workspace / f"{matcher}.log",
    )
    run(
        [
            colmap,
            "mapper",
            "--database_path",
            str(database),
            "--image_path",
            str(staged),
            "--output_path",
            str(sparse),
        ],
        workspace / "mapper.log",
    )
    model = find_model(sparse)
    if model is None:
        raise RuntimeError("COLMAP mapper completed without a points3D model")
    return model, count


def seed_colmap(
    model: Path,
    output: Path,
    *,
    dataset_id: str,
    scene_id: str,
    source_url: str,
) -> None:
    run(
        [
            sys.executable,
            str(COLMAP_SEEDER),
            "--model-dir",
            str(model),
            "--output",
            str(output),
            "--scene-id",
            f"{dataset_id}--{scene_id}",
            "--source-id",
            dataset_id,
            "--source-url",
            source_url,
            "--maximum-points",
            "750000",
        ],
        output.parent / f"{scene_id}.seed.log",
        cwd=ROOT,
    )


def prepare_graphdeco(
    dataset: dict[str, Any],
    scene: dict[str, Any],
    output: Path,
    trained_seeder: str,
) -> dict[str, Any]:
    world = output / dataset["datasetId"] / f"{scene['sceneId']}.aetherworld"
    world.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            trained_seeder,
            "--ply",
            scene["pointCloud"],
            "--output",
            str(world),
            "--target-diagonal",
            "2.0",
            "--json",
        ],
        world.parent / f"{scene['sceneId']}.seed.log",
    )
    return {
        "datasetId": dataset["datasetId"],
        "sceneId": scene["sceneId"],
        "status": "ready",
        "world": str(world.resolve()),
        "representation": "trained-3dgs",
        "source": scene["pointCloud"],
    }


def prepare_scannetpp(
    dataset: dict[str, Any], scene: dict[str, Any], output: Path
) -> dict[str, Any]:
    model_root = Path(scene["dslrColmap"]) if scene.get("dslrColmap") else None
    model = find_model(model_root) if model_root and model_root.is_dir() else None
    if model is None:
        return {
            "datasetId": dataset["datasetId"],
            "sceneId": scene["sceneId"],
            "status": "blocked",
            "reason": "scannetpp-dslr-colmap-model-missing",
        }
    world = output / dataset["datasetId"] / f"{scene['sceneId']}.aetherworld"
    world.parent.mkdir(parents=True, exist_ok=True)
    seed_colmap(
        model,
        world,
        dataset_id=dataset["datasetId"],
        scene_id=scene["sceneId"],
        source_url=dataset.get("officialUrl") or "",
    )
    return {
        "datasetId": dataset["datasetId"],
        "sceneId": scene["sceneId"],
        "status": "ready",
        "world": str(world.resolve()),
        "representation": "scannetpp-dslr-colmap-seeded-gaussians",
        "source": str(model),
        "referenceGeometry": scene.get("laserMesh"),
    }


def prepare_reconstructed(
    dataset: dict[str, Any],
    scene: dict[str, Any],
    output: Path,
    cache: Path,
    *,
    colmap: str | None,
    maximum_images: int,
) -> dict[str, Any]:
    if colmap is None:
        return {
            "datasetId": dataset["datasetId"],
            "sceneId": scene.get("sceneId") or scene.get("pairId"),
            "status": "blocked",
            "reason": "colmap-not-found",
        }
    kind = dataset["kind"]
    if kind == "longitudinal-rgbd":
        images = three_r_scan_images(scene, cache, maximum_images)
        scene_id = scene["referenceScan"]
        sequential = True
    elif kind == "arkit-scenes":
        images = arkit_images(scene, maximum_images)
        scene_id = scene["sceneId"]
        sequential = True
    elif kind == "tum-rgbd":
        images = bonn_images(scene, maximum_images)
        scene_id = scene["sceneId"]
        sequential = True
    else:
        raise ValueError(f"unsupported reconstructed dataset kind: {kind}")

    workspace = cache / "colmap" / dataset["datasetId"] / scene_id
    workspace.mkdir(parents=True, exist_ok=True)
    model, image_count = reconstruct_colmap(
        images,
        workspace,
        colmap=colmap,
        maximum_images=maximum_images,
        sequential=sequential,
    )
    world = output / dataset["datasetId"] / f"{scene_id}.aetherworld"
    world.parent.mkdir(parents=True, exist_ok=True)
    seed_colmap(
        model,
        world,
        dataset_id=dataset["datasetId"],
        scene_id=scene_id,
        source_url=dataset.get("officialUrl") or "",
    )
    return {
        "datasetId": dataset["datasetId"],
        "sceneId": scene_id,
        "status": "ready",
        "world": str(world.resolve()),
        "representation": "rgb-derived-colmap-seeded-gaussians",
        "source": str(model),
        "stagedRgbFrames": image_count,
        "sourceRole": dataset.get("role"),
        "naturalChangePair": scene.get("pairId"),
    }


def copy_existing(dataset: dict[str, Any], output: Path) -> list[dict[str, Any]]:
    root = Path(dataset["root"]) if dataset.get("root") else None
    if root is None or not root.is_dir():
        return []
    source = root / "worlds"
    if not source.is_dir():
        source = root.parent / "worlds"
    records = []
    for world in sorted(source.rglob("*.aetherworld")) if source.is_dir() else []:
        target = output / dataset["datasetId"] / world.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(world, target)
        for sidecar in world.parent.glob(world.name + ".*"):
            shutil.copy2(sidecar, target.parent / sidecar.name)
        records.append(
            {
                "datasetId": dataset["datasetId"],
                "sceneId": world.stem,
                "status": "ready",
                "world": str(target.resolve()),
                "representation": "frozen-existing-public-v2",
                "source": str(world.resolve()),
            }
        )
    return records


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Prepare broad MAVEB CBRC worlds")
    p.add_argument("--import-manifest", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("--max-images", type=int, default=120)
    p.add_argument("--dataset", action="append", default=[])
    p.add_argument("--no-rgb-reconstruction", action="store_true")
    p.add_argument("--colmap")
    p.add_argument("--trained-seeder")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.max_images < 8:
        raise SystemExit("--max-images must be >= 8")
    imported = load(args.import_manifest.resolve())
    output = args.output_dir.resolve()
    cache = (args.cache_dir or (output / "_cache")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    selected = set(args.dataset)
    colmap = args.colmap or executable(
        [ROOT / ".aether-deps/bin/colmap", "colmap"]
    )
    trained = args.trained_seeder or executable(
        [
            ROOT / "build/ci/tools/maveb-seed-trained-3dgs-world/maveb-seed-trained-3dgs-world",
            ROOT / "build/debug/tools/maveb-seed-trained-3dgs-world/maveb-seed-trained-3dgs-world",
            "maveb-seed-trained-3dgs-world",
        ]
    )

    records: list[dict[str, Any]] = []
    for dataset in imported["datasets"]:
        dataset_id = dataset["datasetId"]
        if selected and dataset_id not in selected:
            continue
        if dataset["status"] == "blocked":
            records.append(
                {
                    "datasetId": dataset_id,
                    "status": "blocked",
                    "reason": "dataset-import-blocked",
                    "issues": dataset.get("issues", []),
                }
            )
            continue
        if dataset["kind"] == "existing-campaign":
            records.extend(copy_existing(dataset, output))
            continue
        for scene in dataset.get("scenes", []):
            if scene.get("status") != "ready":
                records.append(
                    {
                        "datasetId": dataset_id,
                        "sceneId": scene.get("sceneId") or scene.get("pairId"),
                        "status": "blocked",
                        "reason": "scene-import-blocked",
                    }
                )
                continue
            try:
                if dataset["kind"] == "trained-3dgs":
                    if trained is None:
                        raise RuntimeError("maveb-seed-trained-3dgs-world not found")
                    record = prepare_graphdeco(dataset, scene, output, trained)
                elif dataset["kind"] == "scannetpp":
                    record = prepare_scannetpp(dataset, scene, output)
                elif dataset["kind"] in {"longitudinal-rgbd", "arkit-scenes", "tum-rgbd"}:
                    if args.no_rgb_reconstruction:
                        record = {
                            "datasetId": dataset_id,
                            "sceneId": scene.get("sceneId") or scene.get("pairId"),
                            "status": "blocked",
                            "reason": "rgb-reconstruction-disabled",
                        }
                    else:
                        record = prepare_reconstructed(
                            dataset,
                            scene,
                            output,
                            cache,
                            colmap=colmap,
                            maximum_images=args.max_images,
                        )
                else:
                    record = {
                        "datasetId": dataset_id,
                        "sceneId": scene.get("sceneId"),
                        "status": "blocked",
                        "reason": f"unsupported-dataset-kind:{dataset['kind']}",
                    }
            except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
                record = {
                    "datasetId": dataset_id,
                    "sceneId": scene.get("sceneId") or scene.get("pairId"),
                    "status": "failed",
                    "reason": str(exc),
                }
            records.append(record)

    manifest = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-broad-prepared-worlds",
        "importManifest": str(args.import_manifest.resolve()),
        "outputRoot": str(output),
        "colmap": colmap,
        "trainedSeeder": trained,
        "maximumRgbFramesPerReconstructedScene": args.max_images,
        "records": records,
        "readyWorlds": sum(record.get("status") == "ready" for record in records),
        "blockedWorlds": sum(record.get("status") == "blocked" for record in records),
        "failedWorlds": sum(record.get("status") == "failed" for record in records),
        "scientificBoundary": (
            "GraphDECO entries preserve trained 3DGS representations. ScanNet++ uses its provided "
            "DSLR COLMAP sparse model. 3RScan/ARKitScenes/Bonn use deterministic RGB-derived COLMAP "
            "sparse geometry for the CBRC Gaussian output-side test; their metric depth/pose data are "
            "retained as independent dataset context and are not mislabeled as part of that seed."
        ),
    }
    write(output / "BROAD_WORLDS.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 1 if manifest["failedWorlds"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
