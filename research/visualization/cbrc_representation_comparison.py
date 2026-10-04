#!/usr/bin/env python3
"""Create a cautious SfM-seeded vs trained-3DGS validation comparison.

The sources are not matched scene-for-scene, so this artifact reports validation
coverage and safety/work summaries side-by-side; it does not claim one
representation is faster or better than the other.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text())


def svg(data: dict, path: Path):
    sfm=data["sfmSeeded"]; trained=data["trained3dgs"]
    def fmt(v):
        return "n/a" if v is None else f"{v:.3g}"
    path.parent.mkdir(parents=True,exist_ok=True)
    body=f"""<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="760" viewBox="0 0 1500 760">
<rect width="1500" height="760" rx="28" fill="#F7F8FA"/>
<style>.t{{font:700 36px sans-serif;fill:#10131A}}.h{{font:700 26px sans-serif;fill:#10131A}}.b{{font:20px sans-serif;fill:#475467}}.n{{font:700 32px monospace;fill:#7C5CFC}}.card{{fill:white;stroke:#D8DEE9;stroke-width:2}}</style>
<text x="70" y="70" class="t">F12 — CBRC across Gaussian representations</text>
<text x="70" y="112" class="b">Coverage validation only — sources are not matched scenes, so no cross-representation performance ranking is implied.</text>
<rect x="80" y="170" width="630" height="500" rx="24" class="card"/>
<text x="120" y="225" class="h">RGB/SfM-seeded Gaussians</text>
<text x="120" y="280" class="n">{sfm['rows']} cases · {sfm['scenes']} scenes</text>
<text x="120" y="335" class="b">certified local cases: {sfm['certifiedLocalCases']}</text>
<text x="120" y="375" class="b">FULL fallbacks: {sfm['fullFallbackCases']}</text>
<text x="120" y="415" class="b">certificate violations: {sfm['certificateViolations']}</text>
<text x="120" y="455" class="b">median work/FULL: {fmt(sfm['medianSelectedWorkRatioFull'])}</text>
<text x="120" y="495" class="b">work unit: {', '.join(sfm['workCostUnits'])}</text>
<text x="120" y="560" class="b">isotropic Gaussian field seeded from real COLMAP SfM points</text>
<rect x="790" y="170" width="630" height="500" rx="24" class="card"/>
<text x="830" y="225" class="h">Public trained 3DGS</text>
<text x="830" y="280" class="n">{trained['rows']} cases · {trained['scenes']} scenes</text>
<text x="830" y="335" class="b">certified local cases: {trained['certifiedLocalCases']}</text>
<text x="830" y="375" class="b">FULL fallbacks: {trained['fullFallbackCases']}</text>
<text x="830" y="415" class="b">certificate violations: {trained['certificateViolations']}</text>
<text x="830" y="455" class="b">median work/FULL: {fmt(trained['medianSelectedWorkRatioFull'])}</text>
<text x="830" y="495" class="b">work unit: {', '.join(trained['workCostUnits'])}</text>
<text x="830" y="560" class="b">trained anisotropic Gaussians; SH, opacity, scale and rotation preserved</text>
<rect x="420" y="615" width="660" height="60" rx="18" fill="#18C6D9"/>
<text x="750" y="654" text-anchor="middle" style="font:700 20px sans-serif;fill:white">same certificate/oracle contract: actual ≤ bound ≤ ε</text>
</svg>"""
    path.write_text(body)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--sfm-answer",type=Path,required=True)
    parser.add_argument("--trained-answer",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    sfm=load(args.sfm_answer); trained=load(args.trained_answer)
    result={
        "schemaVersion":1,
        "artifact":"maveb-cbrc-representation-validation-comparison",
        "sfmSeeded":sfm,
        "trained3dgs":trained,
        "crossRepresentationPerformanceClaim":False,
        "interpretation":"Both representations are evaluated under the same CBRC/oracle safety contract, but the scene sources are not matched; use this as representation-coverage evidence, not a speed/quality ranking.",
    }
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"F12_representation_comparison.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    svg(result,args.output_dir/"F12_representation_comparison.svg")
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
