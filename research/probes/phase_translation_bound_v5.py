#!/usr/bin/env python3
"""Numerically verify the restricted weighted phase-translation error bound.

This does not establish a 3DGS editing contribution. It only checks the linear
algebra used by research/theory/phase_translation_certificate.md under its own
coherent-translation and bounded-phase-noise assumptions.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np

def trial(rng, modes=24, epsilon=0.01):
    K=rng.normal(size=(modes,3))
    K/=np.linalg.norm(K,axis=1,keepdims=True)+1e-12
    radii=rng.uniform(.5,4.0,size=(modes,1))
    A=K*radii
    weights=rng.uniform(.2,1.0,size=modes)
    Wsqrt=np.sqrt(weights)

    truth=rng.uniform(-.05,.05,size=3)
    clean=-A@truth
    noise=rng.uniform(-epsilon,epsilon,size=modes)
    measured=clean+noise

    Aw=A*Wsqrt[:,None]
    yw=measured*Wsqrt
    estimate=np.linalg.lstsq(Aw,-yw,rcond=None)[0]

    error=float(np.linalg.norm(estimate-truth))
    singular=np.linalg.svd(Aw,compute_uv=False)
    sigma_min=float(singular[-1])
    weighted_noise=float(np.linalg.norm(Wsqrt*noise))
    exact_noise_bound=weighted_noise/sigma_min
    infinity_bound=float(epsilon*np.sqrt(weights.sum())/sigma_min)
    return {
      "error":error,
      "sigmaMin":sigma_min,
      "weightedNoiseNorm":weighted_noise,
      "exactNoiseBound":exact_noise_bound,
      "infinityAssumptionBound":infinity_bound,
      "exactBoundHolds":error<=exact_noise_bound+1e-12,
      "infinityBoundHolds":error<=infinity_bound+1e-12
    }

def run():
    rng=np.random.default_rng(42)
    rows=[]
    for epsilon in (1e-4,1e-3,1e-2,5e-2):
        for _ in range(250):
            row=trial(rng,epsilon=epsilon)
            row["epsilon"]=epsilon
            rows.append(row)
    return {
      "schemaVersion":1,
      "experiment":"phase-translation-bound-v5",
      "trials":len(rows),
      "allExactBoundsHold":all(r["exactBoundHolds"] for r in rows),
      "allInfinityBoundsHold":all(r["infinityBoundHolds"] for r in rows),
      "maximumErrorToExactBoundRatio":max(r["error"]/r["exactNoiseBound"] for r in rows if r["exactNoiseBound"]>0),
      "maximumErrorToInfinityBoundRatio":max(r["error"]/r["infinityAssumptionBound"] for r in rows if r["infinityAssumptionBound"]>0),
      "decision":"LINEAR-ALGEBRA SANITY PASS ONLY: the conditional weighted-LS bound behaves as derived. The hard research problem is justifying coherent support and a phase-error envelope under real Gaussian resampling/editing.",
      "records":rows
    }

if __name__=="__main__":
    result=run()
    out=Path("research/results/probes/phase-translation-bound-v5.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ("experiment","trials","allExactBoundsHold","allInfinityBoundsHold","maximumErrorToExactBoundRatio","decision")},indent=2))
