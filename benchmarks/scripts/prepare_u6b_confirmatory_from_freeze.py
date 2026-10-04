#!/usr/bin/env python3
"""Prepare U6b from committed acquisition/preflight evidence and deterministic local assets.

The original acquisition ledger and detailed runtime preflight intentionally contained machine-
local paths / large operational detail and were not committed. Their public-safe freeze records
preserve the original frozen SHA-256 bindings and outcome-free summaries. This wrapper resolves
and re-verifies the frozen assets, deterministically reconstructs the detailed preflight, verifies
that reconstruction against the committed summary freeze, then delegates to the preregistered
U6b preparation implementation without weakening the original provenance chain.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

import prepare_u6b_confirmatory_visibility as base
import preflight_u6b_confirmatory_inputs as preflight


ACQUISITION_FREEZE_STAGE = "U6b-confirmatory-asset-acquisition-freeze"
PREFLIGHT_FREEZE_STAGE = "U6b-confirmatory-pose-and-orientation-preflight-freeze"


def validate_acquisition_evidence(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text())
    if payload.get("study") != base.STUDY_ID:
        raise ValueError("U6b acquisition evidence study mismatch")
    if payload.get("stage") != ACQUISITION_FREEZE_STAGE:
        raise ValueError("U6b acquisition evidence stage mismatch")
    if payload.get("status") != "acquired-after-frozen-clean-plan":
        raise ValueError("U6b acquisition evidence status mismatch")
    if payload.get("protocolSha256") != base.PROTOCOL_SHA256:
        raise ValueError("U6b acquisition evidence protocol SHA mismatch")
    if payload.get("acquisitionLedgerSha256") != base.ACQUISITION_SHA256:
        raise ValueError("U6b acquisition evidence no longer binds the frozen runtime ledger")
    videos = [str(item["videoId"]) for item in payload.get("entries", [])]
    if videos != base.EXPECTED_VIDEOS:
        raise ValueError(f"U6b acquisition evidence video order mismatch: {videos}")
    if payload.get("selectedAssetsAbsentAtFrozenPlan") is not True:
        raise ValueError("U6b acquisition evidence clean-plan boundary changed")
    if int(payload.get("partialFilesRemaining", -1)) != 0:
        raise ValueError("U6b acquisition evidence records partial files")
    if int(payload.get("u6bRenderedDepthCountAfterAcquisition", -1)) != 0:
        raise ValueError("U6b acquisition evidence crossed the render-outcome boundary")
    return payload


def validate_preflight_evidence(path: Path) -> dict:
    """Validate the committed summary freeze, not the unavailable detailed runtime artifact."""
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text())
    if payload.get("study") != base.STUDY_ID:
        raise ValueError("U6b preflight evidence study mismatch")
    if payload.get("stage") != PREFLIGHT_FREEZE_STAGE:
        raise ValueError("U6b preflight evidence stage mismatch")
    if payload.get("status") != "passed" or payload.get("allScenesPassed") is not True:
        raise ValueError("U6b preflight evidence does not record a passed freeze")
    if payload.get("protocolSha256") != base.PROTOCOL_SHA256:
        raise ValueError("U6b preflight evidence protocol SHA mismatch")
    if payload.get("acquisitionLedgerSha256") != base.ACQUISITION_SHA256:
        raise ValueError("U6b preflight evidence acquisition SHA mismatch")
    if payload.get("inputPreflightSha256") != base.PREFLIGHT_SHA256:
        raise ValueError("U6b preflight evidence no longer binds the frozen runtime preflight")
    if payload.get("inputPreflightLogSha256") != base.PREFLIGHT_SHA256:
        raise ValueError("U6b preflight evidence log SHA mismatch")
    if payload.get("noRepresentationOutcomeProduced") is not True:
        raise ValueError("U6b preflight evidence crossed the representation-outcome boundary")
    if int(payload.get("u6bPlyCountAfterPreflight", -1)) != 0:
        raise ValueError("U6b preflight evidence records Gaussian PLY outcomes")
    if int(payload.get("u6bRenderedDepthCountAfterPreflight", -1)) != 0:
        raise ValueError("U6b preflight evidence records rendered-depth outcomes")
    videos = [str(item["videoId"]) for item in payload.get("scenes", [])]
    if videos != base.EXPECTED_VIDEOS:
        raise ValueError(f"U6b preflight evidence video order mismatch: {videos}")
    return payload


def _png_count(path: Path) -> int:
    if not path.is_dir():
        return 0
    return len(list(path.glob("*.png")))


def _require_hash(path: Path, expected_sha: str, *, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    actual = base.sha256_file(path)
    if actual != expected_sha:
        raise ValueError(f"{label} SHA mismatch: {actual} != {expected_sha}")


def resolve_runtime_acquisition(
    evidence: dict,
    *,
    ca1m_root: Path,
    arkit_root: Path,
) -> dict:
    ca1m_root = ca1m_root.expanduser().resolve()
    arkit_root = arkit_root.expanduser().resolve()
    resolved_entries: list[dict] = []

    for item in evidence["entries"]:
        video = str(item["videoId"])
        raw_root = arkit_root / "raw" / "Validation" / video
        archive = ca1m_root / f"ca1m-val-{video}.tar"
        confidence_zip = raw_root / "confidence.zip"
        lowres_zip = raw_root / "lowres_depth.zip"
        confidence_dir = raw_root / "confidence"
        lowres_dir = raw_root / "lowres_depth"

        _require_hash(archive, item["ca1mArchiveSha256"], label=f"U6b CA-1M archive {video}")
        _require_hash(
            confidence_zip,
            item["confidenceZipSha256"],
            label=f"U6b confidence ZIP {video}",
        )
        _require_hash(
            lowres_zip,
            item["lowresDepthZipSha256"],
            label=f"U6b lowres-depth ZIP {video}",
        )

        confidence_count = _png_count(confidence_dir)
        lowres_count = _png_count(lowres_dir)
        if confidence_count != int(item["confidencePngCount"]):
            raise ValueError(
                f"U6b confidence PNG count mismatch for {video}: "
                f"{confidence_count} != {item['confidencePngCount']}"
            )
        if lowres_count != int(item["lowresDepthPngCount"]):
            raise ValueError(
                f"U6b lowres-depth PNG count mismatch for {video}: "
                f"{lowres_count} != {item['lowresDepthPngCount']}"
            )
        if archive.stat().st_size != int(item["ca1mArchiveBytes"]):
            raise ValueError(f"U6b CA-1M archive byte count mismatch for {video}")

        resolved_entries.append(
            {
                **item,
                "ca1mArchive": str(archive),
                "confidenceZip": str(confidence_zip),
                "lowresDepthZip": str(lowres_zip),
            }
        )

    return {
        "schemaVersion": 1,
        "study": base.STUDY_ID,
        "stage": "U6b-confirmatory-runtime-asset-resolution",
        "status": "resolved-from-frozen-acquisition-evidence",
        "protocolSha256": base.PROTOCOL_SHA256,
        "acquisitionLedgerSha256": base.ACQUISITION_SHA256,
        "entries": resolved_entries,
    }


def _assert_float_equal(actual: object, expected: object, *, label: str) -> None:
    if actual is None or expected is None:
        if actual != expected:
            raise ValueError(f"{label} mismatch: {actual!r} != {expected!r}")
        return
    if not math.isclose(float(actual), float(expected), rel_tol=1.0e-12, abs_tol=1.0e-12):
        raise ValueError(f"{label} mismatch: {actual!r} != {expected!r}")


def verify_reconstructed_scene(runtime_scene: dict, frozen_scene: dict) -> None:
    video = str(runtime_scene["videoId"])
    if str(frozen_scene.get("videoId")) != video:
        raise ValueError(f"U6b reconstructed preflight video mismatch for {video}")
    if str(runtime_scene["visitId"]) != str(frozen_scene.get("visitId")):
        raise ValueError(f"U6b reconstructed preflight visit mismatch for {video}")
    if int(runtime_scene["completeFrames"]) != int(frozen_scene.get("completeFrames", -1)):
        raise ValueError(f"U6b reconstructed complete-frame count mismatch for {video}")

    pose = runtime_scene["poseConventionValidation"]
    exact_pose_fields = {
        "posePassed": bool(pose["passed"]),
        "cameraToWorldSupportedPairCount": int(pose["cameraToWorldSupportedPairCount"]),
        "inverseSupportedPairCount": int(pose["inverseSupportedPairCount"]),
        "mutuallyComparablePairCount": int(pose["mutuallyComparablePairCount"]),
        "cameraToWorldWinsAmongComparable": int(pose["cameraToWorldWinsAmongComparable"]),
    }
    for key, actual in exact_pose_fields.items():
        if frozen_scene.get(key) != actual:
            raise ValueError(
                f"U6b reconstructed {key} mismatch for {video}: "
                f"{actual!r} != {frozen_scene.get(key)!r}"
            )
    _assert_float_equal(
        pose["cameraToWorldMedianOfSupportedPairMediansMetres"],
        frozen_scene.get("cameraToWorldMedianOfSupportedPairMediansMetres"),
        label=f"U6b reconstructed camera-to-world median for {video}",
    )
    _assert_float_equal(
        pose["inverseMedianOfSupportedPairMediansMetres"],
        frozen_scene.get("inverseMedianOfSupportedPairMediansMetres"),
        label=f"U6b reconstructed inverse median for {video}",
    )

    sources = runtime_scene["primaryEightViewSelection"]
    accepted = [
        item
        for item in sources
        if item.get("sidecarMatched")
        and item.get("orientationAccepted")
        and item.get("confidenceLevelsAndShapeValid")
    ]
    orientation_passed = len(accepted) == preflight.PRIMARY_VIEWS
    if frozen_scene.get("orientationPassed") is not orientation_passed:
        raise ValueError(f"U6b reconstructed orientation decision mismatch for {video}")
    if int(frozen_scene.get("acceptedSourceCount", -1)) != len(accepted):
        raise ValueError(f"U6b reconstructed accepted-source count mismatch for {video}")
    if runtime_scene["scenePassed"] is not bool(pose["passed"] and orientation_passed):
        raise ValueError(f"U6b reconstructed internal scene decision mismatch for {video}")

    best_records = [item["bestOrientation"] for item in accepted]
    maximum_best = max(float(item["medianAbsErrorMillimetres"]) for item in best_records)
    _assert_float_equal(
        maximum_best,
        frozen_scene.get("maximumBestOrientationMedianAbsErrorMillimetres"),
        label=f"U6b reconstructed maximum orientation median for {video}",
    )
    transform_counts = Counter(str(item["transform"]) for item in best_records)
    frozen_dominant = str(frozen_scene.get("dominantAcceptedTransform"))
    maximum_count = max(transform_counts.values())
    if transform_counts.get(frozen_dominant, 0) != maximum_count:
        raise ValueError(f"U6b reconstructed dominant orientation mismatch for {video}")


def reconstruct_runtime_preflight(
    preflight_evidence: dict,
    runtime_acquisition: dict,
    *,
    arkit_root: Path,
) -> dict:
    """Rebuild the detailed deterministic preflight and verify it against the freeze summary."""
    frozen_by_video = {
        str(item["videoId"]): item for item in preflight_evidence.get("scenes", [])
    }
    scenes: list[dict] = []
    for entry in runtime_acquisition["entries"]:
        video = str(entry["videoId"])
        archive = Path(entry["ca1mArchive"])
        raw_root = arkit_root.expanduser().resolve() / "raw" / "Validation" / video
        pose = preflight.pose_validation(archive, video)
        complete_frames, sources = preflight.selected_source_frames(
            archive,
            video,
            raw_root / "confidence",
            raw_root / "lowres_depth",
        )
        orientation_passed = all(
            item.get("sidecarMatched")
            and item.get("orientationAccepted")
            and item.get("confidenceLevelsAndShapeValid")
            for item in sources
        )
        runtime_scene = {
            "videoId": video,
            "visitId": str(entry["visitId"]),
            "completeFrames": complete_frames,
            "poseConventionValidation": pose,
            "primaryEightViewSelection": sources,
            "orientationPreflightPassed": orientation_passed,
            "scenePassed": bool(pose["passed"] and orientation_passed),
        }
        frozen_scene = frozen_by_video.get(video)
        if frozen_scene is None:
            raise ValueError(f"U6b preflight evidence is missing frozen scene {video}")
        verify_reconstructed_scene(runtime_scene, frozen_scene)
        scenes.append(runtime_scene)

    if [str(item["videoId"]) for item in scenes] != base.EXPECTED_VIDEOS:
        raise ValueError("U6b reconstructed preflight scene order changed")
    if not all(item["scenePassed"] for item in scenes):
        raise ValueError("U6b reconstructed preflight contains a failed scene")

    return {
        "schemaVersion": 1,
        "study": base.STUDY_ID,
        "stage": "U6b-confirmatory-pose-and-orientation-preflight",
        "status": "passed",
        "acquisitionLedgerSha256": base.ACQUISITION_SHA256,
        "protocolSha256": base.PROTOCOL_SHA256,
        "primaryViewCount": preflight.PRIMARY_VIEWS,
        "poseValidationPairCount": preflight.VALIDATION_PAIRS,
        "posePixelStride": preflight.POSE_PIXEL_STRIDE,
        "noRepresentationOutcomeProduced": True,
        "scenes": scenes,
    }


def finalize_preparation_provenance(
    preparation_path: Path,
    *,
    acquisition_evidence_path: Path,
    acquisition_evidence: dict,
    preflight_evidence_path: Path,
    preflight_evidence: dict,
) -> None:
    if not preparation_path.is_file():
        raise FileNotFoundError(preparation_path)
    payload = json.loads(preparation_path.read_text())
    if payload.get("study") != base.STUDY_ID:
        raise ValueError("U6b generated preparation study mismatch")
    if payload.get("status") != "prepared-no-u6b-render-or-metric-outcomes":
        raise ValueError("U6b generated preparation status mismatch")
    if payload.get("noRenderedDepthProduced") is not True:
        raise ValueError("U6b generated preparation unexpectedly produced render outcomes")
    if payload.get("noU6bMetricsProduced") is not True:
        raise ValueError("U6b generated preparation unexpectedly produced metrics")

    acquisition_evidence_sha = base.sha256_file(acquisition_evidence_path)
    if payload.get("acquisitionLedgerSha256") != acquisition_evidence_sha:
        raise ValueError(
            "U6b preparation delegate did not bind the supplied acquisition evidence as expected"
        )
    preflight_evidence_sha = base.sha256_file(preflight_evidence_path)
    if payload.get("inputPreflightSha256") != preflight_evidence_sha:
        raise ValueError(
            "U6b preparation delegate did not bind the supplied preflight evidence as expected"
        )

    # Restore the original preregistered runtime-artifact bindings required downstream while
    # separately recording the exact committed evidence files supplied to this bridge.
    payload["acquisitionLedgerSha256"] = acquisition_evidence["acquisitionLedgerSha256"]
    payload["acquisitionEvidenceSha256"] = acquisition_evidence_sha
    payload["acquisitionEvidenceStage"] = acquisition_evidence["stage"]
    payload["inputPreflightSha256"] = preflight_evidence["inputPreflightSha256"]
    payload["inputPreflightEvidenceSha256"] = preflight_evidence_sha
    payload["inputPreflightEvidenceStage"] = preflight_evidence["stage"]
    payload["assetResolution"] = (
        "deterministic local roots; all five CA-1M archives and ten ARKitScenes ZIPs "
        "reverified against the frozen acquisition evidence before preparation"
    )
    payload["preflightResolution"] = (
        "detailed runtime preflight deterministically reconstructed from the frozen assets and "
        "verified scene-by-scene against the committed pose/orientation summary freeze"
    )
    preparation_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--acquisition-evidence", type=Path, required=True)
    parser.add_argument("--input-preflight", type=Path, required=True)
    parser.add_argument("--ca1m-root", type=Path, required=True)
    parser.add_argument("--arkit-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    acquisition_evidence_path = args.acquisition_evidence.resolve()
    acquisition_evidence = validate_acquisition_evidence(acquisition_evidence_path)
    runtime_acquisition = resolve_runtime_acquisition(
        acquisition_evidence,
        ca1m_root=args.ca1m_root,
        arkit_root=args.arkit_root,
    )

    preflight_evidence_path = args.input_preflight.resolve()
    preflight_evidence = validate_preflight_evidence(preflight_evidence_path)
    runtime_preflight = reconstruct_runtime_preflight(
        preflight_evidence,
        runtime_acquisition,
        arkit_root=args.arkit_root,
    )

    # Keep the mature preparation implementation and frozen math unchanged. Replace only the
    # unavailable path-bearing acquisition ledger and detailed runtime-preflight loaders with
    # their independently reconstructed, freeze-verified equivalents.
    original_validate_acquisition = base.validate_acquisition
    original_validate_preflight = base.validate_preflight
    original_argv = sys.argv
    try:
        base.validate_acquisition = lambda _path: runtime_acquisition
        base.validate_preflight = lambda _path: runtime_preflight
        sys.argv = [
            str(Path(base.__file__).resolve()),
            "--protocol",
            str(args.protocol.resolve()),
            "--acquisition-ledger",
            str(acquisition_evidence_path),
            "--input-preflight",
            str(preflight_evidence_path),
            "--arkit-root",
            str(args.arkit_root.expanduser().resolve()),
            "--output-root",
            str(args.output_root.expanduser().resolve()),
        ]
        result = base.main()
    finally:
        base.validate_acquisition = original_validate_acquisition
        base.validate_preflight = original_validate_preflight
        sys.argv = original_argv

    if result != 0:
        return int(result)
    preparation_path = args.output_root.expanduser().resolve() / "preparation.json"
    finalize_preparation_provenance(
        preparation_path,
        acquisition_evidence_path=acquisition_evidence_path,
        acquisition_evidence=acquisition_evidence,
        preflight_evidence_path=preflight_evidence_path,
        preflight_evidence=preflight_evidence,
    )
    print(
        json.dumps(
            {
                "u6bPreparationFromFreeze": {
                    "status": "prepared-and-rebound-to-original-runtime-provenance",
                    "preparation": str(preparation_path),
                    "preparationSha256": base.sha256_file(preparation_path),
                    "acquisitionLedgerSha256": acquisition_evidence["acquisitionLedgerSha256"],
                    "acquisitionEvidenceSha256": base.sha256_file(acquisition_evidence_path),
                    "inputPreflightSha256": preflight_evidence["inputPreflightSha256"],
                    "inputPreflightEvidenceSha256": base.sha256_file(preflight_evidence_path),
                    "noConfirmatoryOutcomeProduced": True,
                }
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
