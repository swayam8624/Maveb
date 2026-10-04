#!/usr/bin/env python3
"""Exact small-scene temporal representation-assignment oracle for MAVEB.

The oracle is deliberately expensive and intended only for research falsification. It enumerates
joint per-region representation assignments at each revision, applies explicit memory/render/update
budgets, and uses dynamic programming over revisions with representation-migration cost.

If this oracle cannot Pareto/objective-dominate the best fixed per-region assignment on measured
tuples, online representation migration should be killed before implementation.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Option:
    error: float
    memory_mb: float
    render_ms: float
    update_ms: float


@dataclass(frozen=True)
class Budget:
    memory_mb: float
    render_ms: float
    update_ms: float


def validate_number(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return number


def parse_problem(data: dict[str, Any]) -> tuple[list[str], list[str], list[dict[str, dict[str, Option]]], list[Budget], dict[tuple[str, str], float], dict[str, float]]:
    regions = list(data["regions"])
    representations = list(data["representations"])
    revisions_raw = list(data["revisions"])
    budgets_raw = list(data["budgets"])
    weights = {
        "quality": validate_number(data.get("weights", {}).get("quality", 1.0), "quality weight"),
        "update": validate_number(data.get("weights", {}).get("update", 0.0), "update weight"),
        "migration": validate_number(data.get("weights", {}).get("migration", 1.0), "migration weight"),
    }
    if not regions or not representations or len(revisions_raw) != len(budgets_raw):
        raise ValueError("problem requires regions, representations, and one budget per revision")
    if len(set(regions)) != len(regions) or len(set(representations)) != len(representations):
        raise ValueError("region and representation names must be unique")

    revisions: list[dict[str, dict[str, Option]]] = []
    for t, revision in enumerate(revisions_raw):
        parsed_revision: dict[str, dict[str, Option]] = {}
        for region in regions:
            if region not in revision:
                raise ValueError(f"revision {t} missing region {region}")
            parsed_revision[region] = {}
            for representation in representations:
                raw = revision[region].get(representation)
                if raw is None:
                    continue
                parsed_revision[region][representation] = Option(
                    error=validate_number(raw["error"], f"{region}/{representation}/error"),
                    memory_mb=validate_number(raw["memory_mb"], f"{region}/{representation}/memory"),
                    render_ms=validate_number(raw["render_ms"], f"{region}/{representation}/render"),
                    update_ms=validate_number(raw["update_ms"], f"{region}/{representation}/update"),
                )
            if not parsed_revision[region]:
                raise ValueError(f"revision {t} region {region} has no representation option")
        revisions.append(parsed_revision)

    budgets = [
        Budget(
            memory_mb=validate_number(raw["memory_mb"], "memory budget"),
            render_ms=validate_number(raw["render_ms"], "render budget"),
            update_ms=validate_number(raw["update_ms"], "update budget"),
        )
        for raw in budgets_raw
    ]

    migration: dict[tuple[str, str], float] = {}
    migration_raw = data.get("migration_ms", {})
    for source in representations:
        for target in representations:
            if source == target:
                migration[(source, target)] = 0.0
            else:
                value = migration_raw.get(source, {}).get(target)
                if value is None:
                    raise ValueError(f"missing migration cost {source}->{target}")
                migration[(source, target)] = validate_number(
                    value, f"migration {source}->{target}"
                )
    return regions, representations, revisions, budgets, migration, weights


def enumerate_states(
    regions: list[str],
    representations: list[str],
    revision: dict[str, dict[str, Option]],
    budget: Budget,
) -> list[tuple[str, ...]]:
    states: list[tuple[str, ...]] = []
    for assignment in itertools.product(representations, repeat=len(regions)):
        options: list[Option] = []
        valid = True
        for region, representation in zip(regions, assignment, strict=True):
            option = revision[region].get(representation)
            if option is None:
                valid = False
                break
            options.append(option)
        if not valid:
            continue
        if sum(o.memory_mb for o in options) > budget.memory_mb + 1e-12:
            continue
        if sum(o.render_ms for o in options) > budget.render_ms + 1e-12:
            continue
        # Base update work must fit before any migration is considered.
        if sum(o.update_ms for o in options) > budget.update_ms + 1e-12:
            continue
        states.append(assignment)
    return states


def state_quality_cost(
    regions: list[str],
    revision: dict[str, dict[str, Option]],
    state: tuple[str, ...],
    weights: dict[str, float],
) -> float:
    return weights["quality"] * sum(
        revision[region][representation].error
        for region, representation in zip(regions, state, strict=True)
    )


def transition_update_ms(
    regions: list[str],
    revision: dict[str, dict[str, Option]],
    previous: tuple[str, ...] | None,
    current: tuple[str, ...],
    migration: dict[tuple[str, str], float],
) -> tuple[float, float]:
    update_ms = sum(
        revision[region][representation].update_ms
        for region, representation in zip(regions, current, strict=True)
    )
    migration_ms = 0.0
    if previous is not None:
        migration_ms = sum(
            migration[(source, target)]
            for source, target in zip(previous, current, strict=True)
        )
    return update_ms + migration_ms, migration_ms


def solve_exact(data: dict[str, Any]) -> dict[str, Any]:
    regions, representations, revisions, budgets, migration, weights = parse_problem(data)
    feasible = [
        enumerate_states(regions, representations, revision, budget)
        for revision, budget in zip(revisions, budgets, strict=True)
    ]
    if any(not states for states in feasible):
        raise ValueError("at least one revision has no feasible representation assignment")

    costs: dict[tuple[str, ...], float] = {}
    paths: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    work: dict[tuple[str, ...], list[dict[str, float]]] = {}

    for state in feasible[0]:
        update_total, migration_ms = transition_update_ms(
            regions, revisions[0], None, state, migration
        )
        if update_total > budgets[0].update_ms + 1e-12:
            continue
        cost = state_quality_cost(regions, revisions[0], state, weights)
        cost += weights["update"] * update_total
        costs[state] = cost
        paths[state] = [state]
        work[state] = [{"update_ms": update_total, "migration_ms": migration_ms}]
    if not costs:
        raise ValueError("initial revision has no update-budget-feasible assignment")

    for t in range(1, len(revisions)):
        next_costs: dict[tuple[str, ...], float] = {}
        next_paths: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
        next_work: dict[tuple[str, ...], list[dict[str, float]]] = {}
        for current in feasible[t]:
            best: tuple[float, tuple[str, ...], float, float] | None = None
            for previous, previous_cost in costs.items():
                update_total, migration_ms = transition_update_ms(
                    regions, revisions[t], previous, current, migration
                )
                if update_total > budgets[t].update_ms + 1e-12:
                    continue
                candidate = (
                    previous_cost
                    + state_quality_cost(regions, revisions[t], current, weights)
                    + weights["update"] * update_total
                    + weights["migration"] * migration_ms,
                    previous,
                    update_total,
                    migration_ms,
                )
                if best is None or candidate[0] < best[0] - 1e-12:
                    best = candidate
            if best is None:
                continue
            cost, previous, update_total, migration_ms = best
            next_costs[current] = cost
            next_paths[current] = paths[previous] + [current]
            next_work[current] = work[previous] + [
                {"update_ms": update_total, "migration_ms": migration_ms}
            ]
        costs, paths, work = next_costs, next_paths, next_work
        if not costs:
            raise ValueError(f"revision {t} has no transition-feasible assignment")

    best_state = min(costs, key=costs.get)
    adaptive_path = paths[best_state]
    adaptive_cost = costs[best_state]

    fixed_candidates: list[tuple[float, tuple[str, ...], list[dict[str, float]]]] = []
    for state in itertools.product(representations, repeat=len(regions)):
        total_cost = 0.0
        fixed_work: list[dict[str, float]] = []
        valid = True
        for t, (revision, budget) in enumerate(zip(revisions, budgets, strict=True)):
            if state not in feasible[t]:
                valid = False
                break
            update_total, migration_ms = transition_update_ms(
                regions, revision, None if t == 0 else state, state, migration
            )
            if update_total > budget.update_ms + 1e-12:
                valid = False
                break
            total_cost += state_quality_cost(regions, revision, state, weights)
            total_cost += weights["update"] * update_total
            fixed_work.append({"update_ms": update_total, "migration_ms": migration_ms})
        if valid:
            fixed_candidates.append((total_cost, state, fixed_work))
    if not fixed_candidates:
        raise ValueError("no fixed per-region assignment is feasible across all revisions")
    fixed_cost, fixed_state, fixed_work = min(fixed_candidates, key=lambda item: item[0])

    def encode_path(path: list[tuple[str, ...]]) -> list[dict[str, str]]:
        return [
            {region: representation for region, representation in zip(regions, state, strict=True)}
            for state in path
        ]

    return {
        "schemaVersion": 1,
        "status": "exact-small-scene-temporal-oracle",
        "regions": regions,
        "representations": representations,
        "revisionCount": len(revisions),
        "adaptive": {
            "objective": adaptive_cost,
            "assignments": encode_path(adaptive_path),
            "work": work[best_state],
        },
        "bestFixedPerRegion": {
            "objective": fixed_cost,
            "assignment": encode_path([fixed_state])[0],
            "work": fixed_work,
        },
        "adaptiveObjectiveImprovementFraction": (
            (fixed_cost - adaptive_cost) / fixed_cost if fixed_cost > 0.0 else 0.0
        ),
        "adaptiveBeatsFixed": adaptive_cost < fixed_cost - 1e-12,
        "note": (
            "This is an oracle over supplied measured/synthetic tuples. It is not evidence that an "
            "online policy can predict the winning representation."
        ),
    }


def synthetic_fixture() -> dict[str, Any]:
    # Region wall becomes geometrically stable; object becomes view-dependent; doorway oscillates
    # between high update pressure and stability. The fixture is designed to exercise migration,
    # not to represent measured MAVEB performance.
    regions = ["wall", "object", "doorway"]
    representations = ["mesh", "gaussian", "hybrid"]
    revisions = []
    for t in range(5):
        revisions.append(
            {
                "wall": {
                    "mesh": {"error": 0.20 - 0.02*t, "memory_mb": 18, "render_ms": 0.20, "update_ms": 0.25},
                    "gaussian": {"error": 0.12 + 0.02*t, "memory_mb": 38, "render_ms": 0.34, "update_ms": 0.55},
                    "hybrid": {"error": 0.10, "memory_mb": 45, "render_ms": 0.42, "update_ms": 0.65},
                },
                "object": {
                    "mesh": {"error": 0.38 + 0.03*t, "memory_mb": 10, "render_ms": 0.12, "update_ms": 0.22},
                    "gaussian": {"error": 0.09, "memory_mb": 24, "render_ms": 0.23, "update_ms": 0.35},
                    "hybrid": {"error": 0.08, "memory_mb": 31, "render_ms": 0.29, "update_ms": 0.45},
                },
                "doorway": {
                    "mesh": {"error": 0.16 if t >= 2 else 0.32, "memory_mb": 12, "render_ms": 0.14, "update_ms": 0.18},
                    "gaussian": {"error": 0.11 if t < 2 else 0.20, "memory_mb": 22, "render_ms": 0.21, "update_ms": 0.30},
                    "hybrid": {"error": 0.09, "memory_mb": 29, "render_ms": 0.27, "update_ms": 0.42},
                },
            }
        )
    return {
        "regions": regions,
        "representations": representations,
        "revisions": revisions,
        "budgets": [
            {"memory_mb": 90, "render_ms": 0.9, "update_ms": 2.0}
            for _ in revisions
        ],
        "migration_ms": {
            "mesh": {"gaussian": 0.35, "hybrid": 0.28},
            "gaussian": {"mesh": 0.30, "hybrid": 0.22},
            "hybrid": {"mesh": 0.20, "gaussian": 0.18},
        },
        "weights": {"quality": 10.0, "update": 0.05, "migration": 0.05},
    }


def self_test() -> None:
    result = solve_exact(synthetic_fixture())
    if not result["adaptiveBeatsFixed"]:
        raise RuntimeError("synthetic fixture must exercise an adaptive advantage")
    if len(result["adaptive"]["assignments"]) != 5:
        raise RuntimeError("oracle path length mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
    if args.synthetic:
        problem = synthetic_fixture()
    elif args.input:
        problem = json.loads(args.input.read_text())
    elif args.self_test:
        return 0
    else:
        parser.error("provide --input, --synthetic, or --self-test")

    result = solve_exact(problem)
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
