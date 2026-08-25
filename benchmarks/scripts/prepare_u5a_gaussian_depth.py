#!/usr/bin/env python3
"""Prepare U5a uncertainty-shaped Gaussian surfels and held-out FARO target views."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import tarfile

import numpy as np
from scipy.spatial.transform import Rotation

from ca1m_u3_pose_preflight import (
    decode_depth,
    discover_frames,
    parse_intrinsics,
    parse_pose,
    read_member,
)
from prepare_u3_ca1m_scene import sha256_file


STUDY_ID = "metric-uncertainty-u5a-gaussian-depth-v1"
CLARIFICATION_ID = "metric-uncertainty-u5a-target-camera-clarification-v1"
U3B_RESULT_SHA256 = "1b5e1635eb7491658a63058ca9cdeb0e1b4260bec049601c7c168fdca9ac165f"
U3C_SUMMARY_SHA256 = "652b2df1ae3811f23252af4469089ab4a2bd56ca12cdbea8e864b3d149505110"
U4A_RESULT_SHA256 = "e9c12349c08ab6d90f57cc02f61c367ad8a33ed54a38879aba8258684ff0cd49"
U3B_PREP_SHA256 = "acf41a5f094e30de1a8aa487db40b8a3e292ab18bc535aba8d2c6187800a88d3"
ACQUISITION_SHA256 = "3675d61e89599a36641e8d4ddb0dd28ce9722030af3b4672b70c401973695f73"
EXPECTED_SCENES = [
    "ca1m-48458481",
    "ca1m-48018737",
    "ca1m-45261587",
    "ca1m-42897538",
    "ca1m-48018375",
]
METHODS = (
    "depth-only-covariance",
    "calibrated-covariance",
    "shuffled-calibrated-covariance",
)


def validate_protocol(protocol_path: Path, clarification_path: Path) -> tuple[dict, dict]:
    protocol = json.loads(protocol_path.read_text())
    clarification = json.loads(clarification_path.read_text())
    if protocol.get("id") != STUDY_ID or protocol.get("status") != "frozen-before-u5a-gaussian-outcomes" or not protocol.get("frozen"):
        raise ValueError("U5a protocol is not frozen before Gaussian outcomes")
    if protocol.get("scenes") != EXPECTED_SCENES:
        raise ValueError("U5a scene order differs from the frozen protocol")
    parent = protocol["parentEvidence"]
    if parent["u3bPrimaryResultSha256"] != U3B_RESULT_SHA256:
        raise ValueError("U5a protocol U3b parent SHA mismatch")
    if parent["u3cSummarySha256"] != U3C_SUMMARY_SHA256:
        raise ValueError("U5a protocol U3c parent SHA mismatch")
    if parent["u4aGeometryResultSha256"] != U4A_RESULT_SHA256:
        raise ValueError("U5a protocol U4a parent SHA mismatch")
    if parent["u3bPreparationLedgerSha256"] != U3B_PREP_SHA256:
        raise ValueError("U5a protocol U3b preparation SHA mismatch")
    if clarification.get("id") != CLARIFICATION_ID or clarification.get("study") != STUDY_ID or not clarification.get("frozen"):
        raise ValueError("U5a target-camera clarification is not frozen")
    target = clarification["clarification"]
    if target["targetDepth"] != "gt/depth" or target["targetIntrinsics"] != "gt/depth/k" or target["targetPose"] != "gt/RT camera-to-world in FARO coordinates":
        raise ValueError("U5a target-camera clarification changed")
    return protocol, clarification


def camera_to_world_points(depth: np.ndarray, xs: np.ndarray, ys: np.ndarray,
                           intrinsics: tuple[float, float, float, float], pose: np.ndarray) -> np.ndarray:
    fx, fy, cx, cy = intrinsics
    z = depth
    camera = np.column_stack(((xs - cx) * z / fx, (ys - cy) * z / fy, z))
    return camera @ pose[:3, :3].T + pose[:3, 3]


def covariance_batch(xs: np.ndarray, ys: np.ndarray, depth: np.ndarray,
                     intrinsics: tuple[float, float, float, float], pose: np.ndarray,
                     sigma_z: np.ndarray, pixel_sigma: float) -> tuple[np.ndarray, np.ndarray]:
    fx, fy, cx, cy = intrinsics
    count = depth.size
    jacobian = np.zeros((count, 3, 3), dtype=np.float64)
    jacobian[:, 0, 0] = depth / fx
    jacobian[:, 0, 2] = (xs - cx) / fx
    jacobian[:, 1, 1] = depth / fy
    jacobian[:, 1, 2] = (ys - cy) / fy
    jacobian[:, 2, 2] = 1.0
    variances = np.column_stack(
        (
            np.full(count, pixel_sigma * pixel_sigma, dtype=np.float64),
            np.full(count, pixel_sigma * pixel_sigma, dtype=np.float64),
            sigma_z * sigma_z,
        )
    )
    camera_cov = np.einsum("nij,nj,nkj->nik", jacobian, variances, jacobian)
    rotation = pose[:3, :3]
    world_cov = np.einsum("ij,njk,lk->nil", rotation, camera_cov, rotation)
    eigenvalues, eigenvectors = np.linalg.eigh(world_cov)
    if not np.isfinite(eigenvalues).all() or np.any(eigenvalues <= 0.0):
        raise ValueError("U5a covariance eigendecomposition produced non-positive values")

    basis = eigenvectors.copy()
    for column in (0, 1):
        vectors = basis[:, :, column]
        dominant = np.argmax(np.abs(vectors), axis=1)
        signs = np.take_along_axis(vectors, dominant[:, None], axis=1)[:, 0]
        flip = signs < 0.0
        basis[flip, :, column] *= -1.0
    basis[:, :, 2] = np.cross(basis[:, :, 0], basis[:, :, 1])
    determinants = np.linalg.det(basis)
    if not np.allclose(determinants, 1.0, atol=1.0e-6):
        raise ValueError("U5a Gaussian basis is not right-handed")

    quat_xyzw = Rotation.from_matrix(basis).as_quat()
    quat_wxyz = np.column_stack(
        (quat_xyzw[:, 3], quat_xyzw[:, 0], quat_xyzw[:, 1], quat_xyzw[:, 2])
    )
    flip = quat_wxyz[:, 0] < 0.0
    quat_wxyz[flip] *= -1.0
    scales = np.sqrt(eigenvalues)
    return np.log(scales), quat_wxyz


def write_gaussian_ply(path: Path, positions: np.ndarray, log_scales: np.ndarray,
                       quaternions: np.ndarray, opacity_logit: float) -> None:
    if not (positions.shape == log_scales.shape and positions.ndim == 2 and positions.shape[1] == 3):
        raise ValueError("U5a Gaussian position/scale arrays have invalid shapes")
    if quaternions.shape != (positions.shape[0], 4):
        raise ValueError("U5a Gaussian quaternion array has invalid shape")
    path.parent.mkdir(parents=True, exist_ok=True)
    properties = [
        "x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
        "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3",
    ]
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("ply\n")
        stream.write("format ascii 1.0\n")
        stream.write(f"element vertex {positions.shape[0]}\n")
        for name in properties:
            stream.write(f"property float {name}\n")
        stream.write("end_header\n")
        for position, scale, quaternion in zip(positions, log_scales, quaternions, strict=True):
            values = [
                position[0], position[1], position[2], 0.0, 0.0, 0.0, opacity_logit,
                scale[0], scale[1], scale[2],
                quaternion[0], quaternion[1], quaternion[2], quaternion[3],
            ]
            stream.write(" ".join(f"{float(value):.9g}" for value in values) + "\n")


def target_indices(count: int, target_count: int = 8) -> list[int]:
    if count < target_count:
        raise ValueError("U5a target selection has fewer than eight eligible frames")
    result = [math.floor((2 * index + 1) * count / (2 * target_count)) for index in range(target_count)]
    if len(set(result)) != target_count or min(result) < 0 or max(result) >= count:
        raise ValueError("U5a target selection produced invalid or duplicate indices")
    return result


def world_to_camera_payload(pose: np.ndarray) -> tuple[list[float], list[float]]:
    rotation = pose[:3, :3]
    translation = pose[:3, 3]
    inverse_rotation = rotation.T
    inverse_translation = -inverse_rotation @ translation
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = inverse_rotation
    matrix[:3, 3] = inverse_translation
    return [float(value) for value in matrix.reshape(-1)], [float(value) for value in translation]


def method_sigma(method: str, depth: np.ndarray, confidence_u8: np.ndarray,
                 *, floor: float, quadratic: float, penalty: float) -> np.ndarray:
    base = floor + quadratic * depth * depth
    if method == "depth-only-covariance":
        return base
    confidence = confidence_u8.astype(np.float64) / 255.0
    return base * (1.0 + penalty * (1.0 - confidence))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--u3b-root", type=Path, required=True)
    parser.add_argument("--acquisition-ledger", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--clarification", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    protocol, _ = validate_protocol(args.protocol, args.clarification)
    if not args.acquisition_ledger.is_file() or sha256_file(args.acquisition_ledger) != ACQUISITION_SHA256:
        raise ValueError("U5a requires the exact frozen U3b acquisition ledger")
    prep_path = args.u3b_root / "primary-prepare-ledger.json"
    if not prep_path.is_file() or sha256_file(prep_path) != U3B_PREP_SHA256:
        raise ValueError("U5a requires the exact frozen U3b preparation ledger")
    prep = json.loads(prep_path.read_text())
    acquisition = json.loads(args.acquisition_ledger.read_text())
    prep_by_scene = {item["scene"]: item for item in prep["scenes"]}
    acquisition_by_video = {str(item["videoId"]): item for item in acquisition["entries"]}

    final_path = args.output_root / "preparation.json"
    if final_path.exists():
        raise ValueError("U5a preparation.json already exists; preparation will not be overwritten")
    if (args.output_root / "result.json").exists():
        raise ValueError("U5a result already exists")
    if list(args.output_root.glob("scenes/*/renders/*")):
        raise ValueError("U5a render outcomes already exist")
    args.output_root.mkdir(parents=True, exist_ok=True)

    sampling = protocol["representation"]["sampling"]
    stride = int(sampling["pixelStride"])
    pixel_sigma = stride / math.sqrt(12.0)
    opacity_logit = float(protocol["representation"]["opacity"]["logit"])
    model = protocol["frozenPredictiveModel"]
    floor = float(model["a"])
    quadratic = float(model["b"])
    penalty = float(model["k"])
    scene_records: list[dict] = []

    for scene in EXPECTED_SCENES:
        video_id = scene.removeprefix("ca1m-")
        prep_scene = prep_by_scene.get(scene)
        acquired = acquisition_by_video.get(video_id)
        if prep_scene is None or acquired is None:
            raise ValueError(f"U5a provenance is missing {scene}")
        source_scene = args.u3b_root / "scenes" / scene
        source_manifest_path = source_scene / "scene-manifest-relative.json"
        if not source_manifest_path.is_file() or sha256_file(source_manifest_path) != prep_scene["relativeManifestSha256"]:
            raise ValueError(f"U5a source manifest hash mismatch for {scene}")
        source_manifest = json.loads(source_manifest_path.read_text())
        if len(source_manifest["frames"]) != 8:
            raise ValueError(f"U5a requires eight frozen source frames for {scene}")
        source_timestamps = {str(frame["timestampNanoseconds"]) for frame in source_manifest["frames"]}
        scene_output = args.output_root / "scenes" / scene
        scene_output.mkdir(parents=True, exist_ok=True)

        method_chunks: dict[str, list[tuple[np.ndarray, np.ndarray, np.ndarray]]] = {
            method: [] for method in METHODS
        }
        sampled_observations = 0
        for frame in source_manifest["frames"]:
            width = int(frame["width"])
            height = int(frame["height"])
            depth = np.fromfile(source_scene / frame["depthPath"], dtype="<f4").reshape(height, width)
            intact = np.fromfile(source_scene / frame["confidencePath"], dtype=np.uint8).reshape(height, width)
            shuffled = np.fromfile(source_scene / frame["shuffledConfidencePath"], dtype=np.uint8).reshape(height, width)
            ys, xs = np.meshgrid(
                np.arange(0, height, stride, dtype=np.int64),
                np.arange(0, width, stride, dtype=np.int64),
                indexing="ij",
            )
            sampled_depth = depth[ys, xs].astype(np.float64)
            minimum_depth = float(source_manifest["volume"]["minimumDepthMetres"])
            maximum_depth = float(source_manifest["volume"]["maximumDepthMetres"])
            valid = np.isfinite(sampled_depth) & (sampled_depth >= minimum_depth) & (sampled_depth <= maximum_depth)
            if not np.any(valid):
                continue
            z = sampled_depth[valid]
            x = xs[valid].astype(np.float64)
            y = ys[valid].astype(np.float64)
            intact_values = intact[ys, xs][valid]
            shuffled_values = shuffled[ys, xs][valid]
            intrinsics = tuple(float(value) for value in frame["intrinsics"])
            q = frame["poseQuaternionWxyz"]
            from scipy.spatial.transform import Rotation as _Rotation
            rotation = _Rotation.from_quat([q[1], q[2], q[3], q[0]]).as_matrix()
            pose = np.eye(4, dtype=np.float64)
            pose[:3, :3] = rotation
            pose[:3, 3] = np.asarray(frame["poseTranslationMetres"], dtype=np.float64)
            positions = camera_to_world_points(z, x, y, intrinsics, pose)
            sampled_observations += z.size

            for method in METHODS:
                support_conf = shuffled_values if method == "shuffled-calibrated-covariance" else intact_values
                sigma_z = method_sigma(
                    method,
                    z,
                    support_conf,
                    floor=floor,
                    quadratic=quadratic,
                    penalty=penalty,
                )
                log_scales, quaternions = covariance_batch(
                    x, y, z, intrinsics, pose, sigma_z, pixel_sigma
                )
                method_chunks[method].append((positions.copy(), log_scales, quaternions))

        method_records: dict[str, dict] = {}
        primitive_counts: set[int] = set()
        for method in METHODS:
            if not method_chunks[method]:
                raise ValueError(f"U5a {scene} {method} produced no Gaussian primitives")
            positions = np.concatenate([chunk[0] for chunk in method_chunks[method]], axis=0)
            log_scales = np.concatenate([chunk[1] for chunk in method_chunks[method]], axis=0)
            quaternions = np.concatenate([chunk[2] for chunk in method_chunks[method]], axis=0)
            primitive_counts.add(int(positions.shape[0]))
            method_dir = scene_output / method
            ply_path = method_dir / "gaussians.ply"
            write_gaussian_ply(ply_path, positions, log_scales, quaternions, opacity_logit)
            method_records[method] = {
                "gaussianPath": str(ply_path.resolve()),
                "gaussianSha256": sha256_file(ply_path),
                "primitiveCount": int(positions.shape[0]),
            }
        if len(primitive_counts) != 1 or next(iter(primitive_counts)) != sampled_observations:
            raise ValueError(f"U5a methods do not preserve the same observation count for {scene}")

        archive_path = Path(acquired["ca1mArchive"])
        if not archive_path.is_file() or sha256_file(archive_path) != acquired["ca1mArchiveSha256"]:
            raise ValueError(f"U5a acquired CA-1M archive hash mismatch for {scene}")
        targets: list[dict] = []
        target_dir = scene_output / "targets"
        target_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r") as archive:
            complete = discover_frames(archive, video_id)
            eligible = [frame for frame in complete if frame.timestamp not in source_timestamps]
            indices = target_indices(len(eligible), int(protocol["targetViewSelection"]["count"]))
            selected = [eligible[index] for index in indices]
            if len({frame.timestamp for frame in selected}) != 8:
                raise ValueError(f"U5a target selection is not unique for {scene}")
            for index, frame in enumerate(selected):
                gt_depth = decode_depth(read_member(archive, frame.members["gt/depth"])).astype("<f4")
                intrinsics = parse_intrinsics(read_member(archive, frame.members["gt/depth/k"]))
                pose = parse_pose(read_member(archive, frame.members["gt/rt"]))
                depth_path = target_dir / f"{index:02d}-faro.f32"
                gt_depth.tofile(depth_path)
                world_to_camera, camera_position = world_to_camera_payload(pose)
                targets.append(
                    {
                        "targetIndex": index,
                        "eligibleIndex": indices[index],
                        "timestampNanoseconds": int(frame.timestamp),
                        "width": int(gt_depth.shape[1]),
                        "height": int(gt_depth.shape[0]),
                        "intrinsics": [float(value) for value in intrinsics],
                        "cameraWorldPosition": camera_position,
                        "worldToCameraRowMajor": world_to_camera,
                        "faroDepthPath": str(depth_path.resolve()),
                        "faroDepthSha256": sha256_file(depth_path),
                    }
                )

        target_manifest = scene_output / "targets.json"
        target_payload = {
            "schemaVersion": 1,
            "study": STUDY_ID,
            "scene": scene,
            "videoId": video_id,
            "sourceTimestampsNanoseconds": sorted(int(value) for value in source_timestamps),
            "eligibleCompleteFrameCountAfterSourceExclusion": len(eligible),
            "selectionRule": protocol["targetViewSelection"]["indexRule"],
            "targets": targets,
        }
        target_manifest.write_text(json.dumps(target_payload, indent=2, sort_keys=True) + "\n")
        scene_records.append(
            {
                "scene": scene,
                "videoId": video_id,
                "sourceRelativeManifestSha256": prep_scene["relativeManifestSha256"],
                "sampledObservationCount": sampled_observations,
                "methods": method_records,
                "targetManifestSha256": sha256_file(target_manifest),
                "targetTimestampsNanoseconds": [target["timestampNanoseconds"] for target in targets],
                "noRenderedDepthProduced": True,
                "noU5aMetricsProduced": True,
            }
        )
        print(
            json.dumps(
                {
                    "u5aPreparation": {
                        "scene": scene,
                        "primitives": sampled_observations,
                        "targets": [target["timestampNanoseconds"] for target in targets],
                    }
                },
                sort_keys=True,
            ),
            flush=True,
        )

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U5a-preparation",
        "status": "prepared-no-u5a-render-or-metric-outcomes",
        "protocolSha256": sha256_file(args.protocol),
        "clarificationSha256": sha256_file(args.clarification),
        "acquisitionLedgerSha256": sha256_file(args.acquisition_ledger),
        "u3bPreparationLedgerSha256": sha256_file(prep_path),
        "noRenderedDepthProduced": True,
        "noU5aMetricsProduced": True,
        "scenes": scene_records,
    }
    final_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
