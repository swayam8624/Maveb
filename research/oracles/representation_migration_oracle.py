#!/usr/bin/env python3
"""Offline oracle for temporal representation migration experiments.

Input is a JSON file containing per-region, per-revision measurements for candidate
representations (for example tsdf, mesh, gaussian, hybrid residual). The oracle
does not invent metrics; it solves a measured cost/quality allocation problem.

A representation assignment is feasible only if every measurement is present.
Objective weights are explicit and output keeps all raw components.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from typing import Any


def finite(v, name):
    x=float(v)
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def score(candidate: dict[str, Any], weights: dict[str, float]) -> float:
    total=0.0
    for key, weight in weights.items():
        total += finite(weight, f"weights.{key}") * finite(candidate[key], key)
    return total


def solve(payload: dict[str, Any]) -> dict[str, Any]:
    weights=payload["objectiveWeights"]
    regions=payload["regions"]
    assignments=[]
    totals={key:0.0 for key in weights}
    migration_cost_total=0.0
    previous={}

    for revision in sorted({r["revision"] for r in regions}):
        current={}
        for region in [r for r in regions if r["revision"]==revision]:
            rid=str(region["regionId"])
            best=None
            for candidate in region["candidates"]:
                value=score(candidate,weights)
                previous_rep=previous.get(rid)
                migration=0.0
                if previous_rep is not None and previous_rep != candidate["representation"]:
                    migration=finite(candidate.get("migrationCost",0.0),"migrationCost")
                    value += finite(weights.get("migrationCost",0.0),"weights.migrationCost") * migration
                choice=(value,candidate,migration)
                if best is None or choice[0] < best[0]:
                    best=choice
            if best is None:
                raise ValueError(f"region {rid} revision {revision} has no candidates")
            value,candidate,migration=best
            current[rid]=candidate["representation"]
            migration_cost_total+=migration
            for key in totals:
                if key=="migrationCost":
                    continue
                totals[key]+=finite(candidate.get(key,0.0),key)
            assignments.append({
                "revision":revision,
                "regionId":rid,
                "representation":candidate["representation"],
                "objective":value,
                "migrationCost":migration,
                "raw":candidate,
            })
        previous=current

    return {
        "schemaVersion":1,
        "assignmentCount":len(assignments),
        "assignments":assignments,
        "totals":{**totals,"migrationCost":migration_cost_total},
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("input",type=Path)
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    result=solve(json.loads(args.input.read_text()))
    text=json.dumps(result,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text)
    else:
        print(text,end="")


if __name__=="__main__":
    main()
