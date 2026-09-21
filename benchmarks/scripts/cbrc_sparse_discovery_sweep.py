#!/usr/bin/env python3
"""Sweep scan-vs-index Gaussian candidate discovery over scale/locality regimes."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from pathlib import Path


def run(binary: Path, gaussians: int, dirty: float, repeats: int) -> dict:
    process = subprocess.run(
        [
            str(binary),
            "--gaussians",
            str(gaussians),
            "--gaussians-per-cell",
            "8",
            "--dirty-fraction",
            repr(dirty),
            "--cell-size",
            "0.25",
            "--repeats",
            str(repeats),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-3000:])
    return json.loads(process.stdout)


def svg(rows: list[dict], path: Path) -> None:
    width, height = 1100, 680
    left, top, right, bottom = 100, 70, 50, 90
    pw, ph = width-left-right, height-top-bottom
    max_n = max(int(r["gaussians"]) for r in rows)
    max_ms = max(float(r["scanMeanMs"]) for r in rows) or 1.0
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#F7F8FA"/>',
        '<text x="60" y="42" font-family="sans-serif" font-size="26" font-weight="700">F11 — sparse candidate discovery scaling</text>',
        f'<line x1="{left}" y1="{top+ph}" x2="{left+pw}" y2="{top+ph}" stroke="#10131A" stroke-width="2"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+ph}" stroke="#10131A" stroke-width="2"/>',
    ]
    def sx(n: int) -> float:
        return left + math.log10(max(n,1))/math.log10(max_n) * pw
    def sy(ms: float) -> float:
        return top + ph - min(ms/max_ms,1.0)*ph
    for dirty in sorted({float(r["dirtyFraction"]) for r in rows}):
        subset=sorted((r for r in rows if float(r["dirtyFraction"])==dirty),key=lambda r:int(r["gaussians"]))
        scan=" ".join(f"{sx(int(r['gaussians'])):.1f},{sy(float(r['scanMeanMs'])):.1f}" for r in subset)
        indexed=" ".join(f"{sx(int(r['gaussians'])):.1f},{sy(float(r['indexedMeanMs'])):.1f}" for r in subset)
        pieces.append(f'<polyline points="{scan}" fill="none" stroke="#F04438" stroke-width="2" opacity="0.45"/>')
        pieces.append(f'<polyline points="{indexed}" fill="none" stroke="#18C6D9" stroke-width="3" opacity="0.8"/>')
    pieces += [
        f'<text x="{left+pw/2}" y="{height-25}" text-anchor="middle" font-family="sans-serif" font-size="16">Gaussian count (log scale)</text>',
        f'<text transform="translate(28 {top+ph/2}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="16">mean selection latency (ms)</text>',
        '<text x="790" y="55" font-family="sans-serif" font-size="14" fill="#F04438">full scan</text>',
        '<text x="900" y="55" font-family="sans-serif" font-size="14" fill="#18C6D9">indexed</text>',
        '</svg>',
    ]
    path.write_text("".join(pieces))


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--binary",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--repeats",type=int,default=9)
    parser.add_argument("--gaussians",default="10000,100000,500000,1000000")
    parser.add_argument("--dirty-fractions",default="0.001,0.005,0.01,0.05,0.1")
    args=parser.parse_args()
    counts=[int(v) for v in args.gaussians.split(",") if v]
    dirty=[float(v) for v in args.dirty_fractions.split(",") if v]
    if args.repeats < 1 or not counts or not dirty:
        parser.error("non-empty sweep and positive repeats required")
    args.output_dir.mkdir(parents=True,exist_ok=True)
    rows=[]
    for count in counts:
        for fraction in dirty:
            result=run(args.binary,count,fraction,args.repeats)
            result["inspectionRatio"]=result["indexedInspections"]/result["scanInspections"]
            result["latencyRatio"]=result["indexedMeanMs"]/max(result["scanMeanMs"],1e-15)
            rows.append(result)
    (args.output_dir/"sparse-discovery.jsonl").write_text(
        "".join(json.dumps(r,sort_keys=True)+"\n" for r in rows)
    )
    fields=[
        "gaussians","dirtyFraction","selectedGaussians","scanInspections","indexedInspections",
        "inspectionRatio","scanMeanMs","indexedMeanMs","latencyRatio","indexBuildMs","repeats"
    ]
    with (args.output_dir/"sparse-discovery.csv").open("w",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    svg(rows,args.output_dir/"F11_sparse_discovery.svg")
    summary={
        "schemaVersion":1,
        "cases":len(rows),
        "exactSelectionAgreement":all(bool(r["exactSelectionAgreement"]) for r in rows),
        "minimumInspectionRatio":min(float(r["inspectionRatio"]) for r in rows),
        "medianInspectionRatio":sorted(float(r["inspectionRatio"]) for r in rows)[len(rows)//2],
        "minimumLatencyRatio":min(float(r["latencyRatio"]) for r in rows),
        "maximumGaussians":max(counts),
    }
    (args.output_dir/"sparse-discovery-summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0 if summary["exactSelectionAgreement"] else 5


if __name__=="__main__":
    raise SystemExit(main())
