#!/usr/bin/env python3
"""Discover complete real MAVEB worlds and freeze a deterministic CBRC campaign.

Accepted input is never synthesized: a world is usable only when its latest
revision has matching immutable Gaussian and ownership sidecars.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import mmap
import os
import shutil

import cbrc_storage
import struct
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

GAUSSIAN_MAGIC = b"AETHGS\x00\x00"
OWNERSHIP_MAGIC = b"MVGOWNR\x00"
GAUSSIAN_HEADER_BYTES = 32
GAUSSIAN_RECORD_BYTES = 256
OWNERSHIP_HEADER_BYTES = 32


@dataclass(frozen=True)
class Candidate:
    archive: Path
    revision: int
    timestamp: int
    entities: dict[int, dict]
    gaussian_sidecar: Path
    ownership_sidecar: Path
    gaussian_count: int
    owners: tuple[int, ...]
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def latest_world(path: Path) -> tuple[int, int, dict[int, dict]]:
    payload = json.loads(path.read_text())
    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("world has no snapshots")
    latest = snapshots[-1]
    revision = int(latest["revision"])
    timestamp = int(latest["timestamp"])
    entities_raw = latest.get("entities")
    if revision <= 0 or timestamp <= 0 or not isinstance(entities_raw, list):
        raise ValueError("latest world snapshot is invalid")

    entities: dict[int, dict] = {}
    for entity in entities_raw:
        if not isinstance(entity, dict):
            raise ValueError("entity is not an object")
        entity_id = int(entity["id"])
        translation = entity.get("translation")
        if (
            entity_id <= 0
            or entity_id in entities
            or not isinstance(translation, list)
            or len(translation) != 3
            or not all(math.isfinite(float(v)) for v in translation)
        ):
            raise ValueError("entity identity/translation is invalid")
        entities[entity_id] = entity
    if not entities:
        raise ValueError("latest world snapshot has no entities")
    return revision, timestamp, entities


def read_gaussians(
    path: Path,
) -> tuple[int, tuple[float, float, float], tuple[float, float, float]]:
    size = path.stat().st_size
    if size < GAUSSIAN_HEADER_BYTES:
        raise ValueError("Gaussian sidecar header is invalid")

    with path.open("rb") as stream, mmap.mmap(
        stream.fileno(), 0, access=mmap.ACCESS_READ
    ) as data:
        if data[:8] != GAUSSIAN_MAGIC:
            raise ValueError("Gaussian sidecar header is invalid")
        major = struct.unpack_from("<H", data, 8)[0]
        stride = struct.unpack_from("<I", data, 12)[0]
        count = struct.unpack_from("<Q", data, 16)[0]
        degree = struct.unpack_from("<I", data, 24)[0]
        if major != 1 or stride != GAUSSIAN_RECORD_BYTES or count <= 0 or degree > 3:
            raise ValueError("Gaussian sidecar dimensions are invalid")
        if GAUSSIAN_HEADER_BYTES + count * stride != size:
            raise ValueError("Gaussian sidecar byte count is inconsistent")

        minimum = [float("inf")] * 3
        maximum = [float("-inf")] * 3
        for index in range(count):
            offset = GAUSSIAN_HEADER_BYTES + index * stride
            xyz = struct.unpack_from("<3f", data, offset)
            if not all(math.isfinite(v) and abs(v) <= 1.0e12 for v in xyz):
                raise ValueError("Gaussian sidecar contains a non-finite position")
            for axis, value in enumerate(xyz):
                minimum[axis] = min(minimum[axis], float(value))
                maximum[axis] = max(maximum[axis], float(value))

    return int(count), tuple(minimum), tuple(maximum)


def read_ownership(path: Path) -> tuple[int, ...]:
    data = path.read_bytes()
    if len(data) < OWNERSHIP_HEADER_BYTES or data[:8] != OWNERSHIP_MAGIC:
        raise ValueError("ownership sidecar header is invalid")
    version, header_bytes = struct.unpack_from("<II", data, 8)
    count = struct.unpack_from("<Q", data, 16)[0]
    reserved = struct.unpack_from("<Q", data, 24)[0]
    if version != 1 or header_bytes != OWNERSHIP_HEADER_BYTES or reserved != 0:
        raise ValueError("ownership sidecar header is invalid")
    if OWNERSHIP_HEADER_BYTES + count * 8 != len(data):
        raise ValueError("ownership sidecar byte count is inconsistent")
    return tuple(
        int(struct.unpack_from("<Q", data, OWNERSHIP_HEADER_BYTES + i * 8)[0])
        for i in range(count)
    )


def inspect_archive(path: Path) -> Candidate:
    revision, timestamp, entities = latest_world(path)
    gaussian = Path(str(path) + f".gaussians.r{revision}.bin")
    ownership = Path(str(path) + f".ownership.r{revision}.bin")
    if not gaussian.is_file():
        raise FileNotFoundError(f"missing Gaussian sidecar: {gaussian}")
    if not ownership.is_file():
        raise FileNotFoundError(f"missing ownership sidecar: {ownership}")

    count, minimum, maximum = read_gaussians(gaussian)
    owners = read_ownership(ownership)
    if len(owners) != count:
        raise ValueError("Gaussian/ownership sidecars disagree on cardinality")
    if not any(owner in entities for owner in owners):
        raise ValueError("no Gaussian is owned by a current entity")

    return Candidate(
        archive=path.resolve(),
        revision=revision,
        timestamp=timestamp,
        entities=entities,
        gaussian_sidecar=gaussian.resolve(),
        ownership_sidecar=ownership.resolve(),
        gaussian_count=count,
        owners=owners,
        minimum=minimum,
        maximum=maximum,
    )


def walk_worlds(root: Path, max_depth: int) -> Iterable[Path]:
    root = root.expanduser().resolve()
    if root.is_file():
        if root.name.endswith(".aetherworld"):
            yield root
        return
    if not root.is_dir():
        return

    root_depth = len(root.parts)
    skip = {".git", "node_modules", ".venv", ".venv-maveb", "build", "Library", ".Trash"}
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.parts) - root_depth
        dirs[:] = [d for d in dirs if d not in skip and depth < max_depth]
        for name in files:
            if name.endswith(".aetherworld"):
                yield current_path / name


def discover(roots: Iterable[Path], max_depth: int) -> tuple[list[Candidate], list[dict]]:
    accepted: list[Candidate] = []
    rejected: list[dict] = []
    seen: set[Path] = set()
    for root in roots:
        for path in walk_worlds(root, max_depth):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                accepted.append(inspect_archive(resolved))
            except Exception as exc:
                rejected.append({"archive": str(resolved), "reason": str(exc)})

    accepted.sort(
        key=lambda c: (
            -len({o for o in c.owners if o in c.entities}),
            -c.gaussian_count,
            str(c.archive),
        )
    )
    return accepted, rejected


def choose_entity(candidate: Candidate) -> tuple[int, int]:
    counts = Counter(owner for owner in candidate.owners if owner in candidate.entities)
    target_fraction = 0.05
    minimum = max(8, candidate.gaussian_count // 10000)
    eligible = [(entity, count) for entity, count in counts.items() if count >= minimum]
    if not eligible:
        eligible = list(counts.items())
    entity, count = min(
        eligible,
        key=lambda item: (
            abs(item[1] / candidate.gaussian_count - target_fraction),
            item[1] / candidate.gaussian_count > 0.35,
            item[1],
            item[0],
        ),
    )
    return int(entity), int(count)


def bounds(candidate: Candidate) -> tuple[list[float], list[float], list[float]]:
    mins = list(candidate.minimum)
    maxs = list(candidate.maximum)
    center = [(mins[i] + maxs[i]) * 0.5 for i in range(3)]
    return mins, maxs, center


def scene_scale(candidate: Candidate) -> float:
    mins, maxs, _ = bounds(candidate)
    diagonal = math.sqrt(sum((maxs[i] - mins[i]) ** 2 for i in range(3)))
    return max(diagonal, 0.10)


def derive_camera(candidate: Candidate) -> dict:
    mins, maxs, center = bounds(candidate)
    extent = [max((maxs[i] - mins[i]) * 0.5, 1e-4) for i in range(3)]
    width, height = 1280, 720
    focal_x = focal_y = 900.0
    distance = max(
        extent[2] + 0.05,
        extent[2] + focal_x * extent[0] / (0.40 * width),
        extent[2] + focal_y * extent[1] / (0.40 * height),
    )
    distance = max(distance * 1.20, 0.25)
    near = max(1e-3, distance - 1.5 * extent[2])
    far = max(near + 1.0, distance + 2.5 * extent[2] + 1.0)
    tx, ty, tz = -center[0], -center[1], distance - center[2]

    return {
        "width": width,
        "height": height,
        "focal_x": focal_x,
        "focal_y": focal_y,
        "center_x": width / 2.0,
        "center_y": height / 2.0,
        "near": near,
        "far": far,
        "camera_world_position": [center[0], center[1], center[2] - distance],
        "world_to_camera": [
            1.0, 0.0, 0.0, tx,
            0.0, 1.0, 0.0, ty,
            0.0, 0.0, 1.0, tz,
            0.0, 0.0, 0.0, 1.0,
        ],
    }


def copy_before_state(
    candidate: Candidate,
    case_dir: Path,
    *,
    materialize: bool = True,
    require_clone: bool = False,
) -> Path:
    """Return the independent case archive path.

    Broad/reviewer campaigns freeze this path lazily and materialize it only
    immediately before execution. Legacy callers can still request eager
    materialization. When eager, copy-on-write clones are preferred.
    """

    case_dir.mkdir(parents=True, exist_ok=True)
    archive = (case_dir / candidate.archive.name).resolve()
    if not materialize:
        return archive

    cbrc_storage.copy_storage_efficient(
        candidate.archive,
        archive,
        require_clone=require_clone,
    )
    cbrc_storage.copy_storage_efficient(
        candidate.gaussian_sidecar,
        Path(str(archive) + f".gaussians.r{candidate.revision}.bin"),
        require_clone=require_clone,
    )
    cbrc_storage.copy_storage_efficient(
        candidate.ownership_sidecar,
        Path(str(archive) + f".ownership.r{candidate.revision}.bin"),
        require_clone=require_clone,
    )
    return archive


def build_campaign(
    candidates: list[Candidate],
    output_dir: Path,
    epsilon: float,
    work_cost_model: Path | None,
) -> tuple[dict, dict]:
    regimes = [
        ("local-low-01", "low", 0.010, epsilon, True),
        ("local-low-02", "low", 0.025, epsilon, True),
        ("medium-01", "medium", 0.075, epsilon, True),
        ("high-01", "high", 0.200, epsilon, True),
        ("adversarial-full", "adversarial", 0.400, max(epsilon * 0.5, 1e-6), False),
    ]

    cases = []
    frozen_inputs = []
    inputs = output_dir / "inputs"
    for index, (suffix, coupling, delta_fraction, case_epsilon, history_stable) in enumerate(regimes):
        candidate = candidates[min(index * len(candidates) // len(regimes), len(candidates) - 1)]
        entity_id, owned_count = choose_entity(candidate)
        translation = [float(v) for v in candidate.entities[entity_id]["translation"]]
        mins, maxs, _ = bounds(candidate)
        axis = 0 if (maxs[0] - mins[0]) >= (maxs[1] - mins[1]) else 1
        scale = scene_scale(candidate)
        target = list(translation)
        target[axis] += delta_fraction * scale

        case_id = f"real-{suffix}"
        archive_copy = copy_before_state(candidate, inputs / case_id)
        case = {
            "id": case_id,
            "scene_id": candidate.archive.stem,
            "epsilon": case_epsilon,
            "coupling_regime": coupling,
            "edit_class": "gaussian",
            "revision": {
                "archive": str(archive_copy),
                "entity": entity_id,
                "target": target,
                "timestamp": candidate.timestamp + (index + 1) * 1_000_000,
                "history_stable": history_stable,
                "history_weight": 0.9,
                "camera": derive_camera(candidate),
            },
        }
        if work_cost_model is not None:
            case["work_cost_model"] = str(work_cost_model.resolve())
        cases.append(case)
        frozen_inputs.append(
            {
                "case_id": case_id,
                "source_archive": str(candidate.archive),
                "source_revision": candidate.revision,
                "source_archive_sha256": sha256(candidate.archive),
                "source_gaussian_sha256": sha256(candidate.gaussian_sidecar),
                "source_ownership_sha256": sha256(candidate.ownership_sidecar),
                "gaussian_count": candidate.gaussian_count,
                "selected_entity": entity_id,
                "selected_entity_gaussians": owned_count,
                "selected_fraction": owned_count / candidate.gaussian_count,
                "scene_scale": scale,
                "delta_fraction": delta_fraction,
            }
        )

    campaign = {
        "schemaVersion": 1,
        "minimum_revisions": 5,
        "minimum_scenes": min(len({c["scene_id"] for c in cases}), 3),
        "require_local_success": True,
        "require_full_fallback": True,
        "require_high_coupling": True,
        "cases": cases,
        "freeze_note": (
            "Frozen before final execution from immutable real starting revisions. "
            "Do not retune epsilon, cameras, entities, or transforms after reading results."
        ),
    }
    provenance = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-real-campaign-freeze",
        "generator": "benchmarks/scripts/cbrc_prepare_real_campaign.py",
        "candidate_count": len(candidates),
        "frozen_inputs": frozen_inputs,
        "work_cost_model": (
            None
            if work_cost_model is None
            else {"path": str(work_cost_model.resolve()), "sha256": sha256(work_cost_model)}
        ),
    }
    return campaign, provenance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, action="append", default=[])
    parser.add_argument("--search-root", type=Path, action="append", default=[])
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--epsilon", type=float, default=1.0 / 255.0)
    parser.add_argument("--work-cost-model", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.max_depth < 0 or args.epsilon <= 0 or not math.isfinite(args.epsilon):
        parser.error("max-depth must be non-negative and epsilon must be finite/positive")
    if args.work_cost_model is not None and not args.work_cost_model.is_file():
        parser.error(f"work cost model not found: {args.work_cost_model}")

    roots = [p.expanduser() for p in args.search_root]
    if not args.archive and not roots:
        roots = [
            Path.cwd(),
            Path.home() / "Desktop",
            Path.home() / "Documents",
            Path.home() / "Downloads",
        ]

    accepted: list[Candidate] = []
    rejected: list[dict] = []
    seen: set[Path] = set()
    for raw in args.archive:
        path = raw.expanduser().resolve()
        try:
            candidate = inspect_archive(path)
            if candidate.archive not in seen:
                seen.add(candidate.archive)
                accepted.append(candidate)
        except Exception as exc:
            rejected.append({"archive": str(path), "reason": str(exc)})

    discovered, discovery_rejected = discover(roots, args.max_depth)
    for candidate in discovered:
        if candidate.archive not in seen:
            seen.add(candidate.archive)
            accepted.append(candidate)
    rejected.extend(discovery_rejected)
    accepted.sort(
        key=lambda c: (
            -len({o for o in c.owners if o in c.entities}),
            -c.gaussian_count,
            str(c.archive),
        )
    )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schemaVersion": 1,
        "artifact": "maveb-cbrc-real-asset-discovery",
        "accepted": [
            {
                "archive": str(c.archive),
                "revision": c.revision,
                "entities": len(c.entities),
                "owned_entities": len({o for o in c.owners if o in c.entities}),
                "gaussians": c.gaussian_count,
                "gaussian_sidecar": str(c.gaussian_sidecar),
                "ownership_sidecar": str(c.ownership_sidecar),
            }
            for c in accepted
        ],
        "rejected": rejected,
    }
    (output_dir / "asset-discovery.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )

    if not accepted:
        print(
            "No complete real MAVEB persistent world was found.\n"
            "Required for latest revision R:\n"
            "  WORLD.aetherworld\n"
            "  WORLD.aetherworld.gaussians.rR.bin\n"
            "  WORLD.aetherworld.ownership.rR.bin\n"
            f"Discovery report: {output_dir / 'asset-discovery.json'}",
            file=sys.stderr,
        )
        return 4

    campaign, provenance = build_campaign(
        accepted, output_dir, args.epsilon, args.work_cost_model
    )
    manifest = output_dir / "campaign.json"
    manifest.write_text(json.dumps(campaign, indent=2, sort_keys=True) + "\n")
    provenance["campaign_sha256"] = sha256(manifest)
    (output_dir / "campaign-freeze.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
