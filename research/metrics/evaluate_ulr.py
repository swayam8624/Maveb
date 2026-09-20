#!/usr/bin/env python3
"""Validate and summarize MAVEB Update Locality Ratio evidence.

ULR never invents cross-layer primitive equivalence. The evaluator reports:
  * one ratio per counter using identical full/incremental units;
  * end-to-end latency ratio;
  * byte ratios by named domain;
  * eligibility based on explicit required correctness gates.

Input is JSON. See research/config/ulr-fixture.json.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

def nonnegative_number(value: Any, field: str) -> float:
    result=float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return result

def ratio(incremental: float, full: float) -> float | None:
    if full == 0:
        return 0.0 if incremental == 0 else None
    return incremental/full

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args=parser.parse_args()

    data=json.loads(args.input.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1:
        raise ValueError("ULR evidence schemaVersion must be 1")

    changed=nonnegative_number(data["changedFraction"], "changedFraction")
    if changed > 1:
        raise ValueError("changedFraction must be in [0,1]")

    gates=data.get("correctnessGates", [])
    if not isinstance(gates,list):
        raise ValueError("correctnessGates must be a list")
    required=[g for g in gates if bool(g.get("required",True))]
    failed=[str(g.get("name","unnamed")) for g in required if not bool(g.get("passed",False))]
    eligible=not failed

    layers={}
    raw_layers=data.get("layers",{})
    if not isinstance(raw_layers,dict):
        raise ValueError("layers must be an object")
    for layer_name,counters in raw_layers.items():
        if not isinstance(counters,dict):
            raise ValueError(f"layer {layer_name} must be an object")
        layer={}
        for counter_name,pair in counters.items():
            if not isinstance(pair,dict):
                raise ValueError(f"{layer_name}.{counter_name} must contain full/incremental")
            full=nonnegative_number(pair["full"],f"{layer_name}.{counter_name}.full")
            inc=nonnegative_number(pair["incremental"],f"{layer_name}.{counter_name}.incremental")
            layer[counter_name]={"full":full,"incremental":inc,"ratio":ratio(inc,full)}
        layers[layer_name]=layer

    timing=data.get("timingMs",{})
    full_ms=nonnegative_number(timing["full"],"timingMs.full")
    inc_ms=nonnegative_number(timing["incremental"],"timingMs.incremental")

    byte_ratios={}
    for domain,pair in data.get("byteDomains",{}).items():
        full=nonnegative_number(pair["full"],f"byteDomains.{domain}.full")
        inc=nonnegative_number(pair["incremental"],f"byteDomains.{domain}.incremental")
        byte_ratios[domain]={"full":full,"incremental":inc,"ratio":ratio(inc,full)}

    result={
      "schemaVersion":1,
      "experiment":"update-locality-ratio",
      "sourceEvidence":str(args.input),
      "repo":data.get("repo"),
      "branch":data.get("branch"),
      "sha":data.get("sha"),
      "scene":data.get("scene"),
      "revision":data.get("revision"),
      "changedFraction":changed,
      "eligibleForLocalityClaim":eligible,
      "failedRequiredCorrectnessGates":failed,
      "layerRatios":layers,
      "latency":{"fullMs":full_ms,"incrementalMs":inc_ms,"ratio":ratio(inc_ms,full_ms)},
      "byteDomains":byte_ratios,
      "peakMemoryBytes":data.get("peakMemoryBytes"),
      "note":"Ratios above 1 are retained; they are negative evidence, not clipped."
    }

    encoded=json.dumps(result,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encoded,encoding="utf-8")
    print(encoded,end="")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
