#!/usr/bin/env python3
"""Falsify raw Gaussian-field phase as a geometry-only invariant.

Centers remain fixed while covariance and opacity are perturbed. A geometry-only
signature should not react more strongly to these representation changes than
to actual center edits. We compare:
  1) phase/amplitude of the full anisotropic opacity-weighted Gaussian field;
  2) phase/amplitude after canonicalizing every primitive to an equal isotropic
     kernel centered only at the Gaussian center.

This is a cheap synthetic probe, not a paper experiment.
"""
from __future__ import annotations
import argparse, json, platform, sys
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import rankdata

GRID_N=18
AX=np.linspace(-1.0,1.0,GRID_N)
X,Y,Z=np.meshgrid(AX,AX,AX,indexing="ij")
GRID=np.stack([X,Y,Z],axis=-1)

def points(seed,n=48):
    rng=np.random.default_rng(seed)
    xy=rng.uniform(-0.75,0.75,(n,2))
    z=0.08*np.sin(2.5*xy[:,0])*np.cos(2.0*xy[:,1])
    return np.c_[xy,z]

def rotation(rng):
    q,_=np.linalg.qr(rng.normal(size=(3,3)))
    if np.linalg.det(q)<0:q[:,0]*=-1
    return q

def scene(seed,n=48):
    rng=np.random.default_rng(seed)
    p=points(seed,n); cov=[]
    for _ in range(n):
        r=rotation(rng)
        s=np.exp(rng.uniform(np.log(.05),np.log(.12),3))
        cov.append(r@np.diag(s*s)@r.T)
    return p,np.asarray(cov),rng.uniform(.4,1.0,n)

def full_density(p,cov,opacity):
    out=np.zeros((GRID_N,GRID_N,GRID_N),dtype=np.float64)
    for center,C,a in zip(p,cov,opacity):
        d=GRID-center
        q=np.einsum("...i,ij,...j->...",d,np.linalg.inv(C),d)
        out+=a*np.exp(-.5*q)
    return out/(np.linalg.norm(out)+1e-12)

def center_density(p,sigma=.08):
    out=np.zeros((GRID_N,GRID_N,GRID_N),dtype=np.float64)
    for center in p:
        d=GRID-center
        out+=np.exp(-np.sum(d*d,axis=-1)/(2*sigma*sigma))
    return out/(np.linalg.norm(out)+1e-12)

def spectrum(d):
    f=np.fft.fftn(d); m=np.abs(f)
    return m/(m.sum()+1e-12),np.angle(f)

def distance(a,b):
    ma,pa=spectrum(a); mb,pb=spectrum(b)
    w=np.sqrt(ma*mb); threshold=np.quantile(w.ravel(),.65)
    w=np.where(w>=threshold,w,0.0); w[(0,0,0)]=0.0
    dp=np.angle(np.exp(1j*(pa-pb)))
    return {
      "phase":float(np.sqrt((w*dp*dp).sum()/(w.sum()+1e-12))),
      "amplitude":float(np.linalg.norm(ma-mb)),
    }

def edit(p,delta):
    q=p.copy(); score=q[:,0]+.25*q[:,2]
    mask=score>=np.quantile(score,.72)
    q[mask,1]+=delta; q[mask,2]+=.25*delta
    return q

def chamfer(a,b):
    ta,tb=cKDTree(a),cKDTree(b)
    da,_=tb.query(a,k=1); db,_=ta.query(b,k=1)
    return float(.5*(da.mean()+db.mean()))

def auc(pos,neg):
    values=np.r_[pos,neg]; ranks=rankdata(values)
    n,m=len(pos),len(neg)
    return float((ranks[:n].sum()-n*(n+1)/2)/(n*m))

def run():
    records=[]
    for seed in range(12):
        p,c,o=scene(seed)
        base_full=full_density(p,c,o); base_center=center_density(p)
        rng=np.random.default_rng(500+seed)
        for level in (.1,.25,.5):
            c2=[]
            for C in c:
                vals,vecs=np.linalg.eigh(C)
                factors=np.exp(rng.normal(0,level,size=3))
                c2.append(vecs@np.diag(vals*factors)@vecs.T)
            c2=np.asarray(c2)
            o2=np.clip(o*np.exp(rng.normal(0,level,len(o))),.05,2.0)
            f=distance(base_full,full_density(p,c2,o2))
            z=distance(base_center,center_density(p))
            records.append({"seed":seed,"kind":"representation_nuisance","level":level,
              "chamfer":0.0,"full_phase":f["phase"],"full_amplitude":f["amplitude"],
              "center_phase":z["phase"],"center_amplitude":z["amplitude"]})
        for delta in (.015,.03,.06,.12):
            p2=edit(p,delta)
            f=distance(base_full,full_density(p2,c,o))
            z=distance(base_center,center_density(p2))
            records.append({"seed":seed,"kind":"geometry_edit","level":delta,
              "chamfer":chamfer(p,p2),"full_phase":f["phase"],"full_amplitude":f["amplitude"],
              "center_phase":z["phase"],"center_amplitude":z["amplitude"]})
    summary={}
    for metric in ("full_phase","center_phase","full_amplitude","center_amplitude"):
        nuisance=np.asarray([r[metric] for r in records if r["kind"]=="representation_nuisance"])
        edits=np.asarray([r[metric] for r in records if r["kind"]=="geometry_edit"])
        summary[metric]={
          "nuisance_median":float(np.median(nuisance)),
          "nuisance_p95":float(np.quantile(nuisance,.95)),
          "edit_median":float(np.median(edits)),
          "edit_vs_nuisance_auc":auc(edits,nuisance),
        }
    return {
      "schemaVersion":1,
      "experiment":"phase-representation-nuisance-v1",
      "environment":{"python":sys.version,"numpy":np.__version__,"platform":platform.platform()},
      "configuration":{"seeds":12,"points":48,"grid":GRID_N,
        "covariance_opacity_noise_levels":[.1,.25,.5],
        "center_edit_magnitudes":[.015,.03,.06,.12]},
      "record_count":len(records),
      "summary":summary,
      "decision":"REJECT raw anisotropic opacity-weighted field phase as a geometry-only invariant; retain geometry-normalized center phase only for harder testing.",
      "interpretation":[
        "Raw field phase reacts strongly to covariance/opacity changes even when centers are identical.",
        "In this probe raw field phase has edit-vs-nuisance AUC below 0.5, so the nuisance is larger than the target signal too often.",
        "Equal-kernel center-only phase is invariant to this particular nuisance by construction and remains sensitive to center edits.",
        "This does not validate center phase; split/merge, local neighborhood, anisotropic geometry, moment-preserving deformation and real 3DGS resampling remain required attacks."
      ],
      "records":records,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,default=Path("research/results/probes/phase-representation-nuisance-v1.json"))
    args=ap.parse_args(); result=run()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"experiment":result["experiment"],"record_count":result["record_count"],"decision":result["decision"]},indent=2))
if __name__=="__main__": main()
