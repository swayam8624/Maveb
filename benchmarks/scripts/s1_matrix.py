#!/usr/bin/env python3
"""Freeze the S1 experimental matrix before full runs."""
from __future__ import annotations
import argparse,json
from pathlib import Path

DEFAULT_FRACTIONS=[0.001,0.0025,0.005,0.01,0.02,0.05,0.10,0.25,0.50,1.0]
DEFAULT_SEEDS=[17,41,73,101,149]
DEFAULT_SCALES=["small","medium","large"]
DEFAULT_CHANGE_TYPES=["addition","removal","rearrangement","geometry","appearance"]

def build()->dict:
    cells=[]
    for scale in DEFAULT_SCALES:
      for change in DEFAULT_CHANGE_TYPES:
       for fraction in DEFAULT_FRACTIONS:
        for seed in DEFAULT_SEEDS:
         cells.append({"sceneScale":scale,"changeType":change,"changedFraction":fraction,"seed":seed})
    return {
      "schemaVersion":1,"experiment":"s1-full-matrix-v1",
      "frozenFactors":{
        "changedFractions":DEFAULT_FRACTIONS,"seeds":DEFAULT_SEEDS,
        "sceneScales":DEFAULT_SCALES,"changeTypes":DEFAULT_CHANGE_TYPES
      },
      "cellCount":len(cells),"cells":cells,
      "requiredOutputs":[
        "per-layer incremental/full native-unit counters",
        "full-reference equivalence verdict and error",
        "wall time CPU/GPU where available",
        "peak memory and transfer bytes",
        "scene/revision provenance"
      ],
      "rule":"No factor may be silently dropped after seeing outcomes; blocked cells remain recorded."
    }

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path); ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args(); result=build()
    if a.self_test:
      expected=len(DEFAULT_SCALES)*len(DEFAULT_CHANGE_TYPES)*len(DEFAULT_FRACTIONS)*len(DEFAULT_SEEDS)
      if result["cellCount"]!=expected or expected!=750: raise RuntimeError("S1 matrix cardinality changed")
      if 1.0 not in DEFAULT_FRACTIONS or min(DEFAULT_FRACTIONS)>0.001: raise RuntimeError("S1 matrix lost full/sparse anchors")
      if not a.output: return 0
    text=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if a.output:
      a.output.parent.mkdir(parents=True,exist_ok=True); tmp=a.output.with_suffix(a.output.suffix+".tmp"); tmp.write_text(text); tmp.replace(a.output)
    else: print(text,end="")
    return 0
if __name__=="__main__": raise SystemExit(main())
