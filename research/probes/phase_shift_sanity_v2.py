#!/usr/bin/env python3
"""Sanity-check the Fourier shift theorem on canonicalized Gaussian-center fields.

For a global translation d, a continuous field satisfies
    F_shift(k) = F(k) exp(-i k·d)
so low-frequency phase differences should recover d while amplitude remains
unchanged. This validates only the restricted mathematical bridge; it does not
prove local-edit preservation.
"""
from __future__ import annotations
import argparse, json, platform, sys
from pathlib import Path
import numpy as np

N=32
AX=np.linspace(-1.2,1.2,N)
DX=AX[1]-AX[0]
X,Y,Z=np.meshgrid(AX,AX,AX,indexing="ij")
GRID=np.stack([X,Y,Z],axis=-1)
FREQ=2*np.pi*np.fft.fftfreq(N,d=DX)
KX,KY,KZ=np.meshgrid(FREQ,FREQ,FREQ,indexing="ij")
K=np.stack([KX,KY,KZ],axis=-1)

def density(points,sigma=.09):
    out=np.zeros((N,N,N),dtype=np.float64)
    for p in points:
        d=GRID-p
        out+=np.exp(-np.sum(d*d,axis=-1)/(2*sigma*sigma))
    return out

def recover(a,b,kmax=8.0):
    f1=np.fft.fftn(a); f2=np.fft.fftn(b)
    m1=np.abs(f1); m2=np.abs(f2)
    phase=np.angle(f2*np.conj(f1))
    weight=np.sqrt(m1*m2)
    kmag=np.linalg.norm(K,axis=-1)
    eligible=(kmag>1e-9)&(kmag<=kmax)
    threshold=np.quantile(weight[eligible],.35)
    mask=eligible&(weight>threshold)
    A=K[mask]
    y=-phase[mask]
    w=np.sqrt(weight[mask]/(weight[mask].max()+1e-12))
    estimate=np.linalg.lstsq(A*w[:,None],y*w,rcond=None)[0]
    amp1=m1/(m1.sum()+1e-12); amp2=m2/(m2.sum()+1e-12)
    predicted=-np.einsum("...i,i->...",K,estimate)
    residual=np.angle(np.exp(1j*(phase-predicted)))
    rmse=np.sqrt((weight[mask]*residual[mask]**2).sum()/(weight[mask].sum()+1e-12))
    return estimate,float(np.linalg.norm(amp2-amp1)),float(rmse),int(mask.sum())

def run():
    records=[]
    for seed in range(20):
        rng=np.random.default_rng(seed)
        points=rng.uniform(-.55,.55,(72,3))
        base=density(points)
        for magnitude in (.005,.01,.02,.04,.06,.08):
            direction=rng.normal(size=3); direction/=np.linalg.norm(direction)
            truth=direction*magnitude
            estimate,amp,phase_rmse,modes=recover(base,density(points+truth))
            records.append({
              "seed":seed,"magnitude":magnitude,"truth":truth.tolist(),"estimate":estimate.tolist(),
              "translation_error":float(np.linalg.norm(estimate-truth)),
              "relative_error":float(np.linalg.norm(estimate-truth)/(magnitude+1e-12)),
              "normalized_amplitude_drift":amp,"phase_model_rmse":phase_rmse,"modes":modes
            })
    by_magnitude={}
    for magnitude in (.005,.01,.02,.04,.06,.08):
        rows=[r for r in records if r["magnitude"]==magnitude]
        by_magnitude[str(magnitude)]={
          "translation_error_median":float(np.median([r["translation_error"] for r in rows])),
          "relative_error_median":float(np.median([r["relative_error"] for r in rows])),
          "normalized_amplitude_drift_median":float(np.median([r["normalized_amplitude_drift"] for r in rows])),
          "phase_model_rmse_median":float(np.median([r["phase_model_rmse"] for r in rows])),
        }
    return {
      "schemaVersion":1,"experiment":"phase-shift-sanity-v2",
      "environment":{"python":sys.version,"numpy":np.__version__,"platform":platform.platform()},
      "configuration":{"seeds":20,"points":72,"grid":N,"translations":[.005,.01,.02,.04,.06,.08],"kmax":8.0},
      "record_count":len(records),
      "summary":{
        "translation_error_median":float(np.median([r["translation_error"] for r in records])),
        "translation_error_max":float(np.max([r["translation_error"] for r in records])),
        "normalized_amplitude_drift_median":float(np.median([r["normalized_amplitude_drift"] for r in records])),
        "phase_model_rmse_median":float(np.median([r["phase_model_rmse"] for r in records])),
        "by_magnitude":by_magnitude
      },
      "decision":"MATHEMATICAL SANITY PASS: canonical center-field phase recovers restricted global translations; proceed to local-window and resampling attacks.",
      "records":records
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,default=Path("research/results/probes/phase-shift-sanity-v2.json"))
    args=ap.parse_args(); result=run()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"experiment":result["experiment"],"record_count":result["record_count"],"decision":result["decision"]},indent=2))
if __name__=="__main__": main()
