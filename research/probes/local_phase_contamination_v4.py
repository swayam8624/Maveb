#!/usr/bin/env python3
"""Local canonical phase displacement probe with resampling and partial-motion contamination.

Tests whether low-frequency phase of an equal-kernel center field can recover local
translation under:
  * split/merge representation nuisance;
  * partial stationary contamination inside a neighborhood.

Important: this probe explicitly attacks the assumption that a phase-derived
translation estimate can certify the maximum geometric motion of every point.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

N=28
EXTENT=1.2
AX=np.linspace(-EXTENT,EXTENT,N)
DX=AX[1]-AX[0]
X,Y,Z=np.meshgrid(AX,AX,AX,indexing="ij")
GRID=np.stack([X,Y,Z],axis=-1)
FREQ=2*np.pi*np.fft.fftfreq(N,d=DX)
KX,KY,KZ=np.meshgrid(FREQ,FREQ,FREQ,indexing="ij")
K=np.stack([KX,KY,KZ],axis=-1)

def density(points,sigma=.09,weights=None):
    if weights is None:
        weights=np.ones(len(points),dtype=np.float64)/len(points)
    out=np.zeros((N,N,N),dtype=np.float64)
    for p,w in zip(points,weights):
        d=GRID-p
        out+=w*np.exp(-np.sum(d*d,axis=-1)/(2*sigma*sigma))
    return out

def phase_shift_estimate(a,b,kmax=7.0):
    f1=np.fft.fftn(a); f2=np.fft.fftn(b)
    m1=np.abs(f1); m2=np.abs(f2)
    phase=np.angle(f2*np.conj(f1))
    weight=np.sqrt(m1*m2)
    kmag=np.linalg.norm(K,axis=-1)
    eligible=(kmag>1e-9)&(kmag<=kmax)
    threshold=np.quantile(weight[eligible],.4)
    mask=eligible&(weight>=threshold)
    A=K[mask]
    y=-phase[mask]
    w=np.sqrt(weight[mask]/(weight[mask].max()+1e-12))
    estimate=np.linalg.lstsq(A*w[:,None],y*w,rcond=None)[0]
    predicted=-np.einsum("...i,i->...",K,estimate)
    residual=np.angle(np.exp(1j*(phase-predicted)))
    rmse=np.sqrt((weight[mask]*residual[mask]**2).sum()/(weight[mask].sum()+1e-12))
    coherence=np.abs((weight[mask]*np.exp(1j*residual[mask])).sum())/(weight[mask].sum()+1e-12)
    return estimate,float(rmse),float(coherence)

def base_points(seed,n=64):
    rng=np.random.default_rng(seed)
    xy=rng.uniform(-.5,.5,(n,2))
    z=.06*np.sin(2.0*xy[:,0])+rng.normal(0,.01,n)
    return np.c_[xy,z]

def split(points,rng,epsilon):
    d=rng.normal(size=points.shape)
    d/=np.linalg.norm(d,axis=1,keepdims=True)+1e-12
    q=np.vstack([points+epsilon*d,points-epsilon*d])
    return q,np.ones(len(q),dtype=np.float64)/len(q)

def merge(points,rng,fraction):
    n=len(points)
    alive=np.ones(n,dtype=bool)
    tree=cKDTree(points)
    out=[]; weights=[]; target=int(n*fraction/2); pairs=0
    for i in rng.permutation(n):
        if not alive[i]: continue
        _,neighbors=tree.query(points[i],k=min(8,n))
        for j in np.atleast_1d(neighbors)[1:]:
            j=int(j)
            if alive[j]:
                out.append((points[i]+points[j])/2)
                weights.append(2/n)
                alive[i]=alive[j]=False
                pairs+=1
                break
        if pairs>=target: break
    for i in range(n):
        if alive[i]:
            out.append(points[i]); weights.append(1/n)
    return np.asarray(out),np.asarray(weights)

def run():
    records=[]
    for seed in range(20):
        rng=np.random.default_rng(1000+seed)
        points=base_points(seed)
        base=density(points)

        for epsilon in (.005,.01,.02,.03):
            q,w=split(points,rng,epsilon)
            estimate,rmse,coherence=phase_shift_estimate(base,density(q,weights=w))
            records.append({
                "seed":seed,"kind":"split","magnitude":epsilon,
                "spuriousShift":float(np.linalg.norm(estimate)),
                "phaseModelRmse":rmse,"coherence":coherence
            })

        for fraction in (.1,.2,.35):
            q,w=merge(points,rng,fraction)
            estimate,rmse,coherence=phase_shift_estimate(base,density(q,weights=w))
            records.append({
                "seed":seed,"kind":"merge","magnitude":fraction,
                "spuriousShift":float(np.linalg.norm(estimate)),
                "phaseModelRmse":rmse,"coherence":coherence
            })

        for magnitude in (.01,.02,.04,.06,.08):
            direction=rng.normal(size=3)
            direction/=np.linalg.norm(direction)
            truth=direction*magnitude
            for contamination in (0.0,.1,.25,.5):
                stationary=int(len(points)*contamination)
                order=np.arange(len(points)); rng.shuffle(order)
                moving=np.ones(len(points),dtype=bool)
                if stationary:
                    moving[order[:stationary]]=False
                q=points.copy()
                q[moving]+=truth
                estimate,rmse,coherence=phase_shift_estimate(base,density(q))
                records.append({
                    "seed":seed,"kind":"translation","magnitude":magnitude,
                    "stationaryFraction":contamination,
                    "translationError":float(np.linalg.norm(estimate-truth)),
                    "relativeError":float(np.linalg.norm(estimate-truth)/(magnitude+1e-12)),
                    "estimatedMagnitude":float(np.linalg.norm(estimate)),
                    "phaseModelRmse":rmse,"coherence":coherence
                })

    summary={}
    for kind in ("split","merge"):
        rows=[r for r in records if r["kind"]==kind]
        summary[kind]={
            "medianSpuriousShift":float(np.median([r["spuriousShift"] for r in rows])),
            "p95SpuriousShift":float(np.quantile([r["spuriousShift"] for r in rows],.95))
        }
    for contamination in (0.0,.1,.25,.5):
        rows=[r for r in records if r["kind"]=="translation" and r["stationaryFraction"]==contamination]
        summary[f"translation_stationary_{contamination}"]={
            "medianAbsoluteError":float(np.median([r["translationError"] for r in rows])),
            "medianRelativeError":float(np.median([r["relativeError"] for r in rows])),
            "p95RelativeError":float(np.quantile([r["relativeError"] for r in rows],.95)),
            "medianPhaseModelRmse":float(np.median([r["phaseModelRmse"] for r in rows])),
            "medianCoherence":float(np.median([r["coherence"] for r in rows]))
        }

    return {
      "schemaVersion":1,
      "experiment":"local-phase-contamination-v4",
      "recordCount":len(records),
      "configuration":{"seeds":20,"pointsPerNeighborhood":64,"grid":N,
                       "splitEpsilons":[.005,.01,.02,.03],
                       "mergeFractions":[.1,.2,.35],
                       "translations":[.01,.02,.04,.06,.08],
                       "stationaryFractions":[0.0,.1,.25,.5]},
      "summary":summary,
      "decision":"PHASE REMAINS USEFUL FOR COHERENT LOCAL TRANSLATION BUT FAILS AS A STANDALONE MAX-DISPLACEMENT CERTIFICATE UNDER PARTIAL MOTION.",
      "interpretation":[
        "Split and merge resampling produce very small spurious displacement estimates in this synthetic setting.",
        "A coherently translated neighborhood is recovered to numerical precision in the tested low-frequency regime.",
        "When a stationary fraction is mixed with translated support, relative displacement error tracks the stationary fraction approximately: phase behaves like an aggregate/mass-weighted motion signal.",
        "Very high residual coherence does not expose the partial-motion failure reliably.",
        "Therefore phase alone cannot upper-bound the maximum motion of all local support. A certificate requires support partitioning, multi-component modeling, or an independent residual/coverage constraint."
      ],
      "records":records
    }

if __name__=="__main__":
    result=run()
    out=Path("research/results/probes/local-phase-contamination-v4.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"experiment":result["experiment"],"recordCount":result["recordCount"],"decision":result["decision"]},indent=2))
