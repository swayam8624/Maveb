#!/usr/bin/env python3
"""Monte Carlo sanity check for the Gaussian tail locality certificate."""
from __future__ import annotations
import argparse, json, platform, sys
from pathlib import Path
import numpy as np

def random_covariance(rng, smin=0.02, smax=0.08):
    q,_=np.linalg.qr(rng.normal(size=(3,3)))
    if np.linalg.det(q)<0: q[:,0]*=-1
    s=np.exp(rng.uniform(np.log(smin),np.log(smax),3))
    return q@np.diag(s*s)@q.T

def face_bounds(mu,cov,alpha,lo,hi):
    out=[]
    for axis in range(3):
        dl=mu[axis]-lo[axis]
        du=hi[axis]-mu[axis]
        out.append(alpha if dl<=0 else alpha*np.exp(-0.5*dl*dl/cov[axis,axis]))
        out.append(alpha if du<=0 else alpha*np.exp(-0.5*du*du/cov[axis,axis]))
    return np.asarray(out)

def field(points,mus,covs,alphas):
    out=np.zeros(len(points))
    for mu,cov,alpha in zip(mus,covs,alphas):
        d=points-mu
        inv=np.linalg.inv(cov)
        q=np.sum((d@inv)*d,axis=1)
        out += alpha*np.exp(-0.5*q)
    return out

def sample_outside(rng,n,lo,hi,span=0.35):
    chunks=[]
    total=0
    while total<n:
        pts=rng.uniform(lo-span,hi+span,(max(4096,n),3))
        pts=pts[np.any((pts<lo)|(pts>hi),axis=1)]
        chunks.append(pts); total+=len(pts)
    return np.concatenate(chunks)[:n]

def trial(seed,margin,n_gauss=40,n_samples=40000,move=0.02):
    rng=np.random.default_rng(seed)
    lo=np.array([-0.5,-0.5,-0.5]); hi=-lo
    mus=rng.uniform(lo+margin,hi-margin,(n_gauss,3))
    covs=np.stack([random_covariance(rng) for _ in range(n_gauss)])
    alphas=rng.uniform(0.15,0.85,n_gauss)
    directions=rng.normal(size=mus.shape)
    directions/=np.linalg.norm(directions,axis=1,keepdims=True)+1e-12
    mus2=np.clip(mus+move*directions,lo+1e-5,hi-1e-5)
    covs2=[]
    for cov in covs:
        values,vectors=np.linalg.eigh(cov)
        values*=np.exp(rng.normal(0,0.12,3))
        covs2.append(vectors@np.diag(values)@vectors.T)
    covs2=np.stack(covs2)
    alphas2=np.clip(alphas*np.exp(rng.normal(0,0.08,n_gauss)),0.01,0.99)
    face_sum=np.zeros(6)
    for mu,cov,alpha in zip(mus,covs,alphas):
        face_sum += face_bounds(mu,cov,alpha,lo,hi)
    for mu,cov,alpha in zip(mus2,covs2,alphas2):
        face_sum += face_bounds(mu,cov,alpha,lo,hi)
    bound=float(face_sum.max())
    points=sample_outside(rng,n_samples,lo,hi)
    actual=np.abs(field(points,mus,covs,alphas)-field(points,mus2,covs2,alphas2))
    return {"bound":bound,"sampledMax":float(actual.max()),
            "sampledP999":float(np.quantile(actual,0.999)),
            "boundToSampledMax":float(bound/(actual.max()+1e-30))}

def run():
    records=[]
    for margin in (0.05,0.10,0.15,0.20,0.25):
        for seed in range(5):
            records.append({"margin":margin,"seed":seed,**trial(seed,margin)})
    summary={}
    for margin in (0.05,0.10,0.15,0.20,0.25):
        rows=[r for r in records if r["margin"]==margin]
        summary[str(margin)]={
            "boundMedian":float(np.median([r["bound"] for r in rows])),
            "sampledMaxMedian":float(np.median([r["sampledMax"] for r in rows])),
            "boundToSampledMaxMedian":float(np.median([r["boundToSampledMax"] for r in rows])),
            "sampledViolations":sum(r["sampledMax"]>r["bound"]*(1+1e-12) for r in rows)
        }
    return {"schemaVersion":1,"experiment":"gaussian-tail-locality-certificate-v0",
            "environment":{"python":sys.version,"numpy":np.__version__,"platform":platform.platform()},
            "configuration":{"gaussians":40,"outsideSamplesPerTrial":40000,"seeds":5,
                             "margins":[0.05,0.10,0.15,0.20,0.25]},
            "summary":summary,"records":records}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,default=Path("research/results/probes/gaussian-tail-locality-certificate-v0.json"))
    args=ap.parse_args(); result=run()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result["summary"],indent=2))
if __name__=="__main__": main()
