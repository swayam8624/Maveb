#!/usr/bin/env python3
"""S1 dependency-certified heterogeneous minimal-work evaluation harness.

Consumes revision records with per-layer incremental/full work in native units plus an explicit
equivalence verdict. Produces per-layer ULR curves, sparse-change scaling diagnostics, hidden-global
work detection, and hard-gate status. It never mixes incomparable work units into one scalar.
"""
from __future__ import annotations
import argparse, csv, json, math, statistics, sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REQUIRED_LAYERS=(
 "observations","tsdfBlocksRead","tsdfBlocksWritten","meshCellsRegenerated",
 "gaussiansInspected","gaussiansUpdated","textureTexelsWritten",
 "gpuPublicationBytes","temporalPixelsInvalidated"
)

def finite_nonnegative(value:Any,name:str)->float:
    v=float(value)
    if not math.isfinite(v) or v<0: raise ValueError(f"{name} must be finite and non-negative")
    return v

def load_records(path:Path)->list[dict[str,Any]]:
    if path.suffix==".jsonl":
        rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    else:
        data=json.loads(path.read_text()); rows=data["revisions"] if isinstance(data,dict) else data
    if not rows: raise ValueError("evaluation requires at least one revision")
    return rows

def validate_record(row:dict[str,Any],index:int)->dict[str,Any]:
    changed=finite_nonnegative(row["changedFraction"],f"revision {index} changedFraction")
    if changed>1: raise ValueError("changedFraction must be <= 1")
    eq=row.get("equivalence")
    if not isinstance(eq,dict) or "pass" not in eq: raise ValueError("equivalence.pass is required")
    layers=row.get("layers")
    if not isinstance(layers,dict): raise ValueError("layers object is required")
    normalized={}
    for layer in REQUIRED_LAYERS:
        if layer not in layers: raise ValueError(f"revision {index} missing layer {layer}")
        item=layers[layer]
        inc=finite_nonnegative(item["incremental"],f"{layer}.incremental")
        full=finite_nonnegative(item["full"],f"{layer}.full")
        unit=str(item.get("unit","")).strip()
        if not unit: raise ValueError(f"{layer}.unit is required")
        if full==0 and inc>0: raise ValueError(f"{layer}: nonzero incremental work has zero full baseline")
        ratio=0.0 if full==0 else inc/full
        normalized[layer]={"incremental":inc,"full":full,"unit":unit,"ratio":ratio}
    return {
      "scene":str(row.get("scene","unknown")),
      "revision":str(row.get("revision",index)),
      "changedFraction":changed,
      "equivalence":{"pass":bool(eq["pass"]),"maxError":eq.get("maxError"),"contract":eq.get("contract","unspecified")},
      "layers":normalized
    }

def evaluate(rows:list[dict[str,Any]], sparse_threshold:float=0.05,
             global_ratio_threshold:float=0.80)->dict[str,Any]:
    records=[validate_record(row,i) for i,row in enumerate(rows)]
    by_layer=defaultdict(list)
    for record in records:
        for name,item in record["layers"].items():
            by_layer[name].append((record["changedFraction"],item["ratio"],item["unit"]))

    layer_summary={}
    hidden=[]
    for layer,points in by_layer.items():
        units={p[2] for p in points}
        if len(units)!=1: raise ValueError(f"{layer} changes work units across revisions")
        sparse=[ratio for changed,ratio,_ in points if 0<changed<=sparse_threshold]
        ordered=sorted((changed,ratio) for changed,ratio,_ in points)
        sparse_median=statistics.median(sparse) if sparse else None
        is_hidden=sparse_median is not None and sparse_median>=global_ratio_threshold
        if is_hidden: hidden.append(layer)
        # Spearman-like monotonicity without scipy: fraction of adjacent non-decreasing ratios.
        comparisons=[ordered[i+1][1]>=ordered[i][1]-1e-12 for i in range(len(ordered)-1)]
        monotonic=sum(comparisons)/len(comparisons) if comparisons else 1.0
        layer_summary[layer]={
          "unit":next(iter(units)),
          "minimumULR":min(p[1] for p in points),
          "maximumULR":max(p[1] for p in points),
          "sparseMedianULR":sparse_median,
          "monotonicWithChangedFraction":monotonic,
          "hiddenGlobalWork":is_hidden,
          "points":[{"changedFraction":c,"ulr":r} for c,r,_ in sorted(points)]
        }

    equivalence_failures=[
      {"scene":r["scene"],"revision":r["revision"],"contract":r["equivalence"]["contract"],
       "maxError":r["equivalence"]["maxError"]}
      for r in records if not r["equivalence"]["pass"]
    ]
    gates={
      "G1RecordsValid":True,
      "G2Equivalence":not equivalence_failures,
      "G3NoSparseHiddenGlobalLayers":not hidden,
      "G4AllRequiredLayersInstrumented":all(layer in by_layer for layer in REQUIRED_LAYERS),
      "G5SparseRegimeObserved":any(0<r["changedFraction"]<=sparse_threshold for r in records),
      "G6FullReferenceObserved":any(abs(r["changedFraction"]-1.0)<1e-12 for r in records),
    }
    return {
      "schemaVersion":1,
      "experiment":"s1-heterogeneous-minimal-work",
      "recordCount":len(records),
      "sparseThreshold":sparse_threshold,
      "globalRatioThreshold":global_ratio_threshold,
      "layers":layer_summary,
      "hiddenGlobalLayers":hidden,
      "equivalenceFailures":equivalence_failures,
      "gates":gates,
      "pass":all(gates.values()),
      "interpretation":(
        "PASS means this supplied experiment set satisfies instrumentation/equivalence/locality "
        "gates. It does not by itself establish novelty or publication readiness."
      )
    }

def synthetic(healthy:bool=True)->list[dict[str,Any]]:
    fractions=(0.001,0.005,0.01,0.05,0.10,0.25,1.0)
    fulls={
      "observations":100000,"tsdfBlocksRead":12000,"tsdfBlocksWritten":12000,
      "meshCellsRegenerated":900000,"gaussiansInspected":1000000,"gaussiansUpdated":1000000,
      "textureTexelsWritten":16_000_000,"gpuPublicationBytes":256_000_000,
      "temporalPixelsInvalidated":2_073_600,
    }
    units={
      "observations":"observations","tsdfBlocksRead":"blocks","tsdfBlocksWritten":"blocks",
      "meshCellsRegenerated":"cells","gaussiansInspected":"gaussians","gaussiansUpdated":"gaussians",
      "textureTexelsWritten":"texels","gpuPublicationBytes":"bytes","temporalPixelsInvalidated":"pixels"
    }
    rows=[]
    for i,f in enumerate(fractions):
        layers={}
        for layer,full in fulls.items():
            if f==1.0: ratio=1.0
            else:
                ratio=min(1.0,0.01+1.35*f)
                if layer in ("meshCellsRegenerated","gaussiansUpdated"): ratio=min(1.0,0.004+1.10*f)
                if not healthy and layer=="tsdfBlocksRead": ratio=1.0
            layers[layer]={"incremental":round(full*ratio,6),"full":full,"unit":units[layer]}
        rows.append({"scene":"synthetic-s1","revision":i,"changedFraction":f,
                     "equivalence":{"pass":True,"maxError":0.0,"contract":"exact-synthetic"},
                     "layers":layers})
    return rows

def write_csv(result:dict[str,Any],path:Path)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="") as handle:
        writer=csv.writer(handle); writer.writerow(["layer","unit","changed_fraction","ulr"])
        for layer,summary in result["layers"].items():
            for point in summary["points"]:
                writer.writerow([layer,summary["unit"],point["changedFraction"],point["ulr"]])

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",type=Path); ap.add_argument("--output",type=Path)
    ap.add_argument("--csv",type=Path); ap.add_argument("--synthetic",choices=("healthy","global-scan"))
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        good=evaluate(synthetic(True)); bad=evaluate(synthetic(False))
        if not good["pass"]: raise RuntimeError("healthy S1 fixture must pass")
        if bad["pass"] or "tsdfBlocksRead" not in bad["hiddenGlobalLayers"]:
            raise RuntimeError("global-scan fixture must expose hidden TSDF read work")
        if not (args.input or args.synthetic): return 0
    rows=synthetic(args.synthetic!="global-scan") if args.synthetic else load_records(args.input)
    result=evaluate(rows)
    text=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True); tmp=args.output.with_suffix(args.output.suffix+".tmp")
        tmp.write_text(text); tmp.replace(args.output)
    else: sys.stdout.write(text)
    if args.csv: write_csv(result,args.csv)
    return 0 if result["pass"] else 3

if __name__=="__main__": raise SystemExit(main())
