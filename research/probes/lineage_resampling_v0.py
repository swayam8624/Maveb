#!/usr/bin/env python3
"""Synthetic stress test for Gaussian identity under repeated resampling.

This probe does not claim that explicit lineage is a solved method. It quantifies
how quickly sequential nearest-neighbour identity can drift when a representation
undergoes split, merge, prune and small re-optimization jitter.

Ground-truth ancestry is propagated from the synthetic resampling operations.
The baseline tracker propagates only the ancestry of each new primitive's nearest
primitive in the immediately previous revision.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree


def initial(seed: int, count: int = 200):
    rng=np.random.default_rng(seed)
    points=rng.uniform(-1.0,1.0,(count,3))
    points[count//2:]=points[:count//2]+np.array([0.0,0.12,0.0])+rng.normal(0,0.005,(count//2,3))
    ancestry=[{i} for i in range(count)]
    return points,ancestry


def resample(rng, points, ancestry, split_fraction=.08, merge_fraction=.05,
             prune_fraction=.04, jitter=.015):
    n=len(points)
    prune=set(rng.choice(n,size=max(1,int(n*prune_fraction)),replace=False))
    alive=[i for i in range(n) if i not in prune]
    rng.shuffle(alive)

    tree=cKDTree(points[alive])
    used=set()
    merge_pairs=[]
    target=max(1,int(n*merge_fraction/2))
    for i in alive:
        if i in used:
            continue
        _,neighbors=tree.query(points[i],k=min(6,len(alive)))
        for local in np.atleast_1d(neighbors)[1:]:
            j=alive[int(local)]
            if j not in used and j!=i:
                merge_pairs.append((i,j))
                used.update((i,j))
                break
        if len(merge_pairs)>=target:
            break

    next_points=[]
    next_ancestry=[]
    for i,j in merge_pairs:
        next_points.append((points[i]+points[j])/2+rng.normal(0,jitter,3))
        next_ancestry.append(set(ancestry[i])|set(ancestry[j]))

    remaining=[i for i in alive if i not in used]
    split_count=max(1,int(len(remaining)*split_fraction))
    split=set(rng.choice(remaining,size=min(split_count,len(remaining)),replace=False))
    for i in remaining:
        if i in split:
            delta=rng.normal(0,jitter,3)
            next_points.extend((points[i]+delta,points[i]-delta))
            next_ancestry.extend((set(ancestry[i]),set(ancestry[i])))
        else:
            next_points.append(points[i]+rng.normal(0,jitter,3))
            next_ancestry.append(set(ancestry[i]))

    return np.asarray(next_points),next_ancestry


def one_chain(seed: int, revisions: int = 20):
    points,true_ancestry=initial(seed)
    tracked=[set(value) for value in true_ancestry]
    rng=np.random.default_rng(5000+seed)
    records=[]

    for revision in range(1,revisions+1):
        next_points,next_true=resample(rng,points,true_ancestry)
        tree=cKDTree(points)
        _,nearest=tree.query(next_points,k=1)
        next_tracked=[set(tracked[int(index)]) for index in nearest]

        recalls=[]
        exact=[]
        for truth,predicted in zip(next_true,next_tracked):
            recalls.append(len(truth & predicted)/len(truth))
            exact.append(truth==predicted)

        records.append({
            "revision":revision,
            "primitiveCount":len(next_points),
            "meanGroundTruthAncestors":float(np.mean([len(value) for value in next_true])),
            "nearestNeighborAncestorRecall":float(np.mean(recalls)),
            "nearestNeighborExactAncestryRate":float(np.mean(exact)),
        })
        points,true_ancestry,tracked=next_points,next_true,next_tracked
    return records


def run(seeds=30,revisions=20):
    chains=[one_chain(seed,revisions) for seed in range(seeds)]
    summary=[]
    for revision in range(revisions):
        rows=[chain[revision] for chain in chains]
        summary.append({
            "revision":revision+1,
            "primitiveCountMean":float(np.mean([row["primitiveCount"] for row in rows])),
            "meanGroundTruthAncestors":float(np.mean([row["meanGroundTruthAncestors"] for row in rows])),
            "nearestNeighborAncestorRecallMean":float(np.mean([row["nearestNeighborAncestorRecall"] for row in rows])),
            "nearestNeighborExactAncestryRateMean":float(np.mean([row["nearestNeighborExactAncestryRate"] for row in rows])),
        })
    return {
        "schemaVersion":1,
        "experiment":"lineage-vs-sequential-nearest-neighbor-v0",
        "configuration":{
            "seeds":seeds,"revisions":revisions,"initialPrimitives":200,
            "splitFraction":0.08,"mergeFraction":0.05,"pruneFraction":0.04,"jitter":0.015,
            "repeatedNearDuplicateStructure":True
        },
        "summary":summary,
        "decision":"PROMOTE S4 BENCHMARKING: sequential nearest-neighbor ancestry degrades over repeated resampling; next compare against stronger ICP/OT/covariance/topology baselines and require downstream benefit.",
    }


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    result=run()
    text=json.dumps(result,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text)
    else:
        print(text,end="")
