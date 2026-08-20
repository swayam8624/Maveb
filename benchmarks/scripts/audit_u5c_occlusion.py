#!/usr/bin/env python3
"""Audit U5a Gaussian covariance failure for coverage-driven occlusion leakage."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

import numpy as np


STUDY_ID = "metric-uncertainty-u5c-occlusion-audit-v1"
EXPECTED_SCENES = [
    "ca1m-48458481",
    "ca1m-48018737",
    "ca1m-45261587",
    "ca1m-42897538",
    "ca1m-48018375",
]
PAIRS = {
    "candidateVsDepthOnly": ("calibrated-covariance", "depth-only-covariance"),
    "shuffledVsDepthOnly": ("shuffled-calibrated-covariance", "depth-only-covariance"),
    "candidateVsShuffled": ("calibrated-covariance", "shuffled-calibrated-covariance"),
}
FRACTION_KEYS = (
    "challengerOnlyCoverageFraction",
    "referenceOnlyCoverageFraction",
    "bothFiniteFraction",
    "challengerOnlyWithin5cmFractionOfFaroValid",
    "challengerOnlyForegroundWrongFractionOfFaroValid",
    "challengerOnlyBackgroundWrongFractionOfFaroValid",
    "challengerOnlyForegroundWrongShare",
    "challengerOnlyBackgroundWrongShare",
    "challengerOnlyWithin5cmShare",
    "bothFiniteChallengerCloserShare",
    "bothFiniteReferenceCloserShare",
    "referenceCorrectChallengerWrongFractionOfFaroValid",
    "challengerCorrectReferenceWrongFractionOfFaroValid",
)
MEDIAN_KEYS = (
    "medianRenderedDepthShiftMetres",
    "medianAbsoluteErrorShiftMetres",
)
COUNT_KEYS = (
    "faroValidPixelCount",
    "challengerOnlyCount",
    "referenceOnlyCount",
    "bothFiniteCount",
    "challengerOnlyWithin5cmCount",
    "challengerOnlyForegroundWrongCount",
    "challengerOnlyBackgroundWrongCount",
    "bothFiniteChallengerCloserCount",
    "bothFiniteReferenceCloserCount",
    "referenceCorrectChallengerWrongCount",
    "challengerCorrectReferenceWrongCount",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nearest_tie_lower(values: list[float], fraction: float) -> float | None:
    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        return None
    target = fraction * (len(finite) - 1)
    lower = math.floor(target)
    upper = math.ceil(target)
    index = lower if target - lower <= upper - target else upper
    return finite[index]


def paired_bootstrap_median(values: list[float], *, replicates: int, seed: int) -> dict:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return {
            "sceneValues": [],
            "definedSceneCount": 0,
            "median": None,
            "replicates": replicates,
            "seed": seed,
            "lower95": None,
            "upper95": None,
        }
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(replicates):
        sample = [finite[rng.randrange(len(finite))] for _ in range(len(finite))]
        stats.append(float(statistics.median(sample)))
    return {
        "sceneValues": finite,
        "definedSceneCount": len(finite),
        "median": float(statistics.median(finite)),
        "replicates": replicates,
        "seed": seed,
        "lower95": nearest_tie_lower(stats, 0.025),
        "upper95": nearest_tie_lower(stats, 0.975),
    }


def _fraction(count: int, denominator: int) -> float | None:
    return None if denominator == 0 else float(count / denominator)


def pair_metrics(
    challenger: np.ndarray,
    reference: np.ndarray,
    faro: np.ndarray,
    *,
    correct_threshold: float = 0.05,
    tie_tolerance: float = 1.0e-6,
) -> dict:
    challenger = np.asarray(challenger, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    faro = np.asarray(faro, dtype=np.float64)
    if challenger.shape != reference.shape or challenger.shape != faro.shape:
        raise ValueError("U5c pairwise depth shapes differ")

    faro_valid = np.isfinite(faro) & (faro > 0.0)
    faro_count = int(np.count_nonzero(faro_valid))
    if faro_count == 0:
        raise ValueError("U5c FARO target has no valid pixels")

    challenger_valid = faro_valid & np.isfinite(challenger)
    reference_valid = faro_valid & np.isfinite(reference)
    challenger_only = challenger_valid & ~reference_valid
    reference_only = reference_valid & ~challenger_valid
    both = challenger_valid & reference_valid

    challenger_error = np.abs(challenger - faro)
    reference_error = np.abs(reference - faro)
    challenger_correct = challenger_error <= correct_threshold
    reference_correct = reference_error <= correct_threshold
    challenger_foreground_wrong = challenger < faro - correct_threshold
    challenger_background_wrong = challenger > faro + correct_threshold

    challenger_only_count = int(np.count_nonzero(challenger_only))
    reference_only_count = int(np.count_nonzero(reference_only))
    both_count = int(np.count_nonzero(both))
    challenger_only_within = int(np.count_nonzero(challenger_only & challenger_correct))
    challenger_only_foreground = int(np.count_nonzero(challenger_only & challenger_foreground_wrong))
    challenger_only_background = int(np.count_nonzero(challenger_only & challenger_background_wrong))

    challenger_closer = both & (challenger_error + tie_tolerance < reference_error)
    reference_closer = both & (reference_error + tie_tolerance < challenger_error)
    reference_correct_challenger_wrong = both & reference_correct & ~challenger_correct
    challenger_correct_reference_wrong = both & challenger_correct & ~reference_correct

    rendered_shift = challenger[both] - reference[both]
    absolute_error_shift = challenger_error[both] - reference_error[both]

    return {
        "faroValidPixelCount": faro_count,
        "challengerOnlyCount": challenger_only_count,
        "referenceOnlyCount": reference_only_count,
        "bothFiniteCount": both_count,
        "challengerOnlyWithin5cmCount": challenger_only_within,
        "challengerOnlyForegroundWrongCount": challenger_only_foreground,
        "challengerOnlyBackgroundWrongCount": challenger_only_background,
        "bothFiniteChallengerCloserCount": int(np.count_nonzero(challenger_closer)),
        "bothFiniteReferenceCloserCount": int(np.count_nonzero(reference_closer)),
        "referenceCorrectChallengerWrongCount": int(
            np.count_nonzero(reference_correct_challenger_wrong)
        ),
        "challengerCorrectReferenceWrongCount": int(
            np.count_nonzero(challenger_correct_reference_wrong)
        ),
        "challengerOnlyCoverageFraction": float(challenger_only_count / faro_count),
        "referenceOnlyCoverageFraction": float(reference_only_count / faro_count),
        "bothFiniteFraction": float(both_count / faro_count),
        "challengerOnlyWithin5cmFractionOfFaroValid": float(challenger_only_within / faro_count),
        "challengerOnlyForegroundWrongFractionOfFaroValid": float(
            challenger_only_foreground / faro_count
        ),
        "challengerOnlyBackgroundWrongFractionOfFaroValid": float(
            challenger_only_background / faro_count
        ),
        "challengerOnlyForegroundWrongShare": _fraction(
            challenger_only_foreground, challenger_only_count
        ),
        "challengerOnlyBackgroundWrongShare": _fraction(
            challenger_only_background, challenger_only_count
        ),
        "challengerOnlyWithin5cmShare": _fraction(challenger_only_within, challenger_only_count),
        "bothFiniteChallengerCloserShare": _fraction(
            int(np.count_nonzero(challenger_closer)), both_count
        ),
        "bothFiniteReferenceCloserShare": _fraction(
            int(np.count_nonzero(reference_closer)), both_count
        ),
        "referenceCorrectChallengerWrongFractionOfFaroValid": float(
            np.count_nonzero(reference_correct_challenger_wrong) / faro_count
        ),
        "challengerCorrectReferenceWrongFractionOfFaroValid": float(
            np.count_nonzero(challenger_correct_reference_wrong) / faro_count
        ),
        "medianRenderedDepthShiftMetres": None
        if rendered_shift.size == 0
        else float(np.median(rendered_shift)),
        "medianAbsoluteErrorShiftMetres": None
        if absolute_error_shift.size == 0
        else float(np.median(absolute_error_shift)),
    }


def mean_defined(records: list[dict], key: str) -> float | None:
    values = [float(record[key]) for record in records if record[key] is not None]
    return None if not values else float(statistics.mean(values))


def scene_summary(targets: list[dict]) -> dict:
    if len(targets) != 8:
        raise ValueError("U5c scene summary requires eight target views")
    summary: dict[str, object] = {"targetViewCount": 8}
    for key in FRACTION_KEYS:
        summary[f"{key}Mean"] = mean_defined(targets, key)
    for key in MEDIAN_KEYS:
        summary[f"{key}MeanAcrossDefinedTargets"] = mean_defined(targets, key)
    summary["pooledCounts"] = {key: int(sum(int(record[key]) for record in targets)) for key in COUNT_KEYS}
    pooled = summary["pooledCounts"]
    challenger_only_count = int(pooled["challengerOnlyCount"])
    summary["pooledChallengerOnlyForegroundWrongShare"] = _fraction(
        int(pooled["challengerOnlyForegroundWrongCount"]), challenger_only_count
    )
    summary["pooledChallengerOnlyBackgroundWrongShare"] = _fraction(
        int(pooled["challengerOnlyBackgroundWrongCount"]), challenger_only_count
    )
    summary["pooledChallengerOnlyWithin5cmShare"] = _fraction(
        int(pooled["challengerOnlyWithin5cmCount"]), challenger_only_count
    )
    return summary


def target_record_by_index(method_payload: dict) -> dict[int, dict]:
    result = {int(record["targetIndex"]): record for record in method_payload["targets"]}
    if set(result) != set(range(8)):
        raise ValueError("U5c U5a result target indices are not exactly 0..7")
    return result


def read_depth(path: Path, *, width: int, height: int) -> np.ndarray:
    values = np.fromfile(path, dtype="<f4")
    expected = width * height
    if values.size != expected:
        raise ValueError(f"U5c depth byte count mismatch: {path}")
    return values.reshape(height, width)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--u5a-result", type=Path, required=True)
    parser.add_argument("--u5a-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise ValueError("U5c output already exists; mechanism audit will not be overwritten")
    if not args.protocol.is_file() or not args.u5a_result.is_file():
        raise FileNotFoundError("U5c protocol or U5a result is missing")

    protocol = json.loads(args.protocol.read_text())
    if protocol.get("id") != STUDY_ID or not protocol.get("frozen"):
        raise ValueError("U5c protocol is not frozen")
    expected_result_sha = protocol["parentEvidence"]["u5aResultSha256"]
    actual_result_sha = sha256_file(args.u5a_result)
    if actual_result_sha != expected_result_sha:
        raise ValueError("U5c U5a result SHA mismatch")

    u5a = json.loads(args.u5a_result.read_text())
    if u5a.get("status") != "completed-exploratory-gaussian-depth-study":
        raise ValueError("U5c source U5a result is not complete")
    if list(protocol["scenes"]) != EXPECTED_SCENES:
        raise ValueError("U5c protocol scene order changed")

    scenes: dict[str, dict] = {}
    for scene in EXPECTED_SCENES:
        scene_payload = u5a["scenes"][scene]
        target_manifest_path = args.u5a_root / "scenes" / scene / "targets.json"
        if not target_manifest_path.is_file():
            raise FileNotFoundError(target_manifest_path)
        if sha256_file(target_manifest_path) != scene_payload["targetManifestSha256"]:
            raise ValueError(f"U5c target manifest SHA mismatch for {scene}")
        target_manifest = json.loads(target_manifest_path.read_text())
        targets = {int(target["targetIndex"]): target for target in target_manifest["targets"]}
        if set(targets) != set(range(8)):
            raise ValueError(f"U5c {scene} target indices are not exactly 0..7")

        method_targets: dict[str, dict[int, dict]] = {}
        for method, method_payload in scene_payload["methods"].items():
            method_targets[method] = target_record_by_index(method_payload)

        pair_results: dict[str, dict] = {}
        for pair_name, (challenger_method, reference_method) in PAIRS.items():
            target_metrics: list[dict] = []
            for target_index in range(8):
                target = targets[target_index]
                width = int(target["width"])
                height = int(target["height"])
                faro_path = Path(target["faroDepthPath"])
                if not faro_path.is_file() or sha256_file(faro_path) != target["faroDepthSha256"]:
                    raise ValueError(f"U5c FARO SHA mismatch for {scene} target {target_index}")

                challenger_record = method_targets[challenger_method][target_index]
                reference_record = method_targets[reference_method][target_index]
                challenger_path = (
                    args.u5a_root
                    / "scenes"
                    / scene
                    / "renders"
                    / challenger_method
                    / f"{target_index:02d}.f32"
                )
                reference_path = (
                    args.u5a_root
                    / "scenes"
                    / scene
                    / "renders"
                    / reference_method
                    / f"{target_index:02d}.f32"
                )
                if sha256_file(challenger_path) != challenger_record["renderSha256"]:
                    raise ValueError(
                        f"U5c challenger render SHA mismatch for {scene} {pair_name} target {target_index}"
                    )
                if sha256_file(reference_path) != reference_record["renderSha256"]:
                    raise ValueError(
                        f"U5c reference render SHA mismatch for {scene} {pair_name} target {target_index}"
                    )

                faro = read_depth(faro_path, width=width, height=height)
                challenger = read_depth(challenger_path, width=width, height=height)
                reference = read_depth(reference_path, width=width, height=height)
                metrics = pair_metrics(
                    challenger,
                    reference,
                    faro,
                    correct_threshold=0.05,
                    tie_tolerance=float(protocol["validity"]["depthTieToleranceMetres"]),
                )
                target_metrics.append(
                    {
                        "targetIndex": target_index,
                        "timestampNanoseconds": int(target["timestampNanoseconds"]),
                        **metrics,
                    }
                )
            pair_results[pair_name] = {
                "challenger": challenger_method,
                "reference": reference_method,
                "targets": target_metrics,
                "sceneSummary": scene_summary(target_metrics),
            }
        scenes[scene] = {"pairs": pair_results}

    def scene_values(pair: str, key: str) -> list[float]:
        values: list[float] = []
        for scene in EXPECTED_SCENES:
            value = scenes[scene]["pairs"][pair]["sceneSummary"][key]
            if value is not None:
                values.append(float(value))
        return values

    cross_scene = {
        "candidateVsDepthOnlyChallengerOnlyForegroundWrongShare": paired_bootstrap_median(
            scene_values("candidateVsDepthOnly", "challengerOnlyForegroundWrongShareMean"),
            replicates=2000,
            seed=42,
        ),
        "candidateVsDepthOnlyChallengerOnlyCoverageFraction": paired_bootstrap_median(
            scene_values("candidateVsDepthOnly", "challengerOnlyCoverageFractionMean"),
            replicates=2000,
            seed=42,
        ),
        "candidateVsDepthOnlyReferenceCorrectChallengerWrongFraction": paired_bootstrap_median(
            scene_values(
                "candidateVsDepthOnly",
                "referenceCorrectChallengerWrongFractionOfFaroValidMean",
            ),
            replicates=2000,
            seed=42,
        ),
        "candidateVsDepthOnlyChallengerCorrectReferenceWrongFraction": paired_bootstrap_median(
            scene_values(
                "candidateVsDepthOnly",
                "challengerCorrectReferenceWrongFractionOfFaroValidMean",
            ),
            replicates=2000,
            seed=42,
        ),
        "candidateVsDepthOnlyAbsoluteErrorShiftMetres": paired_bootstrap_median(
            scene_values(
                "candidateVsDepthOnly",
                "medianAbsoluteErrorShiftMetresMeanAcrossDefinedTargets",
            ),
            replicates=2000,
            seed=42,
        ),
        "shuffledVsDepthOnlyChallengerOnlyForegroundWrongShare": paired_bootstrap_median(
            scene_values("shuffledVsDepthOnly", "challengerOnlyForegroundWrongShareMean"),
            replicates=2000,
            seed=42,
        ),
        "candidateVsShuffledChallengerOnlyForegroundWrongShare": paired_bootstrap_median(
            scene_values("candidateVsShuffled", "challengerOnlyForegroundWrongShareMean"),
            replicates=2000,
            seed=42,
        ),
        "descriptiveOnly": True,
    }

    payload = {
        "schemaVersion": 1,
        "study": STUDY_ID,
        "stage": "U5c-post-hoc-gaussian-occlusion-mechanism-audit",
        "status": "completed-post-hoc-occlusion-audit",
        "claimType": protocol["claimType"],
        "protocolSha256": sha256_file(args.protocol),
        "u5aResultSha256": actual_result_sha,
        "scenes": scenes,
        "crossScene": cross_scene,
        "claimBoundary": protocol["claimBoundary"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
