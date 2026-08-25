#!/usr/bin/env python3
"""Prepare U6a Gaussian assets that change only opacity relative to U5a depth-only covariance."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


STUDY_ID = "metric-uncertainty-u6a-opacity-visibility-v1"
U5A_PREPARATION_SHA256 = "abb33671d7162b62689779fa87f4bb099cbe59bfdfeb7f3d8c910b4163d768b5"
U5A_RESULT_SHA256 = "5f0d70442ec1973eb28f1b61e7fe8cb174afdabfcae3aa64ab478c479ab32362"
EXPECTED_SCENES = [
    "ca1m-48458481",
    "ca1m-48018737",
    "ca1m-45261587",
    "ca1m-42897538",
    "ca1m-48018375",
]
METHODS = (
    "calibrated-relative-precision-opacity",
    "shuffled-relative-precision-opacity",
)
EXPECTED_PROPERTIES = [
    "x",
    "y",
    "z",
    "f_dc_0",
    "f_dc_1",
    "f_dc_2",
    "opacity",
    "scale_0",
    "scale_1",
    "scale_2",
    "rot_0",
    "rot_1",
    "rot_2",
    "rot_3",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def opacity_probability(confidence_u8: np.ndarray, *, base_opacity: float, k: float) -> np.ndarray:
    confidence = np.asarray(confidence_u8, dtype=np.float64) / 255.0
    return base_opacity / np.square(1.0 + k * (1.0 - confidence))


def opacity_logit(probability: np.ndarray) -> np.ndarray:
    values = np.asarray(probability, dtype=np.float64)
    if np.any(~np.isfinite(values)) or np.any(values <= 0.0) or np.any(values >= 1.0):
        raise ValueError("U6a opacity probability must be finite and strictly between zero and one")
    return np.log(values / (1.0 - values))


def parse_ascii_gaussian_ply(path: Path) -> tuple[list[str], list[list[str]], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "ply":
        raise ValueError(f"U6a baseline is not a PLY: {path}")
    try:
        header_end = lines.index("end_header")
    except ValueError as exc:
        raise ValueError(f"U6a baseline PLY has no end_header: {path}") from exc
    header = lines[: header_end + 1]
    if "format ascii 1.0" not in header:
        raise ValueError("U6a requires the frozen ASCII U5a Gaussian PLY")
    vertex_lines = [line for line in header if line.startswith("element vertex ")]
    if len(vertex_lines) != 1:
        raise ValueError("U6a baseline PLY must have exactly one vertex element")
    vertex_count = int(vertex_lines[0].split()[-1])
    properties = [line.split()[-1] for line in header if line.startswith("property float ")]
    if properties != EXPECTED_PROPERTIES:
        raise ValueError("U6a baseline PLY property order differs from the frozen U5a schema")
    rows = [line.split() for line in lines[header_end + 1 :]]
    if len(rows) != vertex_count:
        raise ValueError("U6a baseline PLY vertex count does not match row count")
    if any(len(row) != len(EXPECTED_PROPERTIES) for row in rows):
        raise ValueError("U6a baseline PLY row has the wrong property count")
    return header, rows, properties


def write_opacity_variant(
    path: Path,
    header: list[str],
    baseline_rows: list[list[str]],
    logits: np.ndarray,
) -> None:
    if logits.shape != (len(baseline_rows),):
        raise ValueError("U6a opacity vector length differs from baseline primitive count")
    opacity_index = EXPECTED_PROPERTIES.index("opacity")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for line in header:
            stream.write(line + "\n")
        for row, logit in zip(baseline_rows, logits, strict=True):
            variant = row.copy()
            variant[opacity_index] = f"{float(logit):.9g}"
            stream.write(" ".join(variant) + "\n")


def assert_only_opacity_changed(baseline: Path, variant: Path) -> None:
    base_header, base_rows, _ = parse_ascii_gaussian_ply(baseline)
    var_header, var_rows, _ = parse_ascii_gaussian_ply(variant)
    if base_header != var_header or len(base_rows) != len(var_rows):
        raise ValueError("U6a variant PLY structure differs from baseline")
    opacity_index = EXPECTED_PROPERTIES.index("opacity")
    for row_index, (base, var) in enumerate(zip(base_rows, var_rows, strict=True)):
        for column in range(len(EXPECTED_PROPERTIES)):
            if column == opacity_index:
                continue
            if base[column] != var[column]:
                raise ValueError(
                    f"U6a changed non-opacity property {EXPECTED_PROPERTIES[column]} at row {row_index}"
                )


def confidence_stream(source_scene: Path, source_manifest: dict, *, shuffled: bool, stride: int) -> np.ndarray:
    chunks: list[np.ndarray] = []
    for frame in source_manifest["frames"]:
        width = int(frame["width"])
        height = int(frame["height"])
        depth = np.fromfile(source_scene / frame["depthPath"], dtype="<f4").reshape(height, width)
        confidence_key = "shuffledConfidencePath" if shuffled else "confidencePath"
        confidence = np.fromfile(source_scene / frame[confidence_key], dtype=np.uint8).reshape(height, width)
        ys, xs = np.meshgrid(
            np.arange(0, height, stride, dtype=np.int64),
            np.arange(0, width, stride, dtype=np.int64),
            indexing="ij",
        )
        sampled_depth = depth[ys, xs].astype(np.float64)
        minimum_depth = float(source_manifest["volume"]["minimumDepthMetres"])
        maximum_depth = float(source_manifest["volume"]["maximumDepthMetres"])
        valid = (
            np.isfinite(sampled_depth)
            & (sampled_depth >= minimum_depth)
            & (sampled_depth <= maximum_depth)
        )
        if np.any(valid):
            chunks.append(confidence[ys, xs][valid].astype(np.uint8, copy=True))
    if not chunks:
        raise ValueError("U6a source manifests produced no sampled confidence observations")
    return np.concatenate(chunks)


def validate_protocol(protocol_path: Path) -> dict:
    protocol = json.loads(protocol_path.read_text())
    if (
        protocol.get("id") != STUDY_ID
        or protocol.get("status") != "frozen-before-u6a-assets-or-outcomes"
        or not protocol.get("frozen")
    ):
        raise ValueError("U6a protocol is not frozen before assets/outcomes")
    if protocol.get("scenes") != EXPECTED_SCENES:
        raise ValueError("U6a scene order differs from protocol")
    mapping = protocol["representation"]["opacityMapping"]
    if mapping.get("candidateOpacity") != "opacity=0.99*w_rel using intact confidence":
        raise ValueError("U6a candidate opacity mapping changed")
    if mapping.get("shuffledOpacity") != "opacity=0.99*w_rel using the exact frozen shuffled confidence":
        raise ValueError("U6a shuffled opacity mapping changed")
    return protocol


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--u5a-root", type=Path, required=True)
    parser.add_argument("--u3b-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    protocol = validate_protocol(args.protocol)
    u5a_preparation_path = args.u5a_root / "preparation.json"
    u5a_result_path = args.u5a_root / "result.json"
    if not u5a_preparation_path.is_file() or sha256_file(u5a_preparation_path) != U5A_PREPARATION_SHA256:
        raise ValueError("U6a requires the exact frozen U5a preparation")
    if not u5a_result_path.is_file() or sha256_file(u5a_result_path) != U5A_RESULT_SHA256:
        raise ValueError("U6a requires the exact frozen U5a result")

    final_path = args.output_root / "preparation.json"
    if final_path.exists():
        raise ValueError("U6a preparation.json already exists; preparation will not be overwritten")
    if (args.output_root / "result.json").exists():
        raise ValueError("U6a result already exists")
    if args.output_root.exists() and list(args.output_root.glob("scenes/*/renders/*")):
        raise ValueError("U6a render outcomes already exist")
    args.output_root.mkdir(parents=True, exist_ok=True)

    u5a_preparation = json.loads(u5a_preparation_path.read_text())
    prep_by_scene = {record["scene"]: record for record in u5a_preparation["scenes"]}
    stride = 4
    base_opacity = float(protocol["representation"]["baseOpacity"])
    k = float(protocol["representation"]["opacityMapping"]["k"])
    scene_records: list[dict] = []

    for scene in EXPECTED_SCENES:
        prep_scene = prep_by_scene.get(scene)
        if prep_scene is None:
            raise ValueError(f"U6a U5a preparation is missing {scene}")
        source_scene = args.u3b_root / "scenes" / scene
        source_manifest_path = source_scene / "scene-manifest-relative.json"
        if not source_manifest_path.is_file():
            raise FileNotFoundError(source_manifest_path)
        source_manifest = json.loads(source_manifest_path.read_text())
        if len(source_manifest["frames"]) != 8:
            raise ValueError(f"U6a requires eight source frames for {scene}")

        baseline_path = Path(prep_scene["methods"]["depth-only-covariance"]["gaussianPath"])
        baseline_sha = prep_scene["methods"]["depth-only-covariance"]["gaussianSha256"]
        if not baseline_path.is_file() or sha256_file(baseline_path) != baseline_sha:
            raise ValueError(f"U6a baseline Gaussian SHA mismatch for {scene}")
        header, rows, _ = parse_ascii_gaussian_ply(baseline_path)
        if len(rows) != int(protocol["assetIntegrity"]["perSceneExpectedPrimitiveCount"]):
            raise ValueError(f"U6a baseline primitive count differs from frozen count for {scene}")

        intact = confidence_stream(source_scene, source_manifest, shuffled=False, stride=stride)
        shuffled = confidence_stream(source_scene, source_manifest, shuffled=True, stride=stride)
        if intact.size != len(rows) or shuffled.size != len(rows):
            raise ValueError(f"U6a confidence ordering/count differs from U5a primitive rows for {scene}")

        scene_root = args.output_root / "scenes" / scene
        method_records: dict[str, dict] = {}
        for method, confidence in (
            ("calibrated-relative-precision-opacity", intact),
            ("shuffled-relative-precision-opacity", shuffled),
        ):
            probabilities = opacity_probability(confidence, base_opacity=base_opacity, k=k)
            logits = opacity_logit(probabilities)
            method_root = scene_root / method
            ply_path = method_root / "gaussians.ply"
            write_opacity_variant(ply_path, header, rows, logits)
            assert_only_opacity_changed(baseline_path, ply_path)
            unique, counts = np.unique(confidence, return_counts=True)
            method_records[method] = {
                "gaussianPath": str(ply_path.resolve()),
                "gaussianSha256": sha256_file(ply_path),
                "primitiveCount": len(rows),
                "baselineGaussianSha256": baseline_sha,
                "confidenceHistogram": {str(int(value)): int(count) for value, count in zip(unique, counts, strict=True)},
                "opacityProbabilityMin": float(np.min(probabilities)),
                "opacityProbabilityMedian": float(np.median(probabilities)),
                "opacityProbabilityMax": float(np.max(probabilities)),
                "onlyOpacityChangedFromBaseline": True,
            }

        target_manifest_path = args.u5a_root / "scenes" / scene / "targets.json"
        if not target_manifest_path.is_file() or sha256_file(target_manifest_path) != prep_scene["targetManifestSha256"]:
            raise ValueError(f"U6a target manifest differs from U5a for {scene}")
        scene_records.append(
            {
                "scene": scene,
                "baselineGaussianPath": str(baseline_path.resolve()),
                "baselineGaussianSha256": baseline_sha,
                "primitiveCount": len(rows),
                "targetManifestPath": str(target_manifest_path.resolve()),
                "targetManifestSha256": prep_scene["targetManifestSha256"],
                "methods": method_records,
                "noRenderedDepthProduced": True,
                "noU6aMetricsProduced": True,
            }
        )
        print(
            json.dumps(
                {
                    "u6aPreparation": {
                        "scene": scene,
                        "primitives": len(rows),
                        "candidateOpacityRange": [
                            method_records["calibrated-relative-precision-opacity"]["opacityProbabilityMin"],
                            method_records["calibrated-relative-precision-opacity"]["opacityProbabilityMax"],
                        ],
                    }
                },
                sort_keys=True,
            ),
            flush=True,
        )

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U6a-preparation",
        "status": "prepared-no-u6a-render-or-metric-outcomes",
        "protocolSha256": sha256_file(args.protocol),
        "u5aPreparationSha256": sha256_file(u5a_preparation_path),
        "u5aResultSha256": sha256_file(u5a_result_path),
        "scenes": scene_records,
        "noRenderedDepthProduced": True,
        "noU6aMetricsProduced": True,
    }
    final_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
