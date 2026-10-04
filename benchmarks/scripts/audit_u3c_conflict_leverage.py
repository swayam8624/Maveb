#!/usr/bin/env python3
"""Audit whether calibrated confidence has mechanical leverage inside frozen U3b TSDF fusion."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

import numpy as np
from scipy.stats import rankdata, spearmanr


STUDY_ID = "metric-uncertainty-u3c-conflict-leverage-audit-v1"
U3B_RESULT_SHA256 = "1b5e1635eb7491658a63058ca9cdeb0e1b4260bec049601c7c168fdca9ac165f"
PREP_SHA256 = "acf41a5f094e30de1a8aa487db40b8a3e292ab18bc535aba8d2c6187800a88d3"
MODEL_SHA256 = "744cdfce9763f5d2ecd9c9a4e53385f66d8bba7cbc047e11729189053a85e17a"
ADAPTER_SHA256 = "9dfb0ec909e7f7671f196d62e762ce72207b658c073ec867130c806643a8c5b4"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quaternion_to_rotation_matrix(q: list[float]) -> np.ndarray:
    w, x, y, z = (float(value) for value in q)
    return np.asarray(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def llround_array(values: np.ndarray) -> np.ndarray:
    return np.where(values >= 0.0, np.floor(values + 0.5), np.ceil(values - 0.5)).astype(np.int64)


def nearest_tie_lower(values: np.ndarray, fraction: float) -> float | None:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return None
    ordered = np.sort(finite)
    target = fraction * (ordered.size - 1)
    lower = int(math.floor(target))
    upper = int(math.ceil(target))
    index = lower if target - lower <= upper - target else upper
    return float(ordered[index])


def finite_median(values: np.ndarray) -> float | None:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    return None if finite.size == 0 else float(np.median(finite))


def fraction_true(mask: np.ndarray, denominator_mask: np.ndarray | None = None) -> float | None:
    if denominator_mask is None:
        denominator_mask = np.ones(mask.shape, dtype=bool)
    denominator = int(np.count_nonzero(denominator_mask))
    if denominator == 0:
        return None
    return float(np.count_nonzero(mask & denominator_mask) / denominator)


def rowwise_spearman(sigmas: np.ndarray, distances: np.ndarray) -> np.ndarray:
    median_distance = np.nanmedian(distances, axis=1)
    residual = np.abs(distances - median_distance[:, None])
    sigma_ranks = rankdata(sigmas, axis=1, method="average", nan_policy="omit")
    residual_ranks = rankdata(residual, axis=1, method="average", nan_policy="omit")
    valid = np.isfinite(sigma_ranks) & np.isfinite(residual_ranks)
    counts = valid.sum(axis=1)
    sigma_mean = np.divide(
        np.nansum(np.where(valid, sigma_ranks, np.nan), axis=1),
        counts,
        out=np.full(counts.shape, np.nan, dtype=np.float64),
        where=counts > 0,
    )
    residual_mean = np.divide(
        np.nansum(np.where(valid, residual_ranks, np.nan), axis=1),
        counts,
        out=np.full(counts.shape, np.nan, dtype=np.float64),
        where=counts > 0,
    )
    sigma_centered = np.where(valid, sigma_ranks - sigma_mean[:, None], 0.0)
    residual_centered = np.where(valid, residual_ranks - residual_mean[:, None], 0.0)
    numerator = np.sum(sigma_centered * residual_centered, axis=1)
    denominator = np.sqrt(
        np.sum(sigma_centered * sigma_centered, axis=1)
        * np.sum(residual_centered * residual_centered, axis=1)
    )
    correlation = np.divide(
        numerator,
        denominator,
        out=np.full(numerator.shape, np.nan, dtype=np.float64),
        where=(counts >= 3) & (denominator > 0.0),
    )
    return correlation


def scene_observations(manifest_path: Path, protocol: dict) -> tuple[dict, dict[str, np.ndarray]]:
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("researchStudy") != "metric-uncertainty-u3b-relative-confidence-transfer-v1":
        raise ValueError(f"unexpected research study in {manifest_path}")
    if manifest.get("researchMethodFamily") != "relative-confidence-precision":
        raise ValueError(f"U3c requires the relative U3b manifest: {manifest_path}")
    if manifest.get("u3bEngineAdapterSha256") != ADAPTER_SHA256:
        raise ValueError(f"U3b engine-adapter SHA mismatch in {manifest_path}")
    frames = manifest["frames"]
    if len(frames) != int(protocol["inputs"]["viewsPerScene"]):
        raise ValueError(f"U3c requires exactly eight frozen views in {manifest_path}")

    volume = manifest["volume"]
    origin = np.asarray(volume["originMetres"], dtype=np.float64)
    dimensions = tuple(int(value) for value in volume["dimensions"])
    voxel_size = float(volume["voxelSizeMetres"])
    truncation = float(volume["truncationDistanceMetres"])
    minimum_depth = float(volume["minimumDepthMetres"])
    maximum_depth = float(volume["maximumDepthMetres"])

    dx, dy, dz = dimensions
    zz, yy, xx = np.indices((dz, dy, dx), dtype=np.float64)
    world = np.column_stack(
        (
            origin[0] + xx.reshape(-1) * voxel_size,
            origin[1] + yy.reshape(-1) * voxel_size,
            origin[2] + zz.reshape(-1) * voxel_size,
        )
    )
    voxel_count = world.shape[0]
    view_count = len(frames)
    distances = np.full((voxel_count, view_count), np.nan, dtype=np.float32)
    confidences = np.full((voxel_count, view_count), np.nan, dtype=np.float32)
    sigmas = np.full((voxel_count, view_count), np.nan, dtype=np.float32)

    frozen = protocol["frozenUncertainty"]
    floor = float(frozen["depthNoiseFloorMetres"])
    quadratic = float(frozen["depthNoiseQuadraticMetresPerMetreSquared"])
    penalty = float(frozen["sensorConfidencePenalty"])
    root = manifest_path.parent

    for view_index, frame in enumerate(frames):
        width = int(frame["width"])
        height = int(frame["height"])
        fx, fy, cx, cy = (float(value) for value in frame["intrinsics"])
        rotation = quaternion_to_rotation_matrix(frame["poseQuaternionWxyz"])
        translation = np.asarray(frame["poseTranslationMetres"], dtype=np.float64)
        camera = (world - translation) @ rotation
        camera_z = camera[:, 2]
        geometric = camera_z > minimum_depth
        projected_x = fx * camera[:, 0] / camera_z + cx
        projected_y = fy * camera[:, 1] / camera_z + cy
        pixel_x = llround_array(projected_x)
        pixel_y = llround_array(projected_y)
        geometric &= (pixel_x >= 0) & (pixel_y >= 0) & (pixel_x < width) & (pixel_y < height)
        candidate_indices = np.flatnonzero(geometric)
        if candidate_indices.size == 0:
            continue

        depth = np.fromfile(root / frame["depthPath"], dtype="<f4")
        confidence_u8 = np.fromfile(root / frame["confidencePath"], dtype=np.uint8)
        expected_pixels = width * height
        if depth.size != expected_pixels or confidence_u8.size != expected_pixels:
            raise ValueError(f"prepared frame byte size mismatch in {manifest_path}: view {view_index}")
        depth = depth.reshape(height, width)
        confidence_u8 = confidence_u8.reshape(height, width)

        px = pixel_x[candidate_indices]
        py = pixel_y[candidate_indices]
        observed_depth = depth[py, px].astype(np.float64)
        confidence = confidence_u8[py, px].astype(np.float64) / 255.0
        valid = (
            np.isfinite(observed_depth)
            & (observed_depth >= minimum_depth)
            & (observed_depth <= maximum_depth)
        )
        signed_distance = observed_depth - camera_z[candidate_indices]
        valid &= signed_distance >= -truncation
        valid_indices = candidate_indices[valid]
        if valid_indices.size == 0:
            continue
        observed_depth = observed_depth[valid]
        confidence = confidence[valid]
        normalized = np.clip(signed_distance[valid] / truncation, -1.0, 1.0)
        sigma = (floor + quadratic * observed_depth * observed_depth) * (
            1.0 + penalty * (1.0 - confidence)
        )
        distances[valid_indices, view_index] = normalized.astype(np.float32)
        confidences[valid_indices, view_index] = confidence.astype(np.float32)
        sigmas[valid_indices, view_index] = sigma.astype(np.float32)

    return manifest, {
        "distances": distances,
        "confidences": confidences,
        "sigmas": sigmas,
        "voxelLinearIndex": np.arange(voxel_count, dtype=np.int64),
    }


def summarize_scene(manifest: dict, observations: dict[str, np.ndarray], protocol: dict) -> tuple[dict, dict[str, np.ndarray]]:
    distances = observations["distances"].astype(np.float64)
    confidences = observations["confidences"].astype(np.float64)
    sigmas = observations["sigmas"].astype(np.float64)
    valid = np.isfinite(distances)
    counts = valid.sum(axis=1)
    minimum_abs = np.min(np.where(valid, np.abs(distances), np.inf), axis=1)
    surface_active = (counts >= int(protocol["observationConstruction"]["minimumContributingViews"])) & (
        minimum_abs <= 0.25
    )
    active_indices = np.flatnonzero(surface_active)
    if active_indices.size == 0:
        raise ValueError(f"{manifest['scene']} produced no U3c surface-active voxels")

    d = distances[active_indices]
    c = confidences[active_indices]
    s = sigmas[active_indices]
    active_valid = np.isfinite(d)
    view_count = active_valid.sum(axis=1).astype(np.int16)
    conflict_range = np.nanmax(d, axis=1) - np.nanmin(d, axis=1)
    conflict_std = np.nanstd(d, axis=1, ddof=0)
    confidence_spread = np.nanmax(c, axis=1) - np.nanmin(c, axis=1)

    naive_denominator = np.nansum(c, axis=1)
    naive_numerator = np.nansum(c * d, axis=1)
    naive_fused = np.divide(
        naive_numerator,
        naive_denominator,
        out=np.full(naive_denominator.shape, np.nan, dtype=np.float64),
        where=naive_denominator > 0.0,
    )
    penalty = float(protocol["frozenUncertainty"]["sensorConfidencePenalty"])
    relative_weight = np.where(
        active_valid,
        1.0 / (1.0 + penalty * (1.0 - c)) ** 2,
        np.nan,
    )
    relative_denominator = np.nansum(relative_weight, axis=1)
    relative_fused = np.nansum(relative_weight * d, axis=1) / relative_denominator
    truncation = float(manifest["volume"]["truncationDistanceMetres"])
    voxel_size = float(manifest["volume"]["voxelSizeMetres"])
    leverage_metres = np.abs(relative_fused - naive_fused) * truncation
    leverage_voxels = leverage_metres / voxel_size
    uncertainty_residual_spearman = rowwise_spearman(s, d)

    high_conflict = conflict_range >= 0.25
    mixed_confidence = confidence_spread >= 0.5
    categories = {
        "consensus-homogeneous-confidence": (~high_conflict) & (~mixed_confidence),
        "consensus-mixed-confidence": (~high_conflict) & mixed_confidence,
        "conflict-homogeneous-confidence": high_conflict & (~mixed_confidence),
        "conflict-mixed-confidence": high_conflict & mixed_confidence,
    }
    category_counts = {name: int(np.count_nonzero(mask)) for name, mask in categories.items()}
    category_fractions = {
        name: float(count / active_indices.size) for name, count in category_counts.items()
    }
    spearman_defined = np.isfinite(uncertainty_residual_spearman)
    leverage_defined = np.isfinite(leverage_metres)
    quarter_voxel = leverage_voxels >= float(protocol["sceneSummaries"]["quarterVoxelThreshold"])

    summary = {
        "scene": manifest["scene"],
        "videoId": str(manifest["videoId"]),
        "volumeDimensions": [int(value) for value in manifest["volume"]["dimensions"]],
        "voxelSizeMetres": voxel_size,
        "truncationDistanceMetres": truncation,
        "totalVolumeVoxelCount": int(distances.shape[0]),
        "surfaceActiveVoxelCount": int(active_indices.size),
        "categoryCounts": category_counts,
        "categoryFractions": category_fractions,
        "fractionConflictMixedConfidence": category_fractions["conflict-mixed-confidence"],
        "medianConflictRangeNormalized": finite_median(conflict_range),
        "p95ConflictRangeNormalized": nearest_tie_lower(conflict_range, 0.95),
        "medianConflictStdNormalized": finite_median(conflict_std),
        "p95ConflictStdNormalized": nearest_tie_lower(conflict_std, 0.95),
        "fusionLeverageDefinedVoxelCount": int(np.count_nonzero(leverage_defined)),
        "medianFusionLeverageMetres": finite_median(leverage_metres),
        "p95FusionLeverageMetres": nearest_tie_lower(leverage_metres, 0.95),
        "medianFusionLeverageVoxelUnits": finite_median(leverage_voxels),
        "p95FusionLeverageVoxelUnits": nearest_tie_lower(leverage_voxels, 0.95),
        "fractionFusionLeverageAtLeastQuarterVoxel": fraction_true(quarter_voxel, leverage_defined),
        "uncertaintyResidualSpearmanDefinedVoxelCount": int(np.count_nonzero(spearman_defined)),
        "medianUncertaintyResidualSpearman": finite_median(uncertainty_residual_spearman),
        "fractionPositiveUncertaintyResidualSpearman": fraction_true(
            uncertainty_residual_spearman > 0.0, spearman_defined
        ),
        "medianContributingViews": finite_median(view_count.astype(np.float64)),
        "p95ContributingViews": nearest_tie_lower(view_count.astype(np.float64), 0.95),
    }
    arrays = {
        "voxelLinearIndex": active_indices.astype(np.int64),
        "viewCount": view_count,
        "conflictRangeNormalized": conflict_range.astype(np.float32),
        "conflictStdNormalized": conflict_std.astype(np.float32),
        "confidenceSpread": confidence_spread.astype(np.float32),
        "naiveFusedNormalized": naive_fused.astype(np.float32),
        "relativeFusedNormalized": relative_fused.astype(np.float32),
        "fusionLeverageMetres": leverage_metres.astype(np.float32),
        "fusionLeverageVoxelUnits": leverage_voxels.astype(np.float32),
        "uncertaintyResidualSpearman": uncertainty_residual_spearman.astype(np.float32),
        "categoryCode": np.select(
            [
                categories["consensus-homogeneous-confidence"],
                categories["consensus-mixed-confidence"],
                categories["conflict-homogeneous-confidence"],
                categories["conflict-mixed-confidence"],
            ],
            [0, 1, 2, 3],
            default=-1,
        ).astype(np.int8),
    }
    return summary, arrays


def safe_scene_spearman(scene_summaries: list[dict], improvements: dict[str, float], key: str) -> dict:
    pairs = [
        (float(improvements[scene["scene"]]), scene.get(key))
        for scene in scene_summaries
        if scene.get(key) is not None and math.isfinite(float(scene[key]))
    ]
    if len(pairs) < 3:
        return {"definedSceneCount": len(pairs), "rho": None, "pValue": None}
    x = [pair[0] for pair in pairs]
    y = [float(pair[1]) for pair in pairs]
    result = spearmanr(x, y)
    rho = float(result.statistic) if math.isfinite(float(result.statistic)) else None
    p_value = float(result.pvalue) if math.isfinite(float(result.pvalue)) else None
    return {"definedSceneCount": len(pairs), "rho": rho, "pValue": p_value}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--u3b-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--u3b-result", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    for path in (args.protocol, args.u3b_result):
        if not path.is_file():
            raise FileNotFoundError(path)
    if sha256_file(args.u3b_result) != U3B_RESULT_SHA256:
        raise ValueError("U3c requires the exact frozen U3b primary result")
    protocol = json.loads(args.protocol.read_text())
    if protocol.get("id") != STUDY_ID or not protocol.get("frozen") or protocol.get("status") != "frozen-before-u3c-mechanism-metrics":
        raise ValueError("U3c protocol is not the frozen pre-metric protocol")
    result = json.loads(args.u3b_result.read_text())
    if result.get("status") != "completed-confirmatory-gate-not-passed":
        raise ValueError("U3c source outcome is not the frozen negative U3b result")
    prepare_path = args.u3b_root / "primary-prepare-ledger.json"
    if not prepare_path.is_file() or sha256_file(prepare_path) != PREP_SHA256:
        raise ValueError("U3c requires the exact frozen U3b preparation ledger")
    prep = json.loads(prepare_path.read_text())
    if prep.get("modelSha256") != MODEL_SHA256 or prep.get("engineAdapterSha256") != ADAPTER_SHA256:
        raise ValueError("U3c preparation provenance mismatch")
    prep_by_scene = {item["scene"]: item for item in prep["scenes"]}

    summary_path = args.output_root / "summary.json"
    if summary_path.exists():
        raise ValueError("U3c summary.json already exists; mechanism audit will not be overwritten")
    args.output_root.mkdir(parents=True, exist_ok=True)

    improvement_values = protocol["crossSceneAnalysis"]["u3bCandidateVsNaiveImprovementValues"]
    scene_summaries: list[dict] = []
    for scene in protocol["scenes"]:
        scene_dir = args.u3b_root / "scenes" / scene
        manifest_path = scene_dir / protocol["inputs"]["preparedManifestFilename"]
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        prep_scene = prep_by_scene.get(scene)
        if prep_scene is None or sha256_file(manifest_path) != prep_scene["relativeManifestSha256"]:
            raise ValueError(f"prepared relative manifest SHA mismatch for {scene}")
        methods = result["scenes"][scene]["methods"]
        naive = float(methods["naive-confidence"]["metrics"]["chamferMeanMetres"])
        candidate = float(methods["relative-confidence-precision"]["metrics"]["chamferMeanMetres"])
        actual_improvement = (naive - candidate) / naive
        if abs(actual_improvement - float(improvement_values[scene])) > 1.0e-15:
            raise ValueError(f"U3c source improvement transcription mismatch for {scene}")

        print(json.dumps({"u3cProgress": {"scene": scene, "stage": "project-voxel-observations"}}), flush=True)
        manifest, observations = scene_observations(manifest_path, protocol)
        scene_summary, arrays = summarize_scene(manifest, observations, protocol)
        scene_summary["u3bCandidateVsNaiveRelativeChamferImprovement"] = actual_improvement
        scene_summary["relativeManifestSha256"] = sha256_file(manifest_path)
        output_scene = args.output_root / "scenes" / scene
        output_scene.mkdir(parents=True, exist_ok=True)
        npz_path = output_scene / "voxel-mechanism.npz"
        np.savez_compressed(npz_path, **arrays)
        scene_summary["voxelMetricsSha256"] = sha256_file(npz_path)
        scene_summary_path = output_scene / "summary.json"
        scene_summary_path.write_text(json.dumps(scene_summary, indent=2, sort_keys=True) + "\n")
        scene_summary["sceneSummarySha256"] = sha256_file(scene_summary_path)
        scene_summaries.append(scene_summary)
        print(
            json.dumps(
                {
                    "u3cSceneSummary": {
                        "scene": scene,
                        "surfaceActiveVoxelCount": scene_summary["surfaceActiveVoxelCount"],
                        "fractionConflictMixedConfidence": scene_summary["fractionConflictMixedConfidence"],
                        "p95FusionLeverageVoxelUnits": scene_summary["p95FusionLeverageVoxelUnits"],
                        "medianUncertaintyResidualSpearman": scene_summary["medianUncertaintyResidualSpearman"],
                    }
                }
            ),
            flush=True,
        )

    cross_scene = {
        "descriptiveOnly": True,
        "improvementVsFractionConflictMixedConfidence": safe_scene_spearman(
            scene_summaries, improvement_values, "fractionConflictMixedConfidence"
        ),
        "improvementVsP95FusionLeverageMetres": safe_scene_spearman(
            scene_summaries, improvement_values, "p95FusionLeverageMetres"
        ),
        "improvementVsMedianUncertaintyResidualSpearman": safe_scene_spearman(
            scene_summaries, improvement_values, "medianUncertaintyResidualSpearman"
        ),
    }
    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "status": "completed-post-hoc-mechanism-audit",
        "claimType": protocol["claimType"],
        "protocolSha256": sha256_file(args.protocol),
        "u3bPrimaryResultSha256": sha256_file(args.u3b_result),
        "u3bPreparationLedgerSha256": sha256_file(prepare_path),
        "modelSha256": MODEL_SHA256,
        "engineAdapterSha256": ADAPTER_SHA256,
        "scenes": scene_summaries,
        "crossScene": cross_scene,
        "claimBoundary": "Descriptive mechanism analysis on already-exposed U3b scenes. This artifact cannot rescue or overturn the negative U3/U3b efficacy outcomes.",
    }
    temporary = summary_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(summary_path)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
