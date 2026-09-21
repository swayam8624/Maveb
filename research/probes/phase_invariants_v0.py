#!/usr/bin/env python3
"""Cheap falsification probe for phase-derived geometry invariants.

This is intentionally NOT a production method. It asks one narrow question:
does a phase-derived descriptor separate true geometric change from
representation-equivalent-ish Gaussian resampling better than simpler controls?

The probe creates synthetic Gaussian-center neighborhoods, applies split/merge
resampling and controlled translation/rotation damage, then compares:
  * normalized Gaussian-density L2
  * FFT amplitude
  * amplitude-weighted wrapped FFT phase
  * pair-distance histogram
  * weighted centroid + covariance eigenvalues ("moments")

A promising phase result must survive harder local/neighborhood probes later.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import rankdata, spearmanr

GRID_N = 22
AXIS = np.linspace(-1.05, 1.05, GRID_N)
X, Y, Z = np.meshgrid(AXIS, AXIS, AXIS, indexing="ij")
GRID = np.stack([X, Y, Z], axis=-1)
METRICS = ["density_l2", "amplitude", "phase", "pair_hist", "moments"]


def make_shapes(seed: int, n: int = 64) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    out: dict[str, np.ndarray] = {}

    xy = rng.uniform(-0.75, 0.75, (n, 2))
    z = 0.08 * np.sin(2.5 * xy[:, 0]) * np.cos(2.0 * xy[:, 1])
    out["wavy_plane"] = np.c_[xy, z]

    phi = rng.uniform(0, 2 * np.pi, n)
    cost = rng.uniform(0.15, 1.0, n)
    sint = np.sqrt(1 - cost**2)
    radius = 0.68
    out["sphere_cap"] = np.c_[
        radius * sint * np.cos(phi),
        radius * sint * np.sin(phi),
        radius * cost - 0.25,
    ]

    m = n // 2
    a = rng.uniform(-0.7, 0.7, (m, 2))
    b = rng.uniform(-0.7, 0.7, (n - m, 2))
    out["corner"] = np.vstack(
        [np.c_[np.zeros(m), a[:, 0], a[:, 1]],
         np.c_[b[:, 0], np.zeros(n - m), b[:, 1]]]
    )

    t = np.linspace(-np.pi, np.pi, n) + rng.normal(0, 0.02, n)
    out["helix"] = np.c_[0.55 * np.cos(t), 0.55 * np.sin(t), 0.18 * t]
    return out


def gaussian_density(
    points: np.ndarray, weights: np.ndarray | None = None, sigma: float = 0.095
) -> np.ndarray:
    if weights is None:
        weights = np.ones(len(points), dtype=np.float64) / len(points)
    result = np.zeros((GRID_N, GRID_N, GRID_N), dtype=np.float64)
    inv = 1.0 / (2.0 * sigma * sigma)
    for point, weight in zip(points, weights):
        delta = GRID - point
        result += weight * np.exp(-np.sum(delta * delta, axis=-1) * inv)
    result /= np.linalg.norm(result) + 1e-12
    return result


def describe(points: np.ndarray, weights: np.ndarray | None = None) -> dict[str, np.ndarray]:
    den = gaussian_density(points, weights)
    fft = np.fft.fftn(den)
    mag = np.abs(fft)
    mag_norm = mag / (mag.sum() + 1e-12)

    if len(points) > 1:
        ii, jj = np.triu_indices(len(points), 1)
        pair = np.linalg.norm(points[ii] - points[jj], axis=1)
    else:
        pair = np.array([0.0])
    hist, _ = np.histogram(pair, bins=48, range=(0.0, 2.2), density=False)
    hist = hist.astype(np.float64)
    hist /= hist.sum() + 1e-12

    if weights is None:
        weights = np.ones(len(points), dtype=np.float64) / len(points)
    weights = np.asarray(weights, dtype=np.float64)
    weights /= weights.sum()
    centroid = (points * weights[:, None]).sum(axis=0)
    centered = points - centroid
    covariance = np.einsum("n,ni,nj->ij", weights, centered, centered)
    evals = np.linalg.eigvalsh(covariance)

    return {
        "density": den,
        "magnitude": mag,
        "magnitude_normalized": mag_norm,
        "phase": np.angle(fft),
        "pair_histogram": hist,
        "moments": np.r_[centroid, evals],
    }


def descriptor_distance(a: dict[str, np.ndarray], b: dict[str, np.ndarray]) -> dict[str, float]:
    shared_weight = np.sqrt(
        a["magnitude_normalized"] * b["magnitude_normalized"]
    )
    threshold = np.quantile(shared_weight.ravel(), 0.65)
    shared_weight = np.where(shared_weight >= threshold, shared_weight, 0.0)
    shared_weight[(0, 0, 0)] = 0.0
    wrapped = np.angle(np.exp(1j * (a["phase"] - b["phase"])))

    return {
        "density_l2": float(np.linalg.norm(a["density"] - b["density"])),
        "amplitude": float(
            np.linalg.norm(
                a["magnitude_normalized"] - b["magnitude_normalized"]
            )
        ),
        "phase": float(
            math.sqrt(
                float((shared_weight * wrapped**2).sum())
                / (float(shared_weight.sum()) + 1e-12)
            )
        ),
        "pair_hist": float(
            np.linalg.norm(a["pair_histogram"] - b["pair_histogram"])
        ),
        "moments": float(np.linalg.norm(a["moments"] - b["moments"])),
    }


def chamfer(a: np.ndarray, b: np.ndarray) -> float:
    ta, tb = cKDTree(a), cKDTree(b)
    da, _ = tb.query(a, k=1)
    db, _ = ta.query(b, k=1)
    return float(0.5 * (da.mean() + db.mean()))


def split_representation(
    points: np.ndarray, rng: np.random.Generator, epsilon: float
) -> tuple[np.ndarray, np.ndarray]:
    direction = rng.normal(size=points.shape)
    direction /= np.linalg.norm(direction, axis=1, keepdims=True) + 1e-12
    children = np.vstack([points + epsilon * direction, points - epsilon * direction])
    weights = np.ones(len(children), dtype=np.float64) / len(children)
    return children, weights


def merge_representation(
    points: np.ndarray, rng: np.random.Generator, fraction: float
) -> tuple[np.ndarray, np.ndarray]:
    weights = np.ones(len(points), dtype=np.float64) / len(points)
    tree = cKDTree(points)
    alive = np.ones(len(points), dtype=bool)
    pairs: list[tuple[int, int]] = []
    target_pairs = int(len(points) * fraction / 2)

    for i in rng.permutation(len(points)):
        if not alive[i]:
            continue
        _, neighbors = tree.query(points[i], k=min(8, len(points)))
        for j in np.atleast_1d(neighbors)[1:]:
            j = int(j)
            if alive[j]:
                pairs.append((int(i), j))
                alive[i] = False
                alive[j] = False
                break
        if len(pairs) >= target_pairs:
            break

    used: set[int] = set()
    merged_points: list[np.ndarray] = []
    merged_weights: list[float] = []
    for i, j in pairs:
        weight = float(weights[i] + weights[j])
        merged_points.append((weights[i] * points[i] + weights[j] * points[j]) / weight)
        merged_weights.append(weight)
        used.update((i, j))
    for i in range(len(points)):
        if i not in used:
            merged_points.append(points[i])
            merged_weights.append(float(weights[i]))

    return np.asarray(merged_points), np.asarray(merged_weights)


def local_translation(points: np.ndarray, delta: float) -> np.ndarray:
    edited = points.copy()
    score = edited[:, 0] + 0.25 * edited[:, 2]
    mask = score >= np.quantile(score, 0.72)
    edited[mask, 1] += delta
    edited[mask, 2] += 0.25 * delta
    return edited


def rigid_rotation(points: np.ndarray, degrees: float) -> np.ndarray:
    edited = points.copy()
    center = edited.mean(axis=0)
    q = edited - center
    angle = np.deg2rad(degrees)
    c, s = np.cos(angle), np.sin(angle)
    rotation = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    return q @ rotation.T + center


def auc_positive_over_negative(positive: np.ndarray, negative: np.ndarray) -> float:
    values = np.concatenate([positive, negative])
    ranks = rankdata(values)
    n_pos = len(positive)
    n_neg = len(negative)
    rank_sum = float(ranks[:n_pos].sum())
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def run() -> dict:
    records: list[dict] = []
    for seed in range(8):
        for shape_name, points in make_shapes(seed).items():
            baseline = describe(points)
            rng = np.random.default_rng(1000 + seed)

            for epsilon in (0.008, 0.015, 0.025, 0.04):
                changed, weights = split_representation(points, rng, epsilon)
                records.append({
                    "seed": seed,
                    "shape": shape_name,
                    "kind": "resample_split",
                    "magnitude": epsilon,
                    "chamfer": chamfer(points, changed),
                    **descriptor_distance(baseline, describe(changed, weights)),
                })

            for fraction in (0.10, 0.20, 0.35):
                changed, weights = merge_representation(points, rng, fraction)
                records.append({
                    "seed": seed,
                    "shape": shape_name,
                    "kind": "resample_merge",
                    "magnitude": fraction,
                    "chamfer": chamfer(points, changed),
                    **descriptor_distance(baseline, describe(changed, weights)),
                })

            for delta in (0.015, 0.03, 0.06, 0.10, 0.16, 0.24):
                changed = local_translation(points, delta)
                records.append({
                    "seed": seed,
                    "shape": shape_name,
                    "kind": "edit_translate",
                    "magnitude": delta,
                    "chamfer": chamfer(points, changed),
                    **descriptor_distance(baseline, describe(changed)),
                })

            for degrees in (1, 2, 5, 10, 20, 30):
                changed = rigid_rotation(points, degrees)
                records.append({
                    "seed": seed,
                    "shape": shape_name,
                    "kind": "edit_rotate",
                    "magnitude": degrees,
                    "chamfer": chamfer(points, changed),
                    **descriptor_distance(baseline, describe(changed)),
                })

    def subset(kind: str, metric: str) -> np.ndarray:
        return np.asarray([r[metric] for r in records if r["kind"] == kind])

    summary: dict[str, dict] = {}
    for metric in METRICS:
        split = subset("resample_split", metric)
        merge = subset("resample_merge", metric)
        translation = subset("edit_translate", metric)
        rotation = subset("edit_rotate", metric)

        all_metric = np.asarray([r[metric] for r in records])
        all_chamfer = np.asarray([r["chamfer"] for r in records])
        rho = spearmanr(all_metric, all_chamfer).statistic

        summary[metric] = {
            "split_median": float(np.median(split)),
            "split_p95": float(np.quantile(split, 0.95)),
            "merge_median": float(np.median(merge)),
            "merge_p95": float(np.quantile(merge, 0.95)),
            "translation_median": float(np.median(translation)),
            "rotation_median": float(np.median(rotation)),
            "translation_vs_split_auc": auc_positive_over_negative(translation, split),
            "rotation_vs_split_auc": auc_positive_over_negative(rotation, split),
            "translation_vs_merge_auc": auc_positive_over_negative(translation, merge),
            "rotation_vs_merge_auc": auc_positive_over_negative(rotation, merge),
            "spearman_with_chamfer": None if np.isnan(rho) else float(rho),
        }

    return {
        "schemaVersion": 1,
        "experiment": "phase-invariants-v0",
        "purpose": "cheap falsification of global phase-derived geometry descriptor",
        "environment": {
            "python": sys.version,
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "configuration": {
            "seeds": 8,
            "shapes": ["wavy_plane", "sphere_cap", "corner", "helix"],
            "points_per_shape": 64,
            "grid_resolution": GRID_N,
            "gaussian_sigma": 0.095,
            "split_epsilons": [0.008, 0.015, 0.025, 0.04],
            "merge_fractions": [0.10, 0.20, 0.35],
            "translation_magnitudes": [0.015, 0.03, 0.06, 0.10, 0.16, 0.24],
            "rotation_degrees": [1, 2, 5, 10, 20, 30],
        },
        "record_count": len(records),
        "summary": summary,
        "interpretation": [
            "Phase is sensitive to real translation and rotation changes and is relatively stable to small split resampling.",
            "Phase is NOT uniquely superior: normalized density L2 performs similarly, while simple moments perfectly separate the tested translations from split/merge nuisance.",
            "Moments and pair-distance histograms fail by construction on rigid rotation around the centroid, while phase/density remain sensitive.",
            "Merge-style resampling is substantially harder for phase than split resampling.",
            "This probe does not justify a phase-based paper claim. The next probe must use local neighborhoods, approximately moment-preserving deformations, anisotropic covariance, opacity variation, and realistic split/merge operations.",
        ],
        "decision": "CONTINUE-NARROWLY: phase survives as a candidate but has not beaten simpler invariants.",
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research/results/probes/phase-invariants-v0.json"),
    )
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("experiment", "record_count", "decision")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
