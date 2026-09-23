#!/usr/bin/env python3
"""Prepare normalized dataset scenes as immutable MAVEB Gaussian worlds.

Supported preparation paths:
- official pretrained GraphDECO 3DGS PLY -> trained-3DGS world seeder;
- ScanNet++ DSLR COLMAP model -> deterministic SfM-seeded Gaussian world;
- 3RScan -> provided reference mesh -> canonical proxy -> Gaussian world;
- ARKitScenes / Bonn RGB-D -> registered depth + provided pose -> canonical proxy -> Gaussian world.

RGB/SfM remains an explicit fallback for native-preparation failures. Every fallback records the
native failure in the world manifest; benchmark acceptance/gating is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
COLMAP_SEEDER = ROOT / "benchmarks/scripts/cbrc_seed_colmap_world.py"
NATIVE_PROXY = ROOT / "benchmarks/scripts/cbrc_native_proxy.py"


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


def overlap_preserving_sample(
    paths: list[Path], maximum: int, maximum_stride: int = 8
) -> list[Path]:
    """Choose a deterministic temporal crop while retaining inter-frame overlap."""
    ordered = sorted(paths)
    if maximum <= 0 or len(ordered) <= maximum:
        return ordered
    if maximum == 1:
        return [ordered[len(ordered) // 2]]
    stride = max(1, min(maximum_stride, (len(ordered) - 1) // (maximum - 1)))
    span = stride * (maximum - 1)
    start = max(0, (len(ordered) - 1 - span) // 2)
    return [ordered[start + index * stride] for index in range(maximum)]


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
        return overlap_preserving_sample(list(sequence.glob("frame-*.color.jpg")), maximum)
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
        selected = overlap_preserving_sample([Path(name) for name in members], maximum)
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
    return overlap_preserving_sample(images, maximum)


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
    return overlap_preserving_sample(rows, maximum)


def find_model(root: Path) -> Path | None:
    direct = [root / "points3D.bin", root / "points3D.txt"]
    if any(path.is_file() for path in direct):
        return root
    candidates = []
    for name in ("points3D.bin", "points3D.txt"):
        candidates.extend(path.parent for path in root.rglob(name))
    return sorted(set(candidates), key=lambda p: (len(p.parts), p.as_posix()))[0] if candidates else None


def model_point_count(model: Path) -> int:
    binary = model / "points3D.bin"
    if binary.is_file():
        with binary.open("rb") as stream:
            raw = stream.read(8)
        return int(struct.unpack("<Q", raw)[0]) if len(raw) == 8 else 0
    text = model / "points3D.txt"
    if text.is_file():
        return sum(
            1
            for line in text.read_text(errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return 0


def usable_model(root: Path, minimum_points: int = 64) -> Path | None:
    model = find_model(root)
    if model is None:
        return None
    return model if model_point_count(model) >= minimum_points else None


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

    primary_matcher = "sequential_matcher" if sequential else "exhaustive_matcher"
    run(
        [colmap, primary_matcher, "--database_path", str(database)],
        workspace / f"{primary_matcher}.log",
    )

    def reset_sparse() -> None:
        if sparse.exists():
            shutil.rmtree(sparse)
        sparse.mkdir(parents=True)

    def map_once(log_name: str) -> tuple[Path | None, str | None]:
        try:
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
                workspace / log_name,
            )
            error = None
        except RuntimeError as exc:
            error = str(exc)
        return usable_model(sparse), error

    model, primary_error = map_once("mapper.log")
    if model is not None:
        return model, count

    # Stable temporal subsampling can make neighbouring staged frames too far
    # apart for sequential matching. Keep the first attempt for provenance,
    # then deterministically add all-pairs matches and retry from a clean
    # sparse directory. This is a preparation fallback, not CBRC retuning.
    if primary_matcher != "exhaustive_matcher":
        run(
            [colmap, "exhaustive_matcher", "--database_path", str(database)],
            workspace / "exhaustive_matcher_fallback.log",
        )
        reset_sparse()
        model, fallback_error = map_once("mapper_exhaustive_fallback.log")
        if model is not None:
            return model, count
        raise RuntimeError(
            "COLMAP reconstruction failed after sequential and exhaustive matching.\n"
            f"primary: {primary_error or 'model had fewer than 64 points'}\n"
            f"fallback: {fallback_error or 'model had fewer than 64 points'}"
        )

    raise RuntimeError(
        "COLMAP reconstruction failed after exhaustive matching: "
        + (primary_error or "model had fewer than 64 points")
    )


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
            "--minimum-track-length",
            "2",
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
            "--clamp-log-scale",
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


def seed_native_proxy(
    proxy: Path,
    world: Path,
    *,
    native_seeder: str,
) -> None:
    run(
        [
            native_seeder,
            "--proxy",
            str(proxy),
            "--output",
            str(world),
            "--max-gaussians",
            "750000",
            "--json",
        ],
        world.parent / f"{world.stem}.native-seed.log",
        cwd=ROOT,
    )


def prepare_native(
    dataset: dict[str, Any],
    scene: dict[str, Any],
    output: Path,
    cache: Path,
    *,
    native_seeder: str,
    maximum_images: int,
    ffmpeg: str | None,
) -> dict[str, Any]:
    kind = dataset["kind"]
    if kind == "longitudinal-rgbd":
        scene_id = scene.get("pairId") or scene["referenceScan"]
        source = Path(scene["referenceRoot"]) / "mesh.refined.v2.obj"
        proxy_kind = "3rscan"
        extra: list[str] = []
        source_geometry = str(source)
    elif kind == "arkit-scenes":
        scene_id = scene["sceneId"]
        source = Path(scene["root"])
        proxy_kind = "arkitscenes"
        extra = []
        source_geometry = str(source)
        if ffmpeg is None:
            raise RuntimeError("ffmpeg not found for ARKitScenes native RGB-D preparation")
        extra.extend(["--ffmpeg", ffmpeg])
    elif kind == "tum-rgbd":
        scene_id = scene["sceneId"]
        source = Path(scene["root"])
        proxy_kind = "bonn-rgbd"
        camera = scene.get("camera") or {}
        source_geometry = str(source)
        if ffmpeg is None:
            raise RuntimeError("ffmpeg not found for Bonn native RGB-D preparation")
        extra = [
            "--ffmpeg",
            ffmpeg,
            "--width",
            "640",
            "--height",
            "480",
            "--fx",
            str(camera.get("fx", 542.822841)),
            "--fy",
            str(camera.get("fy", 542.576870)),
            "--cx",
            str(camera.get("cx", 315.593520)),
            "--cy",
            str(camera.get("cy", 237.756098)),
        ]
    else:
        raise ValueError(f"unsupported native dataset kind: {kind}")

    workspace = cache / "native" / dataset["datasetId"] / scene_id
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    proxy = workspace / "proxy.ply"
    argv = [
        sys.executable,
        str(NATIVE_PROXY),
        "--kind",
        proxy_kind,
        "--source",
        str(source),
        "--output",
        str(proxy),
        "--max-frames",
        str(maximum_images),
        "--target-diagonal",
        "2.0",
        *extra,
    ]
    run(argv, workspace / "native-proxy.log", cwd=ROOT)

    world = output / dataset["datasetId"] / f"{scene_id}.aetherworld"
    world.parent.mkdir(parents=True, exist_ok=True)
    seed_native_proxy(proxy, world, native_seeder=native_seeder)
    return {
        "datasetId": dataset["datasetId"],
        "sceneId": scene_id,
        "status": "ready",
        "world": str(world.resolve()),
        "representation": "dataset-native-geometry-seeded-gaussians",
        "preparationPath": "dataset-native-geometry",
        "source": source_geometry,
        "proxy": str(proxy.resolve()),
        "nativeProvenance": str(Path(str(proxy) + ".source.json").resolve()),
        "sourceRole": dataset.get("role"),
        "naturalChangePair": scene.get("pairId"),
        "referenceScan": scene.get("referenceScan"),
        "rescan": scene.get("rescan"),
    }


def prepare_reconstructed(
    dataset: dict[str, Any],
    scene: dict[str, Any],
    output: Path,
    cache: Path,
    *,
    colmap: str | None,
    native_seeder: str | None,
    maximum_images: int,
    ffmpeg: str | None,
    allow_rgb_fallback: bool,
) -> dict[str, Any]:
    native_error: str | None = None
    if native_seeder is not None:
        try:
            return prepare_native(
                dataset,
                scene,
                output,
                cache,
                native_seeder=native_seeder,
                maximum_images=maximum_images,
                ffmpeg=ffmpeg,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            native_error = str(exc)
    else:
        native_error = "maveb-seed-world not found"

    if not allow_rgb_fallback:
        raise RuntimeError(
            "dataset-native preparation failed and RGB reconstruction fallback is disabled: "
            + (native_error or "unknown native preparation failure")
        )
    if colmap is None:
        raise RuntimeError(
            "dataset-native preparation failed and COLMAP fallback is unavailable: "
            + (native_error or "unknown native preparation failure")
        )

    kind = dataset["kind"]
    if kind == "longitudinal-rgbd":
        images = three_r_scan_images(scene, cache, maximum_images)
        scene_id = scene.get("pairId") or scene["referenceScan"]
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
    try:
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
    except (OSError, RuntimeError, ValueError) as fallback_error:
        raise RuntimeError(
            "dataset-native preparation failed:\n"
            + (native_error or "unknown native preparation failure")
            + "\nRGB/COLMAP fallback failed:\n"
            + str(fallback_error)
        ) from fallback_error
    return {
        "datasetId": dataset["datasetId"],
        "sceneId": scene_id,
        "status": "ready",
        "world": str(world.resolve()),
        "representation": "rgb-derived-colmap-seeded-gaussians",
        "preparationPath": "rgb-colmap-fallback",
        "source": str(model),
        "stagedRgbFrames": image_count,
        "nativePreparationError": native_error,
        "sourceRole": dataset.get("role"),
        "naturalChangePair": scene.get("pairId"),
        "referenceScan": scene.get("referenceScan"),
        "rescan": scene.get("rescan"),
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
    p.add_argument(
        "--no-rgb-reconstruction",
        action="store_true",
        help="Disable only the RGB/COLMAP fallback; dataset-native preparation still runs.",
    )
    p.add_argument("--colmap")
    p.add_argument("--ffmpeg")
    p.add_argument("--trained-seeder")
    p.add_argument("--native-seeder")
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
    native = args.native_seeder or executable(
        [
            ROOT / "build/ci/tools/maveb-seed-world/maveb-seed-world",
            ROOT / "build/debug/tools/maveb-seed-world/maveb-seed-world",
            "maveb-seed-world",
        ]
    )
    ffmpeg = args.ffmpeg or executable(["ffmpeg"])

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
                    record = prepare_reconstructed(
                        dataset,
                        scene,
                        output,
                        cache,
                        colmap=colmap,
                        native_seeder=native,
                        maximum_images=args.max_images,
                        ffmpeg=ffmpeg,
                        allow_rgb_fallback=not args.no_rgb_reconstruction,
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
                    "sceneId": scene.get("pairId") or scene.get("sceneId"),
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
        "ffmpeg": ffmpeg,
        "trainedSeeder": trained,
        "nativeSeeder": native,
        "maximumSourceFramesPerScene": args.max_images,
        "records": records,
        "readyWorlds": sum(record.get("status") == "ready" for record in records),
        "blockedWorlds": sum(record.get("status") == "blocked" for record in records),
        "failedWorlds": sum(record.get("status") == "failed" for record in records),
        "nativePreparedWorlds": sum(
            record.get("preparationPath") == "dataset-native-geometry" for record in records
        ),
        "rgbFallbackWorlds": sum(
            record.get("preparationPath") == "rgb-colmap-fallback" for record in records
        ),
        "scientificBoundary": (
            "GraphDECO entries preserve trained 3DGS representations. ScanNet++ uses its provided "
            "DSLR COLMAP sparse model. 3RScan/ARKitScenes/Bonn prefer dataset-native geometry or "
            "registered depth plus provided poses, uniformly canonicalized to the same 2 m broad-"
            "benchmark scene-diagonal convention. RGB-derived COLMAP is retained only as an explicit "
            "per-scene fallback and its native-preparation failure is recorded in provenance. No "
            "dataset-specific CBRC threshold or result gate is changed."
        ),
    }
    write(output / "BROAD_WORLDS.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 1 if manifest["failedWorlds"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
