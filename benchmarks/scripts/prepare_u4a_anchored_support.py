#!/usr/bin/env python3
"""Prepare U4a uncertainty-anchored support masks without reconstructing geometry."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from audit_u3c_conflict_leverage import (
    llround_array,
    quaternion_to_rotation_matrix,
    scene_observations,
    sha256_file,
)


STUDY_ID = "metric-uncertainty-u4a-anchored-support-v1"
U3B_RESULT_SHA256 = "1b5e1635eb7491658a63058ca9cdeb0e1b4260bec049601c7c168fdca9ac165f"
U3C_SUMMARY_SHA256 = "652b2df1ae3811f23252af4469089ab4a2bd56ca12cdbea8e864b3d149505110"
PREP_SHA256 = "acf41a5f094e30de1a8aa487db40b8a3e292ab18bc535aba8d2c6187800a88d3"
MODEL_SHA256 = "744cdfce9763f5d2ecd9c9a4e53385f66d8bba7cbc047e11729189053a85e17a"
ADAPTER_SHA256 = "9dfb0ec909e7f7671f196d62e762ce72207b658c073ec867130c806643a8c5b4"
EXPECTED_SCENES = [
    "ca1m-48458481",
    "ca1m-48018737",
    "ca1m-45261587",
    "ca1m-42897538",
    "ca1m-48018375",
]
METHODS = [
    "depth-only-anchored-support",
    "calibrated-anchored-support",
    "shuffled-calibrated-anchored-support",
]


def protocol_sha(path: Path) -> str:
    return sha256_file(path)


def u3c_protocol_shim(protocol: dict) -> dict:
    frozen = protocol["frozenPredictiveModel"]
    return {
        "inputs": {"viewsPerScene": int(protocol["dataReuse"]["viewsPerScene"])},
        "frozenUncertainty": {
            "depthNoiseFloorMetres": float(frozen["depthNoiseFloorMetres"]),
            "depthNoiseQuadraticMetresPerMetreSquared": float(
                frozen["depthNoiseQuadraticMetresPerMetreSquared"]
            ),
            "sensorConfidencePenalty": float(frozen["sensorConfidencePenalty"]),
        },
    }


def anchor_support_field(
    distances: np.ndarray,
    support_sigma: np.ndarray,
    voxel_size: float,
    anchor_fraction: float = 0.5,
    surface_band: float = 0.25,
) -> dict[str, np.ndarray]:
    distances = np.asarray(distances, dtype=np.float64)
    support_sigma = np.asarray(support_sigma, dtype=np.float64)
    if distances.shape != support_sigma.shape or distances.ndim != 2:
        raise ValueError("anchor-support distances/sigma must be matching voxel-by-view arrays")
    threshold = anchor_fraction * float(voxel_size)
    valid = np.isfinite(distances) & np.isfinite(support_sigma)
    anchor = valid & (support_sigma <= threshold)
    count = anchor.sum(axis=1).astype(np.int16)
    numerator = np.sum(np.where(anchor, distances, 0.0), axis=1)
    fused = np.divide(
        numerator,
        count,
        out=np.full(count.shape, np.nan, dtype=np.float64),
        where=count > 0,
    )
    supported = (count > 0) & (np.abs(fused) <= surface_band)
    return {
        "anchorMask": anchor,
        "anchorCount": count,
        "anchorDistance": fused,
        "supported": supported,
    }


def support_sigma_arrays(observations: dict[str, np.ndarray], penalty: float) -> dict[str, np.ndarray]:
    intact_sigma = observations["sigmas"].astype(np.float64)
    intact_confidence = observations["confidences"].astype(np.float64)
    factor = 1.0 + float(penalty) * (1.0 - intact_confidence)
    base_sigma = np.divide(
        intact_sigma,
        factor,
        out=np.full(intact_sigma.shape, np.nan, dtype=np.float64),
        where=np.isfinite(intact_sigma) & np.isfinite(factor) & (factor > 0.0),
    )
    return {
        "depth-only-anchored-support": base_sigma,
        "calibrated-anchored-support": intact_sigma,
    }


def shuffled_observations(manifest_path: Path, protocol: dict, scratch_manifest: Path) -> dict[str, np.ndarray]:
    payload = json.loads(manifest_path.read_text())
    for frame in payload["frames"]:
        frame["confidencePath"] = frame["shuffledConfidencePath"]
    scratch_manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    try:
        _, observations = scene_observations(scratch_manifest, u3c_protocol_shim(protocol))
    finally:
        scratch_manifest.unlink(missing_ok=True)
    return observations


def pixel_surface_grid_indices(
    depth: np.ndarray,
    frame: dict,
    volume: dict,
) -> tuple[np.ndarray, np.ndarray]:
    depth = np.asarray(depth, dtype=np.float64)
    height, width = depth.shape
    fx, fy, cx, cy = (float(value) for value in frame["intrinsics"])
    rotation = quaternion_to_rotation_matrix(frame["poseQuaternionWxyz"])
    translation = np.asarray(frame["poseTranslationMetres"], dtype=np.float64)
    yy, xx = np.indices((height, width), dtype=np.float64)
    camera = np.stack(
        (
            (xx - cx) * depth / fx,
            (yy - cy) * depth / fy,
            depth,
        ),
        axis=-1,
    )
    world = camera @ rotation.T + translation
    origin = np.asarray(volume["originMetres"], dtype=np.float64)
    voxel_size = float(volume["voxelSizeMetres"])
    grid = llround_array((world - origin) / voxel_size)
    dimensions = np.asarray(volume["dimensions"], dtype=np.int64)
    in_bounds = np.all((grid >= 0) & (grid < dimensions), axis=-1)
    linear = (
        (grid[..., 2] * dimensions[1] + grid[..., 1]) * dimensions[0] + grid[..., 0]
    ).astype(np.int64)
    return linear, in_bounds


def mask_frame_confidence(
    depth: np.ndarray,
    original_confidence_u8: np.ndarray,
    support_confidence_u8: np.ndarray,
    frame: dict,
    volume: dict,
    supported_grid: np.ndarray,
    floor: float,
    quadratic: float,
    penalty: float,
    method: str,
) -> tuple[np.ndarray, dict]:
    depth = np.asarray(depth, dtype=np.float64)
    original = np.asarray(original_confidence_u8, dtype=np.uint8)
    support_conf = np.asarray(support_confidence_u8, dtype=np.uint8)
    if depth.shape != original.shape or depth.shape != support_conf.shape:
        raise ValueError("U4a depth/confidence frame shapes differ")
    minimum_depth = float(volume["minimumDepthMetres"])
    maximum_depth = float(volume["maximumDepthMetres"])
    valid_depth = np.isfinite(depth) & (depth >= minimum_depth) & (depth <= maximum_depth)
    base_sigma = float(floor) + float(quadratic) * depth * depth
    if method == "depth-only-anchored-support":
        sigma = base_sigma
    else:
        confidence = support_conf.astype(np.float64) / 255.0
        sigma = base_sigma * (1.0 + float(penalty) * (1.0 - confidence))
    anchor = valid_depth & (sigma <= 0.5 * float(volume["voxelSizeMetres"]))
    linear, in_bounds = pixel_surface_grid_indices(depth, frame, volume)
    lookup = np.zeros(depth.shape, dtype=bool)
    safe = valid_depth & in_bounds
    lookup[safe] = supported_grid[linear[safe]]
    admit = anchor | (valid_depth & lookup)
    masked = original.copy()
    masked[~admit] = 0
    non_anchor = valid_depth & (~anchor)
    supported_non_anchor = non_anchor & lookup
    diagnostics = {
        "validDepthObservationCount": int(np.count_nonzero(valid_depth)),
        "anchorObservationCount": int(np.count_nonzero(anchor)),
        "admittedNonAnchorObservationCount": int(np.count_nonzero(supported_non_anchor)),
        "suppressedNonAnchorObservationCount": int(np.count_nonzero(non_anchor & (~lookup))),
        "finalAdmittedObservationCount": int(np.count_nonzero(admit)),
        "supportLookupInBoundsCount": int(np.count_nonzero(safe)),
        "supportLookupPositiveCount": int(np.count_nonzero(valid_depth & lookup)),
    }
    return masked, diagnostics


def absolute_manifest(payload: dict, source_root: Path, confidence_paths: list[Path], method: str) -> dict:
    result = copy.deepcopy(payload)
    result["researchStudy"] = STUDY_ID
    result["researchMethodFamily"] = method
    for index, frame in enumerate(result["frames"]):
        frame["depthPath"] = str((source_root / frame["depthPath"]).resolve())
        frame["confidencePath"] = str(confidence_paths[index].resolve())
        frame["shuffledConfidencePath"] = str(confidence_paths[index].resolve())
    reference = result.get("reference")
    if isinstance(reference, dict) and "path" in reference:
        reference["path"] = str((source_root / reference["path"]).resolve())
    return result


def aggregate_diagnostics(frames: list[dict], anchor_grid_count: int, total_grid_count: int) -> dict:
    summed = {
        key: sum(int(frame[key]) for frame in frames)
        for key in (
            "validDepthObservationCount",
            "anchorObservationCount",
            "admittedNonAnchorObservationCount",
            "suppressedNonAnchorObservationCount",
            "finalAdmittedObservationCount",
            "supportLookupInBoundsCount",
            "supportLookupPositiveCount",
        )
    }
    valid = summed["validDepthObservationCount"]
    non_anchor = summed["admittedNonAnchorObservationCount"] + summed["suppressedNonAnchorObservationCount"]
    summed.update(
        {
            "anchorObservationFraction": None if valid == 0 else summed["anchorObservationCount"] / valid,
            "finalAdmittedObservationFraction": None if valid == 0 else summed["finalAdmittedObservationCount"] / valid,
            "supportedSurfaceLookupFraction": None if non_anchor == 0 else summed["admittedNonAnchorObservationCount"] / non_anchor,
            "anchorVoxelCount": int(anchor_grid_count),
            "totalVolumeVoxelCount": int(total_grid_count),
            "anchorVoxelFraction": None if total_grid_count == 0 else anchor_grid_count / total_grid_count,
        }
    )
    return summed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--u3b-root", type=Path, required=True)
    parser.add_argument("--u3c-summary", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    if not args.protocol.is_file() or not args.u3c_summary.is_file():
        raise FileNotFoundError("U4a protocol or U3c summary is missing")
    if sha256_file(args.u3c_summary) != U3C_SUMMARY_SHA256:
        raise ValueError("U4a requires the exact frozen U3c summary")
    protocol = json.loads(args.protocol.read_text())
    if protocol.get("id") != STUDY_ID or not protocol.get("frozen") or protocol.get("status") != "frozen-before-u4a-geometry-outcomes":
        raise ValueError("U4a protocol is not frozen before geometry outcomes")
    if protocol["parentEvidence"]["u3bPrimaryResultSha256"] != U3B_RESULT_SHA256:
        raise ValueError("U4a protocol references a different U3b result")
    if protocol["parentEvidence"]["u3cSummarySha256"] != U3C_SUMMARY_SHA256:
        raise ValueError("U4a protocol references a different U3c summary")

    prep_path = args.u3b_root / "primary-prepare-ledger.json"
    if not prep_path.is_file() or sha256_file(prep_path) != PREP_SHA256:
        raise ValueError("U4a requires the exact frozen U3b preparation ledger")
    prep = json.loads(prep_path.read_text())
    if prep.get("modelSha256") != MODEL_SHA256 or prep.get("engineAdapterSha256") != ADAPTER_SHA256:
        raise ValueError("U4a U3b preparation provenance mismatch")
    prep_by_scene = {item["scene"]: item for item in prep["scenes"]}

    output_summary = args.output_root / "preparation.json"
    if output_summary.exists():
        raise ValueError("U4a preparation.json already exists; preparation will not be overwritten")
    if (args.output_root / "geometry-result.json").exists():
        raise ValueError("U4a geometry outcome already exists")
    args.output_root.mkdir(parents=True, exist_ok=True)

    frozen = protocol["frozenPredictiveModel"]
    floor = float(frozen["depthNoiseFloorMetres"])
    quadratic = float(frozen["depthNoiseQuadraticMetresPerMetreSquared"])
    penalty = float(frozen["sensorConfidencePenalty"])
    scene_outputs: list[dict] = []

    for scene in protocol["scenes"]:
        if scene not in EXPECTED_SCENES:
            raise ValueError(f"unexpected U4a scene {scene}")
        source_scene = args.u3b_root / "scenes" / scene
        manifest_path = source_scene / protocol["dataReuse"]["preparedManifestFilename"]
        prep_scene = prep_by_scene.get(scene)
        if prep_scene is None or not manifest_path.is_file() or sha256_file(manifest_path) != prep_scene["relativeManifestSha256"]:
            raise ValueError(f"U4a relative manifest mismatch for {scene}")
        manifest, intact_obs = scene_observations(manifest_path, u3c_protocol_shim(protocol))
        support_sigmas = support_sigma_arrays(intact_obs, penalty)
        scratch = args.output_root / f".{scene}-shuffled-manifest.tmp.json"
        shuffled_obs = shuffled_observations(manifest_path, protocol, scratch)
        support_sigmas["shuffled-calibrated-anchored-support"] = shuffled_obs["sigmas"].astype(np.float64)

        scene_output = args.output_root / "scenes" / scene
        scene_output.mkdir(parents=True, exist_ok=True)
        source_root = manifest_path.parent
        method_outputs: dict[str, dict] = {}

        for method in METHODS:
            anchor = anchor_support_field(
                intact_obs["distances"],
                support_sigmas[method],
                float(manifest["volume"]["voxelSizeMetres"]),
            )
            method_dir = scene_output / method
            confidence_dir = method_dir / "confidence-masked"
            confidence_dir.mkdir(parents=True, exist_ok=True)
            frame_diagnostics: list[dict] = []
            confidence_paths: list[Path] = []

            for frame_index, frame in enumerate(manifest["frames"]):
                width = int(frame["width"])
                height = int(frame["height"])
                depth = np.fromfile(source_root / frame["depthPath"], dtype="<f4").reshape(height, width)
                original = np.fromfile(source_root / frame["confidencePath"], dtype=np.uint8).reshape(height, width)
                if method == "shuffled-calibrated-anchored-support":
                    support_conf = np.fromfile(source_root / frame["shuffledConfidencePath"], dtype=np.uint8).reshape(height, width)
                else:
                    support_conf = original
                masked, diagnostics = mask_frame_confidence(
                    depth,
                    original,
                    support_conf,
                    frame,
                    manifest["volume"],
                    anchor["supported"],
                    floor,
                    quadratic,
                    penalty,
                    method,
                )
                masked_path = confidence_dir / f"{frame_index:02d}.u8"
                masked.tofile(masked_path)
                confidence_paths.append(masked_path)
                diagnostics["frameIndex"] = frame_index
                diagnostics["timestampNanoseconds"] = int(frame["timestampNanoseconds"])
                diagnostics["maskedConfidenceSha256"] = sha256_file(masked_path)
                frame_diagnostics.append(diagnostics)

            prepared_manifest = absolute_manifest(manifest, source_root, confidence_paths, method)
            prepared_manifest_path = method_dir / "scene-manifest.json"
            prepared_manifest_path.write_text(json.dumps(prepared_manifest, indent=2, sort_keys=True) + "\n")
            anchor_npz = method_dir / "anchor-field.npz"
            np.savez_compressed(
                anchor_npz,
                anchorCount=anchor["anchorCount"],
                anchorDistance=anchor["anchorDistance"].astype(np.float32),
                supported=anchor["supported"].astype(np.uint8),
            )
            aggregate = aggregate_diagnostics(
                frame_diagnostics,
                int(np.count_nonzero(anchor["supported"])),
                int(anchor["supported"].size),
            )
            method_outputs[method] = {
                "manifestSha256": sha256_file(prepared_manifest_path),
                "anchorFieldSha256": sha256_file(anchor_npz),
                "diagnostics": aggregate,
                "frameDiagnostics": frame_diagnostics,
            }
            print(
                json.dumps(
                    {
                        "u4aPreparation": {
                            "scene": scene,
                            "method": method,
                            "anchorObservationFraction": aggregate["anchorObservationFraction"],
                            "finalAdmittedObservationFraction": aggregate["finalAdmittedObservationFraction"],
                            "anchorVoxelCount": aggregate["anchorVoxelCount"],
                        }
                    }
                ),
                flush=True,
            )

        scene_outputs.append(
            {
                "scene": scene,
                "sourceRelativeManifestSha256": sha256_file(manifest_path),
                "methods": method_outputs,
            }
        )

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "status": "prepared-no-u4a-geometry-outcomes",
        "protocolSha256": protocol_sha(args.protocol),
        "u3cSummarySha256": sha256_file(args.u3c_summary),
        "u3bPreparationLedgerSha256": sha256_file(prep_path),
        "scenes": scene_outputs,
        "noGeometryOutcomesProduced": True,
    }
    temporary = output_summary.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(output_summary)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
