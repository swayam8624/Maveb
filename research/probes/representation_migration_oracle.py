#!/usr/bin/env python3
"""Exact small-scene oracle for adaptive region representation assignment.

Input contains per-region measured candidates (for example TSDF, mesh, Gaussian,
hybrid residual) with quality loss and resource costs. The oracle chooses one
candidate per region under hard memory/render/update budgets and minimizes
weighted total loss.

This is intentionally an *offline upper-bound* tool. It exists to falsify the
representation-migration idea cheaply: if the best mixed assignment cannot beat
the best fixed representation on measured data, online migration is not worth
implementing.

The solver is exact branch-and-bound for small controlled scenes. It refuses
large combinatorial inputs rather than silently switching to an approximate
heuristic.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_COMBINATIONS = 5_000_000

@dataclass(frozen=True)
class Candidate:
    representation: str
    quality_loss: float
    memory_bytes: int
    render_ms: float
    update_ms: float

@dataclass(frozen=True)
class Region:
    id: str
    weight: float
    candidates: tuple[Candidate, ...]

def parse_input(data: dict[str, Any]) -> tuple[list[Region], dict[str, float]]:
    budgets = data.get("budgets")
    if not isinstance(budgets, dict):
        raise ValueError("budgets object is required")
    for key in ("memoryBytes", "renderMs", "updateMs"):
        if key not in budgets:
            raise ValueError(f"budget {key} is required")

    regions: list[Region] = []
    raw_regions = data.get("regions")
    if not isinstance(raw_regions, list) or not raw_regions:
        raise ValueError("regions must be a non-empty list")

    combinations = 1
    for raw in raw_regions:
        candidates: list[Candidate] = []
        for item in raw.get("candidates", []):
            candidate = Candidate(
                representation=str(item["representation"]),
                quality_loss=float(item["qualityLoss"]),
                memory_bytes=int(item["memoryBytes"]),
                render_ms=float(item["renderMs"]),
                update_ms=float(item["updateMs"]),
            )
            if (not math.isfinite(candidate.quality_loss) or candidate.quality_loss < 0 or
                candidate.memory_bytes < 0 or not math.isfinite(candidate.render_ms) or
                candidate.render_ms < 0 or not math.isfinite(candidate.update_ms) or
                candidate.update_ms < 0):
                raise ValueError("candidate metrics must be finite and non-negative")
            candidates.append(candidate)
        if not candidates:
            raise ValueError(f"region {raw.get('id')} has no candidates")
        combinations *= len(candidates)
        if combinations > MAX_COMBINATIONS:
            raise ValueError(
                f"exact oracle would require {combinations} combinations; "
                f"reduce controlled-scene regions/candidates below {MAX_COMBINATIONS}"
            )
        regions.append(
            Region(
                id=str(raw["id"]),
                weight=float(raw.get("weight", 1.0)),
                candidates=tuple(candidates),
            )
        )
    return regions, {
        "memoryBytes": float(budgets["memoryBytes"]),
        "renderMs": float(budgets["renderMs"]),
        "updateMs": float(budgets["updateMs"]),
    }

def solve(regions: list[Region], budgets: dict[str, float]) -> dict[str, Any] | None:
    order = sorted(
        range(len(regions)),
        key=lambda i: max(c.quality_loss for c in regions[i].candidates)
        - min(c.quality_loss for c in regions[i].candidates),
        reverse=True,
    )
    ordered = [regions[i] for i in order]

    optimistic_suffix = [0.0] * (len(ordered) + 1)
    for i in range(len(ordered) - 1, -1, -1):
        optimistic_suffix[i] = optimistic_suffix[i + 1] + (
            ordered[i].weight * min(c.quality_loss for c in ordered[i].candidates)
        )

    best_loss = math.inf
    best_assignment: list[tuple[str, Candidate]] | None = None
    visited = 0
    feasible = 0

    def dfs(
        index: int,
        loss: float,
        memory: int,
        render: float,
        update: float,
        assignment: list[tuple[str, Candidate]],
    ) -> None:
        nonlocal best_loss, best_assignment, visited, feasible
        visited += 1

        if memory > budgets["memoryBytes"] or render > budgets["renderMs"] or update > budgets["updateMs"]:
            return
        if loss + optimistic_suffix[index] >= best_loss:
            return
        if index == len(ordered):
            feasible += 1
            best_loss = loss
            best_assignment = assignment.copy()
            return

        region = ordered[index]
        candidates = sorted(
            region.candidates,
            key=lambda c: (region.weight * c.quality_loss, c.memory_bytes, c.render_ms, c.update_ms),
        )
        for candidate in candidates:
            assignment.append((region.id, candidate))
            dfs(
                index + 1,
                loss + region.weight * candidate.quality_loss,
                memory + candidate.memory_bytes,
                render + candidate.render_ms,
                update + candidate.update_ms,
                assignment,
            )
            assignment.pop()

    dfs(0, 0.0, 0, 0.0, 0.0, [])
    if best_assignment is None:
        return None

    by_id = {region_id: candidate for region_id, candidate in best_assignment}
    ordered_assignment = [
        {
            "region": region.id,
            "representation": by_id[region.id].representation,
            "qualityLoss": by_id[region.id].quality_loss,
            "memoryBytes": by_id[region.id].memory_bytes,
            "renderMs": by_id[region.id].render_ms,
            "updateMs": by_id[region.id].update_ms,
        }
        for region in regions
    ]
    return {
        "weightedQualityLoss": best_loss,
        "memoryBytes": sum(x["memoryBytes"] for x in ordered_assignment),
        "renderMs": sum(x["renderMs"] for x in ordered_assignment),
        "updateMs": sum(x["updateMs"] for x in ordered_assignment),
        "assignment": ordered_assignment,
        "searchVisitedNodes": visited,
        "searchFeasibleLeaves": feasible,
    }

def fixed_baselines(regions: list[Region], budgets: dict[str, float]) -> list[dict[str, Any]]:
    names = sorted(set.intersection(*[
        {candidate.representation for candidate in region.candidates}
        for region in regions
    ]))
    results = []
    for name in names:
        chosen = []
        for region in regions:
            candidate = next(c for c in region.candidates if c.representation == name)
            chosen.append((region, candidate))
        memory = sum(c.memory_bytes for _, c in chosen)
        render = sum(c.render_ms for _, c in chosen)
        update = sum(c.update_ms for _, c in chosen)
        loss = sum(region.weight * c.quality_loss for region, c in chosen)
        results.append({
            "representation": name,
            "feasible": memory <= budgets["memoryBytes"] and render <= budgets["renderMs"] and update <= budgets["updateMs"],
            "weightedQualityLoss": loss,
            "memoryBytes": memory,
            "renderMs": render,
            "updateMs": update,
        })
    return results

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    regions, budgets = parse_input(data)
    oracle = solve(regions, budgets)
    fixed = fixed_baselines(regions, budgets)
    feasible_fixed = [x for x in fixed if x["feasible"]]
    best_fixed = min(feasible_fixed, key=lambda x: x["weightedQualityLoss"]) if feasible_fixed else None

    result = {
        "schemaVersion": 1,
        "experiment": "representation-migration-offline-oracle",
        "input": str(args.input),
        "budgets": budgets,
        "regionCount": len(regions),
        "oracle": oracle,
        "fixedBaselines": fixed,
        "bestFixedFeasible": best_fixed,
        "oracleImprovesBestFixed": (
            oracle is not None and best_fixed is not None and
            oracle["weightedQualityLoss"] < best_fixed["weightedQualityLoss"]
        ),
        "decisionRule": (
            "Kill adaptive representation migration if the mixed oracle does not materially "
            "dominate the best fixed feasible representation across held-out measured scenes."
        ),
    }

    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
