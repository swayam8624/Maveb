#!/usr/bin/env python3
"""Controlled resampling-lineage falsification probe for MAVEB.

The benchmark generates persistent physical surface patches represented by multiple Gaussian-like
primitives, applies split/prune/densify/merge-like resampling inside each patch, and compares:
  1. nearest-position correspondence,
  2. a position+appearance heuristic,
  3. explicit propagated surface-lineage metadata.

The downstream task is edit propagation: an edit authored on selected original surface patches must
target exactly their descendants after resampling. The explicit lineage path is not assumed novel;
this probe asks whether primitive-index-independent lineage has measurable downstream value over
recovered correspondence under hostile resampling.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SEED = 20260920
PATCH_PAIRS = 24
PRIMITIVES_PER_PATCH = 6
PAIR_SEPARATION = 0.035
INTRA_PATCH_SIGMA = 0.018
RESAMPLE_JITTER = (0.005, 0.015, 0.030, 0.050)
SPLIT_PROBABILITY = 0.35
PRUNE_PROBABILITY = 0.12
DENSIFY_PROBABILITY = 0.18


@dataclass
class Cloud:
    position: np.ndarray
    color: np.ndarray
    scale: np.ndarray
    patch_id: np.ndarray


def f1(expected: np.ndarray, predicted: np.ndarray) -> float:
    tp = int(np.sum(expected & predicted))
    fp = int(np.sum(~expected & predicted))
    fn = int(np.sum(expected & ~predicted))
    if tp == 0:
        return 1.0 if fp == 0 and fn == 0 else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0


def make_initial(rng: np.random.Generator) -> Cloud:
    positions = []
    colors = []
    scales = []
    patches = []
    for pair in range(PATCH_PAIRS):
        base = rng.uniform(-1.0, 1.0, size=3)
        axis = rng.normal(size=3)
        axis /= np.linalg.norm(axis)
        for side in range(2):
            patch = pair * 2 + side
            center = base + axis * (PAIR_SEPARATION * (side - 0.5))
            # Paired surfaces intentionally have similar colors so appearance is useful but not
            # overwhelmingly discriminative.
            pair_color = rng.uniform(0.2, 0.8, size=3)
            color = np.clip(pair_color + (side - 0.5) * 0.04, 0.0, 1.0)
            for _ in range(PRIMITIVES_PER_PATCH):
                positions.append(center + rng.normal(scale=INTRA_PATCH_SIGMA, size=3))
                colors.append(np.clip(color + rng.normal(scale=0.025, size=3), 0.0, 1.0))
                scales.append(rng.uniform(0.012, 0.028, size=3))
                patches.append(patch)
    return Cloud(
        np.asarray(positions, dtype=np.float64),
        np.asarray(colors, dtype=np.float64),
        np.asarray(scales, dtype=np.float64),
        np.asarray(patches, dtype=np.int32),
    )


def resample(initial: Cloud, jitter: float, rng: np.random.Generator) -> Cloud:
    positions: list[np.ndarray] = []
    colors: list[np.ndarray] = []
    scales: list[np.ndarray] = []
    patches: list[int] = []

    for i in range(initial.position.shape[0]):
        if rng.random() < PRUNE_PROBABILITY:
            continue

        copies = 2 if rng.random() < SPLIT_PROBABILITY else 1
        if rng.random() < DENSIFY_PROBABILITY:
            copies += 1

        for child in range(copies):
            offset = rng.normal(scale=jitter, size=3)
            if copies > 1:
                direction = rng.normal(size=3)
                norm = np.linalg.norm(direction)
                if norm > 1e-12:
                    offset += direction / norm * initial.scale[i].max() * (child - 0.5)
            positions.append(initial.position[i] + offset)
            colors.append(
                np.clip(initial.color[i] + rng.normal(scale=0.035 + jitter * 0.4, size=3), 0.0, 1.0)
            )
            scales.append(np.maximum(initial.scale[i] * rng.uniform(0.7, 1.25, size=3), 1e-4))
            patches.append(int(initial.patch_id[i]))

    # Approximate same-surface merge: fuse a deterministic fraction of neighbors sharing a patch.
    by_patch: dict[int, list[int]] = {}
    for idx, patch in enumerate(patches):
        by_patch.setdefault(patch, []).append(idx)

    removed: set[int] = set()
    merged_positions: list[np.ndarray] = []
    merged_colors: list[np.ndarray] = []
    merged_scales: list[np.ndarray] = []
    merged_patches: list[int] = []
    for patch, ids in by_patch.items():
        if len(ids) >= 4 and rng.random() < 0.35:
            a, b = ids[0], ids[1]
            removed.update((a, b))
            merged_positions.append((positions[a] + positions[b]) * 0.5)
            merged_colors.append((colors[a] + colors[b]) * 0.5)
            merged_scales.append(np.maximum(scales[a], scales[b]))
            merged_patches.append(patch)

    kept = [i for i in range(len(positions)) if i not in removed]
    final_position = [positions[i] for i in kept] + merged_positions
    final_color = [colors[i] for i in kept] + merged_colors
    final_scale = [scales[i] for i in kept] + merged_scales
    final_patch = [patches[i] for i in kept] + merged_patches

    return Cloud(
        np.asarray(final_position, dtype=np.float64),
        np.asarray(final_color, dtype=np.float64),
        np.asarray(final_scale, dtype=np.float64),
        np.asarray(final_patch, dtype=np.int32),
    )


def nearest_prediction(initial: Cloud, current: Cloud) -> np.ndarray:
    predicted = np.empty(current.position.shape[0], dtype=np.int32)
    for i, p in enumerate(current.position):
        delta = initial.position - p
        score = np.einsum("ij,ij->i", delta, delta)
        predicted[i] = initial.patch_id[int(np.argmin(score))]
    return predicted


def position_appearance_prediction(initial: Cloud, current: Cloud) -> np.ndarray:
    predicted = np.empty(current.position.shape[0], dtype=np.int32)
    for i, (p, color) in enumerate(zip(current.position, current.color, strict=True)):
        delta = initial.position - p
        spatial = np.einsum("ij,ij->i", delta, delta)
        color_delta = initial.color - color
        appearance = np.einsum("ij,ij->i", color_delta, color_delta)
        # Scale chosen once, not tuned per jitter condition.
        score = spatial + 0.12 * appearance
        predicted[i] = initial.patch_id[int(np.argmin(score))]
    return predicted


def metrics(true_patch: np.ndarray, predicted_patch: np.ndarray, selected_patches: set[int]) -> dict[str, float]:
    expected_edit = np.isin(true_patch, list(selected_patches))
    predicted_edit = np.isin(predicted_patch, list(selected_patches))
    return {
        "patchIdentityAccuracy": float(np.mean(true_patch == predicted_patch)),
        "identitySwitchRate": float(np.mean(true_patch != predicted_patch)),
        "editPropagationF1": f1(expected_edit, predicted_edit),
        "falseEditFraction": float(np.mean(~expected_edit & predicted_edit)),
        "missedEditFraction": float(np.mean(expected_edit & ~predicted_edit)),
    }


def run() -> dict:
    rows = []
    for level, jitter in enumerate(RESAMPLE_JITTER):
        rng = np.random.default_rng(SEED)
        initial = make_initial(rng)
        current = resample(initial, jitter, rng)
        selected = {patch for patch in range(PATCH_PAIRS * 2) if patch % 2 == 0}

        nearest = nearest_prediction(initial, current)
        appearance = position_appearance_prediction(initial, current)
        explicit = current.patch_id.copy()

        rows.append(
            {
                "jitter": jitter,
                "initialPrimitives": int(initial.position.shape[0]),
                "resampledPrimitives": int(current.position.shape[0]),
                "nearest": metrics(current.patch_id, nearest, selected),
                "positionAppearance": metrics(current.patch_id, appearance, selected),
                "propagatedLineage": metrics(current.patch_id, explicit, selected),
            }
        )

    return {
        "schemaVersion": 1,
        "experiment": "resampling-lineage-v1",
        "status": "synthetic-controlled-resampling-probe",
        "warning": (
            "Propagated lineage is an explicit-system upper bound when resampling operations are "
            "owned by MAVEB; it is not evidence that external independently reconstructed clouds "
            "can recover lineage without correspondence."
        ),
        "configuration": {
            "seed": SEED,
            "patchPairs": PATCH_PAIRS,
            "primitivesPerPatch": PRIMITIVES_PER_PATCH,
            "pairSeparation": PAIR_SEPARATION,
            "intraPatchSigma": INTRA_PATCH_SIGMA,
            "resampleJitter": list(RESAMPLE_JITTER),
            "splitProbability": SPLIT_PROBABILITY,
            "pruneProbability": PRUNE_PROBABILITY,
            "densifyProbability": DENSIFY_PROBABILITY,
        },
        "runtime": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "rows": rows,
    }


def self_test(result: dict) -> None:
    for row in result["rows"]:
        lineage = row["propagatedLineage"]
        if lineage["patchIdentityAccuracy"] != 1.0 or lineage["editPropagationF1"] != 1.0:
            raise RuntimeError("explicit lineage must preserve controlled resampling ground truth")
    hardest = result["rows"][-1]
    if hardest["nearest"]["editPropagationF1"] >= hardest["propagatedLineage"]["editPropagationF1"]:
        raise RuntimeError("hostile fixture must expose downstream value beyond nearest matching")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    result = run()
    if args.self_test:
        self_test(result)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(text)
        temporary.replace(args.output)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
