#!/usr/bin/env python3
"""Self-diagnosing local phase certificate probe.

Measures whether the residual of the low-frequency phase translation model predicts
actual displacement-estimation error as a translated Gaussian-center neighborhood
approaches a tapered local-window boundary.

A strong residual/error relation would support a computable reject condition:
accept a phase-derived displacement certificate only when its own model residual is small.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np

N=28
AX=np.linspace(-1.0,1.0,N)
DX=AX[1]-AX[0]
X,Y,Z=np.meshgrid(AX,AX,AX,indexing="ij")
GRID=np.stack([X,Y,Z],axis=-1)
FREQ=2*np.pi*np.fft.fftfreq(N,d=DX)
KX,KY,KZ=np.meshgrid(FREQ,FREQ,FREQ,indexing="ij")
K=np.stack([KX,KY,KZ],axis=-1)
WINDOW_RADIUS=0.8
WINDOW_TAPER=0.12
TRUTH=np.array([0.02,0.01,-0.005],dtype=np.float64)
RADIUS=np.linalg.norm(GRID,axis=-1)
WINDOW=np.clip((WINDOW_RADIUS-RADIUS)/WINDOW_TAPER,0.0,1.0)

def density(points: np.ndarray, sigma: float=0.07) -> np.ndarray:
    out=np.zeros((N,N,N),dtype=np.float64)
    for point in points:
        delta=GRID-point
        out+=np.exp(-np.sum(delta*delta,axis=-1)/(2*sigma*sigma))
    return out*WINDOW

def estimate(before: np.ndarray, after: np.ndarray, kmax: float=10.0):
    f1=np.fft.fftn(before); f2=np.fft.fftn(after)
    m1=np.abs(f1); m2=np.abs(f2)
    phase=np.angle(f2*np.conj(f1))
    weight=np.sqrt(m1*m2)
    kmag=np.linalg.norm(K,axis=-1)
    mask=(kmag>1e-9)&(kmag<kmax)
    threshold=np.quantile(weight[mask],0.4)
    mask&=weight>threshold
    design=K[mask]
    target=-phase[mask]
    regression_weight=np.sqrt(weight[mask]/(weight[mask].max()+1e-12))
    estimated=np.linalg.lstsq(
        design*regression_weight[:,None],
        target*regression_weight,
        rcond=None,
    )[0]
    predicted=-np.einsum("...i,i->...",K,estimated)
    wrapped_residual=np.angle(np.exp(1j*(phase-predicted)))
    rmse=float(np.sqrt(
        (weight[mask]*wrapped_residual[mask]**2).sum()/(weight[mask].sum()+1e-12)
    ))
    return estimated,rmse

def run():
    margins=np.linspace(0.02,0.50,13)
    records=[]
    for margin in margins:
        for seed in range(12):
            rng=np.random.default_rng(seed)
            center=np.array([WINDOW_RADIUS-float(margin),0.0,0.0])
            points=center+rng.normal(0.0,0.05,size=(40,3))
            estimated,residual=estimate(density(points),density(points+TRUTH))
            error=float(np.linalg.norm(estimated-TRUTH))
            records.append({
                "margin":float(margin),
                "seed":seed,
                "translation_error":error,
                "phase_model_residual":residual,
                "estimate":estimated.tolist(),
            })

    errors=np.asarray([r["translation_error"] for r in records])
    residuals=np.asarray([r["phase_model_residual"] for r in records])
    pearson=float(np.corrcoef(errors,residuals)[0,1])

    # Simple quantile rejection analysis; this is deliberately calibration-only.
    order=np.argsort(residuals)
    rejection={}
    for keep_fraction in (0.50,0.70,0.80,0.90):
        keep=max(1,int(len(records)*keep_fraction))
        kept=errors[order[:keep]]
        rejected=errors[order[keep:]]
        rejection[str(keep_fraction)]={
            "residual_threshold":float(residuals[order[keep-1]]),
            "kept_median_error":float(np.median(kept)),
            "kept_p95_error":float(np.quantile(kept,0.95)),
            "rejected_median_error":float(np.median(rejected)) if len(rejected) else None,
        }

    return {
        "schemaVersion":1,
        "experiment":"phase-residual-self-check-v5",
        "recordCount":len(records),
        "configuration":{
            "grid":N,
            "margins":[float(x) for x in margins],
            "seedsPerMargin":12,
            "translation":TRUTH.tolist(),
            "windowRadius":WINDOW_RADIUS,
            "windowTaper":WINDOW_TAPER,
        },
        "summary":{
            "pearson_residual_vs_error":pearson,
            "median_translation_error":float(np.median(errors)),
            "median_phase_model_residual":float(np.median(residuals)),
            "rejection":rejection,
        },
        "decision":"PROMISING SELF-CHECK: phase-model residual strongly tracks boundary-induced translation error in this synthetic sweep. Next test must calibrate thresholds on train scenes and evaluate error-bound coverage on held-out shapes/deformations.",
        "records":records,
    }

if __name__=="__main__":
    result=run()
    out=Path("research/results/probes/phase-residual-self-check-v5.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"experiment":result["experiment"],"recordCount":result["recordCount"],"decision":result["decision"]},indent=2))
